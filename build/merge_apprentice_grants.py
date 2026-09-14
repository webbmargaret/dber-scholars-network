#!/usr/bin/env python3
"""
Build data/apprentice_grants.json from the Apprentice Faculty Grant Awardees
spreadsheet. Never reads or emits the Email Addresses column — this site's
established policy (see about.html) excludes emails entirely.

Matches each recipient against the existing roster (data/scholars.json) by normalized
name + normalized institution. A row that doesn't match confidently is kept in the
output with matched_scholar_id: null rather than guessed or dropped — apprentice-grants.html
lists it either way. No new scholar nodes are created for unmatched names.

Requires openpyxl. Must be run after build_data.py.

Usage:
    python3 build/merge_apprentice_grants.py "/path/to/Apprentice Faculty Grant Awardees 1997-2025 (1).xlsx"
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_data import canonicalize_institution_name  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"


def name_key(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def inst_key(name: str) -> str:
    return canonicalize_institution_name(name or "").strip().lower()


def build(xlsx_path: Path):
    scholars = json.loads((DATA_DIR / "scholars.json").read_text())

    scholars_by_name: dict[str, list[dict]] = defaultdict(list)
    for s in scholars:
        scholars_by_name[name_key(s["name"])].append(s)

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    header = [str(c).strip() if c else "" for c in rows[0]]
    col = {h: i for i, h in enumerate(header)}

    grants = []
    matched = 0
    for row in rows[1:]:
        if row is None or all(v is None for v in row):
            continue
        raw_name = row[col["NAME"]]
        if not raw_name or not str(raw_name).strip():
            continue
        name = str(raw_name).strip()
        raw_year = row[col["AWARD YEAR"]]
        award_year = int(raw_year) if raw_year is not None else None
        institution = str(row[col["INSTITUTION"]]).strip() if row[col.get("INSTITUTION", -1)] else ""
        notes_idx = col.get("Notes")
        notes = str(row[notes_idx]).strip() if notes_idx is not None and row[notes_idx] else ""
        # Email Addresses column (if present) is intentionally never read.

        candidates = scholars_by_name.get(name_key(name), [])
        matched_id = None
        if len(candidates) == 1:
            matched_id = candidates[0]["id"]
        elif len(candidates) > 1:
            target_inst = inst_key(institution)
            inst_matches = [
                c for c in candidates
                if any(inst_key(i["name"]) == target_inst for i in c["institution"])
            ]
            if len(inst_matches) == 1:
                matched_id = inst_matches[0]["id"]

        if matched_id:
            matched += 1

        grants.append({
            "award_year": award_year,
            "name": name,
            "institution": institution,
            "notes": notes,
            "matched_scholar_id": matched_id,
        })

    grants.sort(key=lambda g: (-(g["award_year"] or 0), g["name"]))
    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / "apprentice_grants.json").write_text(
        json.dumps(grants, indent=1, ensure_ascii=False)
    )

    print(f"Wrote {len(grants)} apprentice grant records to {DATA_DIR / 'apprentice_grants.json'}")
    print(f"  {matched} matched to an existing scholar; {len(grants) - matched} unmatched")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <path-to-apprentice-grants.xlsx>")
        sys.exit(1)
    build(Path(sys.argv[1]).expanduser())
