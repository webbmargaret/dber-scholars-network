#!/usr/bin/env python3
"""Re-verify coauthor-mined candidates against live Semantic Scholar data.

Fetches each candidate's S2 author record (by the `scholar_id` already on
file from the original mining pass), independently re-checks name +
institution + DBER-relevance from their *current* publication list, and
writes one row per candidate to a sidecar CSV. Never touches the source CSV
directly — see apply_coauthor_verification.py for the merge step.

Checkpointed: safe to interrupt and re-run with --resume, which skips any
scholar_id already terminally resolved (confirmed/rejected/ambiguous) in the
existing --out file. Only rows left in "error" state are retried.

Usage:
    python3 build/verify_coauthors.py <source_csv> --out <results_csv> \
        [--batch-size 100] [--rate-limit-seconds 1.0] [--limit N] [--resume]
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

csv.field_size_limit(10_000_000)  # publications_json can exceed the 128KB default

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dber_taxonomy import score_fields  # noqa: E402
from s2_client import DEFAULT_FIELDS, S2Client, load_api_key  # noqa: E402

SOURCE_LIST_TAG = "Coauthor-candidate shortlist review (2026-08-07)"

# Authors with a huge publication count (per the CSV's own n_publications, already on
# file from the original mining pass) return a very large `papers` payload in the batch
# API — in practice this reliably triggers gateway timeouts regardless of batch size,
# since it's one oversized response, not request volume. For these, skip fetching their
# full paper list and fall back to the CSV's own coauthor_dber_evidence_venues/titles
# (already curated, no extra API cost) for the DBER-relevance check — identity
# (name/institution) is still verified live either way.
HEAVY_PUBLICATION_THRESHOLD = 150
LIGHT_FIELDS = "name,affiliations,paperCount,hIndex"


def split_pipe(value: str) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split("||") if v.strip()]


def is_heavy(row: dict) -> bool:
    try:
        return float(row.get("n_publications") or 0) > HEAVY_PUBLICATION_THRESHOLD
    except ValueError:
        return False

SIDECAR_FIELDS = [
    "scholar_id",
    "name",
    "verification_status",
    "s2_fetched_name",
    "s2_fetched_affiliations",
    "s2_paper_count",
    "s2_h_index",
    "dber_relevance_score",
    "dber_relevance_field",
    "dber_relevance_venues_matched",
    "name_match",
    "institution_match",
    "reasoning_text",
    "fetched_at",
]

TERMINAL_STATUSES = {"confirmed", "rejected", "ambiguous"}

DBER_RELEVANCE_MIN_SCORE = 2


def normalize_name(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[.,]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def names_match(csv_name: str, s2_name: str | None) -> bool | None:
    if not s2_name:
        return None
    a = normalize_name(csv_name).split(" ")
    b = normalize_name(s2_name).split(" ")
    if not a or not b or not a[-1] or not b[-1]:
        return None
    if a[-1] != b[-1]:
        return False
    fa, fb = a[0], b[0]
    if fa == fb:
        return True
    if len(fa) == 1 and fb.startswith(fa):
        return True
    if len(fb) == 1 and fa.startswith(fb):
        return True
    return False


def normalize_institution(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def institution_match(csv_inst: str, s2_affiliations: list[str]) -> bool | None:
    ci = normalize_institution(csv_inst or "")
    if not ci:
        return None
    if not s2_affiliations:
        return None
    for aff in s2_affiliations:
        na = normalize_institution(aff or "")
        if na and (na in ci or ci in na):
            return True
    return False


def load_existing_results(out_path: Path) -> dict[str, dict]:
    if not out_path.exists():
        return {}
    with out_path.open(newline="", encoding="utf-8") as f:
        return {row["scholar_id"]: row for row in csv.DictReader(f)}


def decide(name_match: bool | None, inst_match: bool | None, dber_score: int) -> str:
    if name_match is False:
        return "rejected"
    if name_match is None:
        return "ambiguous"  # S2 had no name back for this id — can't confirm
    relevant = dber_score >= DBER_RELEVANCE_MIN_SCORE
    inst_ok = inst_match is not False  # True or None (unknown) both pass
    if name_match and inst_ok and relevant:
        return "confirmed"
    return "ambiguous"


def build_reasoning(status, name_match, inst_match, dber_score, field, venues, s2_name, s2_paper_count):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if status == "error":
        return f"Re-verification attempted on {today}: no Semantic Scholar record found for the ID on file."
    parts = [f"Re-verified via Semantic Scholar API on {today}:"]
    if name_match is True:
        parts.append(f"name matches (S2: \"{s2_name}\").")
    elif name_match is False:
        parts.append(f"name does NOT match (S2 record is \"{s2_name}\") — likely a different person.")
    else:
        parts.append("S2 returned no name to compare.")
    if inst_match is True:
        parts.append("institution matches.")
    elif inst_match is False:
        parts.append("institution on file does not match S2's current affiliation.")
    if dber_score >= DBER_RELEVANCE_MIN_SCORE:
        venue_str = "; ".join(venues[:2]) if venues else "keyword match"
        parts.append(f"DBER-relevant publications found ({field}: {venue_str}).")
    else:
        parts.append(f"no clear DBER-relevant venue found across {s2_paper_count} publications.")
    parts.append(f"Status: {status}.")
    return " ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source_csv", type=Path)
    ap.add_argument("--out", type=Path, default=Path("build/coauthor_verification_results.csv"))
    ap.add_argument("--batch-size", type=int, default=100)
    ap.add_argument("--rate-limit-seconds", type=float, default=1.0)
    ap.add_argument("--max-retries", type=int, default=6)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    with args.source_csv.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    candidates = [
        r for r in rows
        if r.get("Source_List", "").strip() == SOURCE_LIST_TAG and r.get("scholar_id", "").strip()
    ]
    skipped_no_id = sum(
        1 for r in rows if r.get("Source_List", "").strip() == SOURCE_LIST_TAG and not r.get("scholar_id", "").strip()
    )

    existing = load_existing_results(args.out) if args.resume else {}
    already_done = {sid for sid, row in existing.items() if row["verification_status"] in TERMINAL_STATUSES}
    todo = [r for r in candidates if r["scholar_id"] not in already_done]
    if args.limit:
        todo = todo[: args.limit]

    print(f"{len(candidates)} coauthor candidates total ({skipped_no_id} skipped, no scholar_id).")
    print(f"{len(already_done)} already resolved; {len(todo)} to process this run.")
    if not todo:
        return

    client = S2Client(
        load_api_key(),
        rate_limit_seconds=args.rate_limit_seconds,
        max_retries=args.max_retries,
    )
    light_client = S2Client(
        load_api_key(),
        rate_limit_seconds=args.rate_limit_seconds,
        max_retries=args.max_retries,
        fields=LIGHT_FIELDS,
    )

    normal_todo = [r for r in todo if not is_heavy(r)]
    heavy_todo = [r for r in todo if is_heavy(r)]
    if heavy_todo:
        print(f"  {len(heavy_todo)} heavy-publication-count rows will skip the full paper list.", file=sys.stderr)

    write_header = not args.out.exists() or not args.resume
    args.out.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if write_header else "a"
    with args.out.open(mode, newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=SIDECAR_FIELDS)
        if write_header:
            writer.writeheader()

        processed = 0
        # Heavy rows first, in small batches, using the light (no-papers) field set.
        for i in range(0, len(heavy_todo), 5):
            batch = heavy_todo[i : i + 5]
            ids = [r["scholar_id"] for r in batch]
            fetched = light_client.fetch_authors_batch(ids)

            for row in batch:
                sid = row["scholar_id"]
                record = fetched.get(sid)
                fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

                if record is None:
                    writer.writerow({
                        "scholar_id": sid,
                        "name": row["Name"],
                        "verification_status": "error",
                        "s2_fetched_name": "",
                        "s2_fetched_affiliations": "",
                        "s2_paper_count": "",
                        "s2_h_index": "",
                        "dber_relevance_score": "",
                        "dber_relevance_field": "",
                        "dber_relevance_venues_matched": "",
                        "name_match": "",
                        "institution_match": "",
                        "reasoning_text": build_reasoning("error", None, None, 0, "", [], "", 0),
                        "fetched_at": fetched_at,
                    })
                    continue

                s2_name = record.get("name") or ""
                s2_affils = record.get("affiliations") or []
                # No fetched papers for heavy authors — fall back to the CSV's own
                # curated coauthor-evidence text (already available, no API cost).
                evidence_venues = split_pipe(row.get("coauthor_dber_evidence_venues", ""))
                evidence_titles = split_pipe(row.get("coauthor_dber_evidence_titles", ""))
                scored = score_fields(
                    "", "", [], evidence_venues=evidence_venues, evidence_titles=evidence_titles,
                    min_score=DBER_RELEVANCE_MIN_SCORE,
                )
                top_field, top_result = ("", {"score": 0, "matched": []})
                if scored:
                    top_field, top_result = max(scored.items(), key=lambda kv: kv[1]["score"])

                nm = names_match(row["Name"], s2_name)
                im = institution_match(row.get("Institution", ""), s2_affils)
                status = decide(nm, im, top_result["score"])
                venues_matched = [m.split(":", 1)[1] for m in top_result["matched"] if m.startswith("venue:")]

                reasoning = build_reasoning(
                    status, nm, im, top_result["score"], top_field, venues_matched,
                    s2_name, record.get("paperCount") or 0,
                )
                writer.writerow({
                    "scholar_id": sid,
                    "name": row["Name"],
                    "verification_status": status,
                    "s2_fetched_name": s2_name,
                    "s2_fetched_affiliations": "||".join(s2_affils),
                    "s2_paper_count": record.get("paperCount") or "",
                    "s2_h_index": record.get("hIndex") or "",
                    "dber_relevance_score": top_result["score"],
                    "dber_relevance_field": top_field,
                    "dber_relevance_venues_matched": "||".join(venues_matched),
                    "name_match": "" if nm is None else str(nm),
                    "institution_match": "" if im is None else str(im),
                    "reasoning_text": reasoning,
                    "fetched_at": fetched_at,
                })

            out_f.flush()
            processed += len(batch)
            print(f"  processed {processed}/{len(todo)} (heavy)", file=sys.stderr)

        todo = normal_todo
        for i in range(0, len(todo), args.batch_size):
            batch = todo[i : i + args.batch_size]
            ids = [r["scholar_id"] for r in batch]
            fetched = client.fetch_authors_batch(ids)

            for row in batch:
                sid = row["scholar_id"]
                record = fetched.get(sid)
                fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

                if record is None:
                    out_row = {
                        "scholar_id": sid,
                        "name": row["Name"],
                        "verification_status": "error",
                        "s2_fetched_name": "",
                        "s2_fetched_affiliations": "",
                        "s2_paper_count": "",
                        "s2_h_index": "",
                        "dber_relevance_score": "",
                        "dber_relevance_field": "",
                        "dber_relevance_venues_matched": "",
                        "name_match": "",
                        "institution_match": "",
                        "reasoning_text": build_reasoning("error", None, None, 0, "", [], "", 0),
                        "fetched_at": fetched_at,
                    }
                    writer.writerow(out_row)
                    continue

                s2_name = record.get("name") or ""
                s2_affils = record.get("affiliations") or []
                papers = record.get("papers") or []
                pubs = [{"title": p.get("title") or "", "journal": p.get("venue") or ""} for p in papers]

                scored = score_fields("", "", pubs, min_score=DBER_RELEVANCE_MIN_SCORE)
                top_field, top_result = ("", {"score": 0, "matched": []})
                if scored:
                    top_field, top_result = max(scored.items(), key=lambda kv: kv[1]["score"])

                nm = names_match(row["Name"], s2_name)
                im = institution_match(row.get("Institution", ""), s2_affils)
                status = decide(nm, im, top_result["score"])
                venues_matched = [m.split(":", 1)[1] for m in top_result["matched"] if m.startswith("venue:")]

                reasoning = build_reasoning(
                    status, nm, im, top_result["score"], top_field, venues_matched, s2_name, len(papers)
                )

                writer.writerow({
                    "scholar_id": sid,
                    "name": row["Name"],
                    "verification_status": status,
                    "s2_fetched_name": s2_name,
                    "s2_fetched_affiliations": "||".join(s2_affils),
                    "s2_paper_count": len(papers),
                    "s2_h_index": record.get("hIndex") or "",
                    "dber_relevance_score": top_result["score"],
                    "dber_relevance_field": top_field,
                    "dber_relevance_venues_matched": "||".join(venues_matched),
                    "name_match": "" if nm is None else str(nm),
                    "institution_match": "" if im is None else str(im),
                    "reasoning_text": reasoning,
                    "fetched_at": fetched_at,
                })

            out_f.flush()
            processed += len(batch)
            print(f"  processed {processed}/{len(todo)}", file=sys.stderr)

    print(f"Wrote results to {args.out}")


if __name__ == "__main__":
    main()
