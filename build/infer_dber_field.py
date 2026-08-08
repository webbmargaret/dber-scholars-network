#!/usr/bin/env python3
"""Infer DBER_Field for people who don't have a hand-sourced one, using
the dber_taxonomy keyword/venue classifier against text already in the CSV
(Research_Interests, Dissertation_Title, publications_json, and — for
coauthor-mined candidates — the curated coauthor_dber_evidence_venues/titles
columns). No API calls; pure local computation.

Only runs on rows where DBER_Field is currently blank (per project decision:
inference fills gaps, it doesn't cross-check existing hand-sourced tags).
Never mutates the input file — always writes to an explicit --out path.

Usage:
    python3 build/infer_dber_field.py <source_csv> \
        --out <source_csv_stem>_with_inferred_fields.csv [--min-score 2] [--limit N]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dber_taxonomy import FIELD_TAXONOMY, score_fields  # noqa: E402


def split_pipe(value: str) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split("||") if v.strip()]


def infer_row(row: dict, min_score: int) -> dict | None:
    if row.get("DBER_Field", "").strip():
        return None  # has a hand-sourced tag already — not our job to touch it

    try:
        publications = json.loads(row.get("publications_json") or "[]")
    except json.JSONDecodeError:
        publications = []

    evidence_venues = split_pipe(row.get("coauthor_dber_evidence_venues", ""))
    evidence_titles = split_pipe(row.get("coauthor_dber_evidence_titles", ""))

    scored = score_fields(
        row.get("Research_Interests", ""),
        row.get("Dissertation_Title", ""),
        publications,
        evidence_venues=evidence_venues,
        evidence_titles=evidence_titles,
        min_score=min_score,
    )
    if not scored:
        return None

    codes = sorted(scored, key=lambda c: scored[c]["score"], reverse=True)
    return {
        "DBER_Field_inferred": "||".join(codes),
        "DBER_Field_inferred_confidence": "||".join(scored[c]["tier"] for c in codes),
        "DBER_Field_inferred_evidence": "||".join(
            "; ".join(scored[c]["matched"][:2]) for c in codes
        ),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source_csv", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--min-score", type=int, default=2)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    out_path = args.out or args.source_csv.with_name(
        args.source_csv.stem + "_with_inferred_fields.csv"
    )

    with args.source_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    new_cols = ["DBER_Field_inferred", "DBER_Field_inferred_confidence", "DBER_Field_inferred_evidence"]
    for c in new_cols:
        if c not in fieldnames:
            fieldnames.append(c)
        for row in rows:
            row.setdefault(c, "")

    gap_rows = [r for r in rows if not r.get("DBER_Field", "").strip()]
    already_tagged = len(rows) - len(gap_rows)
    to_process = gap_rows[: args.limit] if args.limit else gap_rows

    tally = {code: 0 for code in FIELD_TAXONOMY}
    inferred_count = 0
    no_evidence_count = 0

    for row in to_process:
        result = infer_row(row, args.min_score)
        if result is None:
            no_evidence_count += 1
            continue
        row.update(result)
        inferred_count += 1
        for code in result["DBER_Field_inferred"].split("||"):
            tally[code] = tally.get(code, 0) + 1

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"{len(rows)} total rows; {already_tagged} already have a hand-sourced DBER_Field.")
    print(f"{len(gap_rows)} gap rows considered this run ({len(to_process)} processed).")
    print(f"  inferred a tag for: {inferred_count}")
    print(f"  no evidence found:  {no_evidence_count}")
    print("Tag counts:")
    for code, count in sorted(tally.items(), key=lambda kv: -kv[1]):
        if count:
            print(f"  {code}: {count}")
    print(f"Wrote {out_path}")
    print("Not written to the working CSV filename — review, then promote manually.")


if __name__ == "__main__":
    main()
