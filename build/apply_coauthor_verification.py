#!/usr/bin/env python3
"""Merge verify_coauthors.py's sidecar results back into a copy of the source
CSV. Updates only pre-existing columns (coauthor_identity_confirmed,
coauthor_identity_updated, review_needed, match_confidence) and appends a
plain-language explanation to Notes — no new columns, no row deletions,
regardless of verification outcome (a "rejected" name-mismatch stays in the
dataset, flagged for a human to remove by hand, per project policy).

Never writes to the working CSV filename directly — always to an explicit
--out path, so the result can be reviewed/diffed before being promoted.

Usage:
    python3 build/apply_coauthor_verification.py <source_csv> <sidecar_csv> --out <merged_csv>
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

csv.field_size_limit(10_000_000)  # publications_json can exceed the 128KB default

SOURCE_LIST_TAG = "Coauthor-candidate shortlist review (2026-08-07)"

STATUS_TO_CONFIRMED = {
    "confirmed": "True",
    "rejected": "False",
    "ambiguous": "False",
    "error": None,  # leave whatever was already there
}
STATUS_TO_REVIEW_NEEDED = {
    "confirmed": "False",
    "rejected": "True",
    "ambiguous": "True",
    "error": "True",
}
STATUS_TO_CONFIDENCE = {
    "confirmed": "high",
    "rejected": "low",
    "ambiguous": "medium",
    "error": None,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source_csv", type=Path)
    ap.add_argument("sidecar_csv", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    with args.sidecar_csv.open(newline="", encoding="utf-8") as f:
        # Keyed by (scholar_id, name), not scholar_id alone — a handful of source-CSV
        # rows share an S2 author ID with an unrelated coauthor candidate (an upstream
        # ID mix-up, e.g. "Tyler Sullivan" vs. candidate "Zachary Sullivan"). Keying on
        # id alone would silently apply one person's re-verification result to a
        # different, already-hand-sourced scholar's row.
        sidecar_by_key = {(row["scholar_id"], row["name"]): row for row in csv.DictReader(f)}

    with args.source_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    status_counts = Counter()
    review_needed_before = sum(1 for r in rows if r.get("review_needed", "").strip() == "True")
    updated = 0
    skipped_id_collision = 0

    for row in rows:
        if row.get("Source_List", "").strip() != SOURCE_LIST_TAG:
            continue
        sid = row.get("scholar_id", "").strip()
        key = (sid, row.get("Name", "").strip())
        if key not in sidecar_by_key:
            if sid and any(sid == k[0] for k in sidecar_by_key):
                skipped_id_collision += 1
            continue
        result = sidecar_by_key[key]
        status = result["verification_status"]
        status_counts[status] += 1
        updated += 1

        confirmed = STATUS_TO_CONFIRMED[status]
        if confirmed is not None:
            row["coauthor_identity_confirmed"] = confirmed
        row["coauthor_identity_updated"] = "True"
        row["review_needed"] = STATUS_TO_REVIEW_NEEDED[status]
        confidence = STATUS_TO_CONFIDENCE[status]
        if confidence is not None:
            row["match_confidence"] = confidence

        reasoning = result.get("reasoning_text", "").strip()
        if reasoning:
            existing_notes = row.get("Notes", "").strip()
            row["Notes"] = f"{existing_notes} | {reasoning}" if existing_notes else reasoning

    with args.out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    review_needed_after = sum(1 for r in rows if r.get("review_needed", "").strip() == "True")

    print(f"Updated {updated} rows from {args.sidecar_csv}.")
    if skipped_id_collision:
        print(f"Skipped {skipped_id_collision} row(s) sharing a scholar_id with an unrelated candidate (name didn't match).")
    print("Status breakdown:")
    for status, count in status_counts.most_common():
        print(f"  {status}: {count}")
    print(f"review_needed=True: {review_needed_before} -> {review_needed_after}")
    print(f"Wrote merged CSV to {args.out}")
    print("This file was NOT written to the working CSV filename — review it, then copy it over manually if it looks right.")


if __name__ == "__main__":
    main()
