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
# Expert_Type, Phase, Source_List, and Data_Quality_Flag are intentionally excluded —
# they're internal data-collection metadata (how/where a record was sourced), not
# information this public site publishes.
DISPLAY_COLUMNS = [
    "Institution",
    "DBER_Field",
    "Research_Interests",
    "Position_Title",
    "Position_Type",
    "Program",
    "PhD_Year",
    "Dissertation_Title",
    "Current_Position",
    "Notes",
]

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


def slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "unnamed"


def split_pipe(value: str) -> list[str]:
    """Split on `||` only. Never split on `+` — some institution names contain it."""
    if not value:
        return []
    return [v.strip() for v in value.split("||") if v.strip()]


# Simple whole-string name variants -> one canonical spelling. Checked against the
# lowercased, trimmed raw string when nothing more specific (an override or a split)
# applies.
CANONICAL_INSTITUTION_NAMES = {
    "clemson": "Clemson University",
    "cornell": "Cornell University",
    "ohio state university": "The Ohio State University",
}

# Exact raw `Institution` strings that pack a multi-institution history, a joint
# program, or a career move into one piece of text, with no consistent delimiter.
# Hand-curated because the dataset only has a few dozen of these total — a generic
# splitter risks mangling legitimate comma-bearing names like "University of
# Nevada, Reno". `status` is "former" or "current" only where the source text (or,
# for two entries, unambiguous language elsewhere in that person's record) says so
# outright; otherwise "unknown" — no institution history is guessed or invented.
INSTITUTION_STRING_OVERRIDES: dict[str, list[dict[str, str]]] = {
    "Cornell University (formerly CU Boulder)": [
        {"name": "Cornell University", "status": "current", "note": ""},
        {"name": "University of Colorado Boulder", "status": "former", "note": ""},
    ],
    "North Carolina State University (moved 2025)": [
        {"name": "North Carolina State University", "status": "current", "note": "moved 2025"},
    ],
    "Florida International University: Now at UNM": [
        {"name": "Florida International University", "status": "former", "note": ""},
        {"name": "University of New Mexico", "status": "current", "note": ""},
    ],
    "Florida International University | OSU": [
        {"name": "Florida International University", "status": "former", "note": ""},
        {"name": "The Ohio State University", "status": "current", "note": ""},
    ],
    "Florida International University; multiple institutiosn": [
        {"name": "Florida International University", "status": "current", "note": ""},
    ],
    "St. Olaf College (previously Carleton College, NSF)": [
        {"name": "St. Olaf College", "status": "current", "note": ""},
        {"name": "Carleton College", "status": "former", "note": ""},
    ],
    "San Diego State University + UC San Diego": [
        {"name": "San Diego State University", "status": "current", "note": "joint program"},
        {"name": "University of California, San Diego", "status": "current", "note": "joint program"},
    ],
    "Cornell University, FIU, Olin, MIT": [
        {"name": "Cornell University", "status": "unknown", "note": ""},
        {"name": "Florida International University", "status": "unknown", "note": ""},
        {"name": "Olin College of Engineering", "status": "unknown", "note": ""},
        {"name": "Massachusetts Institute of Technology", "status": "unknown", "note": ""},
    ],
    "Rice University, MIT": [
        {"name": "Rice University", "status": "unknown", "note": ""},
        {"name": "Massachusetts Institute of Technology", "status": "unknown", "note": ""},
    ],
    "Stanford University; PhET (CU Boulder)": [
        {"name": "Stanford University", "status": "unknown", "note": ""},
        {"name": "University of Colorado Boulder", "status": "unknown", "note": "PhET"},
    ],
    "UK Open University / Heriot-Watt": [
        {"name": "The Open University", "status": "unknown", "note": ""},
        {"name": "Heriot-Watt University", "status": "unknown", "note": ""},
    ],
    "University of Minnesota/Purdue": [
        {"name": "University of Minnesota", "status": "unknown", "note": ""},
        {"name": "Purdue University", "status": "unknown", "note": ""},
    ],
    "University of San Francisco / University of Washington": [
        {"name": "University of San Francisco", "status": "unknown", "note": ""},
        {"name": "University of Washington", "status": "unknown", "note": ""},
    ],
    "Lamont-Doherty Earth Observatory, Columbia University": [
        {"name": "Columbia University", "status": "current", "note": ""},
    ],
}


def canonicalize_institution_name(name: str) -> str:
    name = name.strip()
    return CANONICAL_INSTITUTION_NAMES.get(name.lower(), name)


def normalize_institutions(raw_list: list[str]) -> list[dict[str, str]]:
    """Turn a scholar's raw (already `||`-split) Institution pieces into a structured,
    deduplicated history: [{name, status: current/former/unknown, note}, ...].

    A source-CSV encoding bug (a Windows-1252 en dash miskeyed as \\x96) is fixed
    inline so e.g. both spellings of "University of Nebraska-Lincoln" merge into one.
    """
    resolved: list[dict[str, str | None]] = []
    for raw in raw_list:
        raw = raw.replace("\x96", "-").strip()
        if not raw:
            continue
        override = INSTITUTION_STRING_OVERRIDES.get(raw)
        if override is not None:
            resolved.extend(dict(entry) for entry in override)
            continue
        # Status is undetermined here — a plain raw piece with no annotation. It's
        # resolved below based on how many institutions this scholar ends up with:
        # "current" for the one-institution case, "unknown" when there's more than
        # one and nothing else pins down the order (e.g. the CSV's `||`-joined pieces
        # already represent a multi-institution history with no stated sequence).
        resolved.append({"name": canonicalize_institution_name(raw), "status": None, "note": ""})

    default_status = "current" if len(resolved) == 1 else "unknown"
    for entry in resolved:
        if entry["status"] is None:
            entry["status"] = default_status

    # A "(moved YYYY)" annotation on one entry implies any other undetermined entry
    # in the same list is where the person moved *from* — e.g. ["Western Michigan
    # University", "North Carolina State University (moved 2025)"].
    moved = [e for e in resolved if e["note"].startswith("moved ")]
    if len(moved) == 1:
        moved_name = moved[0]["name"]
        for entry in resolved:
            if entry["name"] != moved_name and entry["status"] == default_status and not entry["note"]:
                entry["status"] = "former"

    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in resolved:
        key = entry["name"].lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


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

        institutions = normalize_institutions(split_pipe(row.get("Institution", "")))
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
            "phd_year": year,
            "phd_era": era,
            "dissertation_title": row.get("Dissertation_Title", "").strip(),
            "position_or_advisor_note": row.get("Current_Position", "").strip(),
            "notes": row.get("Notes", "").strip(),
            "completeness": completeness_score(row),
        }
        scholars.append(scholar)

        for inst in institutions:
            group_members["institution"][inst["name"]].append(person_id)
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
