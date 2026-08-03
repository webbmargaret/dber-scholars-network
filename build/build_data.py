#!/usr/bin/env python3
"""
Build data/scholars.json, data/groups.json, data/build_meta.json from the
DBER scholars merged CSV. Run locally; commit the output. Never reads or
emits the Email column.

Usage:
    python3 build/build_data.py /path/to/1000_DBER_scholars_merged.csv
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"

# Columns kept for display, excluding Name (handled separately) and Email (never kept).
DISPLAY_COLUMNS = [
    "Institution",
    "DBER_Field",
    "Research_Interests",
    "Position_Title",
    "Position_Type",
    "Expert_Type",
    "Program",
    "PhD_Year",
    "Dissertation_Title",
    "Current_Position",
    "Phase",
    "Notes",
    "Source_List",
    "Data_Quality_Flag",
]

# Grouping/hub attributes only — Expert_Type and Source_List are deliberately excluded.
GROUP_ATTRS = ["institution", "program", "dber_field", "phd_era"]

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def scrub_emails(value: str) -> str:
    """Safety net: the source CSV has email addresses miskeyed into non-Email columns
    for a handful of rows (e.g. Position_Title holding a bare email address with the
    row's actual Email cell left blank). Strip any email-shaped substring from every
    display field, not just the dedicated Email column, since dropping only the Email
    column isn't sufficient to keep emails out of the published site."""
    if not value:
        return value
    return EMAIL_RE.sub("", value).strip()


SOURCE_LIST_FIXES = {
    "PhD Alumni List + ProQuest/Repository Research (Aug 2026)":
        "PhD Alumni List || ProQuest/Repository Research (Aug 2026)",
}


def slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "unnamed"


def split_pipe(value: str) -> list[str]:
    """Split on `||` only. Never split on `+` — some institution names contain it."""
    if not value:
        return []
    return [v.strip() for v in value.split("||") if v.strip()]


def split_dber_field(value: str) -> list[str]:
    """DBER_Field mixes `||` and `;` as separators (e.g. "EER; CER")."""
    if not value:
        return []
    parts = re.split(r"\|\||;", value)
    out, seen = [], set()
    for p in parts:
        p = p.strip()
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def coerce_phd_year(value: str) -> int | None:
    """Handles float-string artifacts like "2007.0"."""
    if not value or not value.strip():
        return None
    try:
        return int(float(value.strip().split("||")[0].split(";")[0]))
    except ValueError:
        return None


def phd_era(year: int | None) -> str | None:
    if year is None:
        return None
    if year < 2000:
        return "Pre-2000"
    band_start = (year // 5) * 5
    return f"{band_start}–{band_start + 4}"


def completeness_score(row: dict) -> float:
    filled = sum(1 for c in DISPLAY_COLUMNS if row.get(c, "").strip())
    return round(filled / len(DISPLAY_COLUMNS), 3)


def build(csv_path: Path):
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    scholars = []
    fill_counts = defaultdict(int)
    group_members = {attr: defaultdict(list) for attr in GROUP_ATTRS}

    for idx, row in enumerate(rows):
        name = row.get("Name", "").strip()
        if not name:
            continue

        # Scrub email-shaped substrings out of every field before anything else reads
        # from `row` — the source CSV has a few rows with an email miskeyed into a
        # non-Email column (e.g. Position_Title) rather than the Email column itself.
        for c in DISPLAY_COLUMNS:
            row[c] = scrub_emails(row.get(c, ""))

        for c in DISPLAY_COLUMNS:
            if row.get(c, "").strip():
                fill_counts[c] += 1

        raw_source_list = row.get("Source_List", "").strip()
        raw_source_list = SOURCE_LIST_FIXES.get(raw_source_list, raw_source_list)

        institutions = split_pipe(row.get("Institution", ""))
        programs = split_pipe(row.get("Program", ""))
        dber_fields = split_dber_field(row.get("DBER_Field", ""))
        year = coerce_phd_year(row.get("PhD_Year", ""))
        era = phd_era(year)

        person_id = f"{idx:04d}-{slugify(name)}"

        scholar = {
            "id": person_id,
            "name": name,
            "institution": institutions,
            "program": programs,
            "dber_field": dber_fields,
            "research_interests": row.get("Research_Interests", "").strip(),
            "position_title": row.get("Position_Title", "").strip(),
            "position_type": row.get("Position_Type", "").strip(),
            "expert_type": split_pipe(row.get("Expert_Type", "")),
            "phd_year": year,
            "phd_era": era,
            "dissertation_title": row.get("Dissertation_Title", "").strip(),
            "position_or_advisor_note": row.get("Current_Position", "").strip(),
            "phase": row.get("Phase", "").strip(),
            "notes": row.get("Notes", "").strip(),
            "source_list": split_pipe(raw_source_list),
            "data_quality_flag": row.get("Data_Quality_Flag", "").strip(),
            "completeness": completeness_score(row),
        }
        scholars.append(scholar)

        for inst in institutions:
            group_members["institution"][inst].append(person_id)
        for prog in programs:
            group_members["program"][prog].append(person_id)
        for field in dber_fields:
            group_members["dber_field"][field].append(person_id)
        if era:
            group_members["phd_era"][era].append(person_id)

    groups = {}
    for attr, members_by_label in group_members.items():
        items = [
            {
                "groupId": f"{attr}:{slugify(label)}",
                "label": label,
                "count": len(member_ids),
                "memberIds": member_ids,
            }
            for label, member_ids in members_by_label.items()
        ]
        items.sort(key=lambda g: g["count"], reverse=True)
        groups[attr] = items

    build_meta = {
        "built": datetime.now().isoformat(timespec="seconds"),
        "row_count": len(scholars),
        "source_file": csv_path.name,
        "fill_counts": dict(fill_counts),
        "group_attribute_counts": {attr: len(items) for attr, items in groups.items()},
    }

    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / "scholars.json").write_text(json.dumps(scholars, indent=1, ensure_ascii=False))
    (DATA_DIR / "groups.json").write_text(json.dumps(groups, indent=1, ensure_ascii=False))
    (DATA_DIR / "build_meta.json").write_text(json.dumps(build_meta, indent=2, ensure_ascii=False))

    print(f"Wrote {len(scholars)} scholars to {DATA_DIR / 'scholars.json'}")
    for attr, items in groups.items():
        print(f"  {attr}: {len(items)} groups (top: {items[0]['label']!r} = {items[0]['count']})")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <path-to-DBER_scholars_merged.csv>")
        sys.exit(1)
    build(Path(sys.argv[1]).expanduser())
