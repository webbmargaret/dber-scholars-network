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

from dber_taxonomy import FIELD_TAXONOMY

csv.field_size_limit(10_000_000)  # publications_json can exceed the 128KB default

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

# Matches the exact reasoning suffix a now-retired Semantic Scholar re-verification
# pass appended to Notes (e.g. '... || [coauthor re-verify, 2026-08-08] Re-verified
# via Semantic Scholar API on 2026-08-08: name matches (S2: "..."). Status: confirmed.').
# This site is Google Scholar/SerpAPI only now — strip any leftover S2 reasoning text
# regardless of whether the row's scholar_data_source happens to mention it, since the
# two aren't reliably correlated (some google_scholar-sourced rows still carry stale S2
# text from an earlier identity match; some semantic_scholar-sourced rows carry none).
S2_REASONING_RE = re.compile(r"\s*\|\|\s*\[coauthor re-verify.*$", re.DOTALL)


def scrub_emails(value: str) -> str:
    """Safety net: the source CSV has email addresses miskeyed into non-Email columns
    for a handful of rows (e.g. Position_Title holding a bare email address with the
    row's actual Email cell left blank). Strip any email-shaped substring from every
    display field, not just the dedicated Email column, since dropping only the Email
    column isn't sufficient to keep emails out of the published site."""
    if not value:
        return value
    return EMAIL_RE.sub("", value).strip()


def strip_s2_reasoning(value: str) -> str:
    """Remove a leftover Semantic Scholar re-verification suffix from Notes, if present.
    Always leaves the legitimate coauthor-mining evidence text before it intact."""
    if not value:
        return value
    return S2_REASONING_RE.sub("", value).strip()


MATCH_SCORE_RE = re.compile(r"inst=([\d.-]+).*?field=([\d.-]+)")


def is_weak_scholar_match(match_notes: str) -> bool:
    """A Google Scholar identity match where neither the institution nor the research
    field lined up at all (inst=0.00, field=0.00 in the source pipeline's own scoring)
    is frequently just a same-name coincidence, not the right person — confirmed by
    spot-checking real examples the site's owner flagged as wrong (e.g. matched to an
    unrelated person at a different institution in a different field entirely). This
    pattern covers ~1,100 of 3,470 Google-Scholar-sourced rows and, notably, doesn't
    occur in ANY row the source pipeline itself scored "high" confidence — so it's a
    reliable additional filter on top of match_confidence, not a replacement for it."""
    m = MATCH_SCORE_RE.search(match_notes or "")
    if not m:
        return False
    inst, field = float(m.group(1)), float(m.group(2))
    return inst == 0.0 and field == 0.0


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
    "Virginia Tech (PhD)": [
        {"name": "Virginia Tech", "status": "PhD", "note": ""},
    ],
    "Cornell University (current)": [
        {"name": "Cornell University", "status": "current", "note": ""},
    ],
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
    "Vanderbilt University (previously Virginia Tech, PhD)": [
        {"name": "Vanderbilt University", "status": "current", "note": ""},
        {"name": "Virginia Tech", "status": "former", "note": "PhD"},
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


# Raw `Program` strings that unambiguously mean one program regardless of which
# institution the scholar has, mapped to a canonical spelling. Most of the source
# data's ~80 distinct Program strings are really the same handful of programs
# written inconsistently: with vs. without the program's acronym, acronym-only vs.
# full name, or a sub-department annotation tacked onto an otherwise-repeated name
# (e.g. Toronto's "ISTEP / EngSci", Curtin's "SMEC-affiliated"). Hand-curated
# against every Program value actually present in the source CSV — see
# PROGRAM_INSTITUTION_OVERRIDES below for the handful of raw strings that are
# reused, as the *same spelling*, by multiple institutions to mean genuinely
# different programs.
CANONICAL_PROGRAM_NAMES: dict[str, str] = {
    "School of Engineering Education (ENE)": "School of Engineering Education (ENE)",
    "School of Engineering Education": "School of Engineering Education (ENE)",
    "Department of Engineering & Science Education (ESED)": "Department of Engineering & Science Education (ESED)",
    "Department of Engineering & Science Education": "Department of Engineering & Science Education (ESED)",
    "Mallinson Institute for Science Education": "Mallinson Institute for Science Education",
    "Mathematics and Science Education (MSED)": "Mathematics and Science Education (MSED)",
    "Center for Mathematics Education (CfME)": "Center for Mathematics Education (CfME)",
    "School of Education Mathematics Education PhD": "School of Education Mathematics Education PhD",
    "Department of Engineering Education (ENED)": "Department of Engineering Education (ENED)",
    "Department of Engineering Education (ENGE)": "Department of Engineering Education (ENGE)",
    "ISTEP": "Institute for Studies in Transdisciplinary Engineering Education & Practice (ISTEP)",
    "ISTEP-affiliated": "Institute for Studies in Transdisciplinary Engineering Education & Practice (ISTEP)",
    "Institute for Studies in Transdisciplinary Engineering Education & Practice (ISTEP)": "Institute for Studies in Transdisciplinary Engineering Education & Practice (ISTEP)",
    "ISTEP / EngSci": "Institute for Studies in Transdisciplinary Engineering Education & Practice (ISTEP)",
    "ISTEP / Engineering Communication Program": "Institute for Studies in Transdisciplinary Engineering Education & Practice (ISTEP)",
    "ISTEP / Civil & Mineral Engineering": "Institute for Studies in Transdisciplinary Engineering Education & Practice (ISTEP)",
    "ISTEP / Mechanical & Industrial Engineering": "Institute for Studies in Transdisciplinary Engineering Education & Practice (ISTEP)",
    "ISTEP / Collaborative Specialization in Engineering Education (EngEd, w/ OISE)": "Institute for Studies in Transdisciplinary Engineering Education & Practice (ISTEP)",
    "ISTEP (predecessor units)": "Institute for Studies in Transdisciplinary Engineering Education & Practice (ISTEP)",
    "Department of Engineering Education (EED)": "Department of Engineering Education (EED)",
    "Cornell Discipline-Based Education Research (CDER)": "Cornell Discipline-Based Education Research (CDER)",
    "Mathematics and Science Education (MSE)": "Mathematics and Science Education (MSE)",
    "Mathematics and Science Education PhD": "Mathematics and Science Education (MSE)",
    "Mathematics and Science Education, Biology Ed concentration (PhD)": "Mathematics and Science Education (MSE)",
    "Engineering Education (Engineering Pathways)": "Engineering Education (Engineering Pathways)",
    "School of Aerospace and Mechanical Engineering": "Engineering Education (Engineering Pathways)",
    "Science/Mathematics Education (SMED)": "Science/Mathematics Education (SMED)",
    "Engineering Education (PhD)": "Department of Engineering Education",
    "SMEC": "Science and Mathematics Education Centre (SMEC)",
    "MSET-Ed / REDI": "Mathematics, Science, Environment and Technology Education Research group (MSET-Ed) / Centre for Research for Educational Impact (REDI)",
    "Department of Engineering and Computing Education": "Department of Engineering and Computing Education",
    "Center for Engineering Learning & Teaching (CELT)": "Center for Engineering Learning & Teaching (CELT)",
    "Center for Engineering Learning & Teaching (CELT), UW (PhD)": "Center for Engineering Learning & Teaching (CELT)",
    "Engineering Education Research (PhD)": "Engineering Education Research",
    "Engineering Education Transformations Institute (EETI)": "Engineering Education Transformations Institute (EETI)",
    "CCSE": "Centre for Computing in Science Education (CCSE)",
    "PhD in Physics: Physics Education": "PhD in Physics: Physics Education",
    "Engineering and Computing Education (PhD)": "Department of Engineering and Computing Education",
    "Department of Engineering Education (GSEE)": "Department of Engineering Education (GSEE)",
    "UCPBL": "UCPBL",
    "UCPBL-affiliated": "UCPBL",
    "CLS, Engineering Education Research division": "Communication and Learning in Science (CLS), Engineering Education Research division",
    "Communication and Learning in Science (CLS), Engineering Education Research division": "Communication and Learning in Science (CLS), Engineering Education Research division",
    "Discipline-Based Education Research (DBER)": "Discipline-Based Education Research (DBER)",
    "PhD in Engineering Education": "PhD in Engineering Education",
    "Engineering Education concentration": "Engineering Education concentration",
    "SEED": "Center for Science and Engineering Education Development (SEED)",
    "Engineering, Engineering Education & Transformative Practice (PhD)": "Engineering Education Transformations Institute (EETI)",
    "Experiential Engineering Education (ExEEd)": "Experiential Engineering Education (ExEEd)",
    "Engineering (EER specialization, uncertain)": "Discipline-Based Education Research (DBER)",
    "Smith Engineering, Teaching and Learning": "Smith Engineering",
    "Smith Engineering, Integrated Learning Program": "Smith Engineering",
    "Department of Health Science and Technology": "Department of Health Science and Technology",
    "Department of Learning in Engineering Sciences": "Department of Learning",
    "Department of Learning, Learning in Technology and Science Education group": "Department of Learning",
    "Department of Learning, Digital Learning division": "Department of Learning",
    "Uppsala Computing Education Research Group (UpCERG), Dept. of Information Technology": "Uppsala Computing Education Research Group (UpCERG), Dept. of Information Technology",
    "UpCERG, Dept. of Information Technology": "Uppsala Computing Education Research Group (UpCERG), Dept. of Information Technology",
    "Centre for Computing in Science Education (CCSE)": "Centre for Computing in Science Education (CCSE)",
    "Center for Science and Engineering Education Development (SEED)": "Center for Science and Engineering Education Development (SEED)",
    "SEED / Department of Physics": "Center for Science and Engineering Education Development (SEED)",
    "SEED-affiliated / Dept. of Computer Science": "Center for Science and Engineering Education Development (SEED)",
    "Engineering Education Research group": "Engineering Education Research group",
    "Engineering Education Research group, School of Engineering": "Engineering Education Research group",
    "Sydney University Physics Education Research (SUPER) Group": "Sydney University Physics Education Research (SUPER) Group",
    "SUPER Group": "Sydney University Physics Education Research (SUPER) Group",
    "FEIT Teaching and Learning Laboratory": "FEIT Teaching and Learning Laboratory",
    "Science and Mathematics Education Centre (SMEC)": "Science and Mathematics Education Centre (SMEC)",
    "SMEC / STEM Education Research Group": "Science and Mathematics Education Centre (SMEC)",
    "SMEC-affiliated": "Science and Mathematics Education Centre (SMEC)",
    "STEM Education Research Group": "Science and Mathematics Education Centre (SMEC)",
    "Mathematics, Science, Environment and Technology Education Research group (MSET-Ed) / Centre for Research for Educational Impact (REDI)": "Mathematics, Science, Environment and Technology Education Research group (MSET-Ed) / Centre for Research for Educational Impact (REDI)",
    "Mathematics Education (PhD, Math & Statistics)": "Mathematics Education (PhD, Math & Statistics)",
    "Engineering Education Research": "Engineering Education Research",
    "Engineering Education Systems and Design (EESD)": "Engineering Education Systems and Design (EESD)",
    "Mathematics Education PhD/EdD": "Mathematics Education PhD/EdD",
}

# Raw `Program` strings that are reused, as the *same spelling*, by multiple
# institutions to mean genuinely different programs — resolving these needs the
# scholar's institution, not just the string. Keyed by the raw string, then by
# lowercased institution name. An institution not listed here for a given raw
# string means: no fuller/acronym form is attested for it in the source data, so
# the raw string is left as its own canonical form.
PROGRAM_INSTITUTION_OVERRIDES: dict[str, dict[str, str]] = {
    "Department of Engineering Education": {
        "virginia tech": "Department of Engineering Education (ENGE)",
        "the ohio state university": "Department of Engineering Education (EED)",
        "utah state university": "Department of Engineering Education (ENED)",
        "university of manitoba": "Department of Engineering Education (GSEE)",
        "rowan university": "Experiential Engineering Education (ExEEd)",
    },
    "Mathematics Education PhD": {
        "university of delaware": "School of Education Mathematics Education PhD",
        "georgia state university": "Mathematics Education (PhD, Math & Statistics)",
    },
    "Engineering Education": {
        "university of manitoba": "Department of Engineering Education (GSEE)",
    },
}


def normalize_programs(raw_list: list[str], institutions: list[dict[str, str]]) -> list[str]:
    """Canonicalize each Program piece, then dedupe (preserving order) — a few
    rows list both the bare and acronym form of the same program as if they were
    two, once the acronym is added back they'd otherwise show up twice."""
    inst_names = {inst["name"].lower() for inst in institutions}
    out = []
    for raw in raw_list:
        override = PROGRAM_INSTITUTION_OVERRIDES.get(raw)
        if override:
            for iname in inst_names:
                if iname in override:
                    out.append(override[iname])
                    break
            else:
                out.append(raw)
        else:
            out.append(CANONICAL_PROGRAM_NAMES.get(raw, raw))

    deduped, seen = [], set()
    for p in out:
        if p not in seen:
            seen.add(p)
            deduped.append(p)
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


def parse_dber_field_inferred(fields_str: str, confidence_str: str, evidence_str: str) -> list[dict]:
    """Parses the three `||`-aligned DBER_Field_inferred* columns produced by
    build/infer_dber_field.py into structured chips. Deliberately doesn't reuse
    split_dber_field — that dedupes/reorders, which would break positional
    alignment between a field code and its confidence/evidence."""
    codes = split_pipe(fields_str)
    confidences = split_pipe(confidence_str)
    evidences = split_pipe(evidence_str)
    out = []
    seen = set()
    for i, code in enumerate(codes):
        if code in seen:
            continue
        seen.add(code)
        spec = FIELD_TAXONOMY.get(code)
        out.append({
            "code": code,
            "label": spec["label"] if spec else code,
            "confidence": confidences[i] if i < len(confidences) else "",
            "evidence": evidences[i] if i < len(evidences) else "",
        })
    return out


def coerce_phd_year(value: str) -> int | None:
    """Handles float-string artifacts like "2007.0"."""
    if not value or not value.strip():
        return None
    try:
        return int(float(value.strip().split("||")[0].split(";")[0]))
    except ValueError:
        return None


def coerce_int(value: str) -> int | None:
    """Handles float-string artifacts like "42.0" in the scholar_* enrichment columns."""
    if not value or not value.strip():
        return None
    try:
        return int(float(value.strip()))
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
    dber_field_inferred_people = 0
    dber_field_inferred_distinct = set()
    n_citations_known = 0
    match_confidence_counts: defaultdict[str, int] = defaultdict(int)

    for idx, row in enumerate(rows):
        name = row.get("Name", "").strip()
        if not name:
            continue

        # Scrub email-shaped substrings out of every field before anything else reads
        # from `row` — the source CSV has a few rows with an email miskeyed into a
        # non-Email column (e.g. Position_Title) rather than the Email column itself.
        for c in DISPLAY_COLUMNS:
            row[c] = scrub_emails(row.get(c, ""))
        row["Notes"] = strip_s2_reasoning(row.get("Notes", ""))

        for c in DISPLAY_COLUMNS:
            if row.get(c, "").strip():
                fill_counts[c] += 1

        institutions = normalize_institutions(split_pipe(row.get("Institution", "")))
        programs = normalize_programs(split_pipe(row.get("Program", "")), institutions)
        dber_fields = split_dber_field(row.get("DBER_Field", ""))
        # Machine-inferred by build/infer_dber_field.py, not read into DISPLAY_COLUMNS
        # so it never counts toward completeness_score/fill_counts (sourced-data-only
        # metric) — kept as a separate scholar key so the site can render it distinctly
        # from hand-sourced dber_field.
        dber_field_inferred = parse_dber_field_inferred(
            row.get("DBER_Field_inferred", ""),
            row.get("DBER_Field_inferred_confidence", ""),
            row.get("DBER_Field_inferred_evidence", ""),
        )
        year = coerce_phd_year(row.get("PhD_Year", ""))
        era = phd_era(year)

        person_id = f"{idx:04d}-{slugify(name)}"

        scholar = {
            "id": person_id,
            "name": name,
            "institution": institutions,
            "program": programs,
            "dber_field": dber_fields,
            "dber_field_inferred": dber_field_inferred,
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
        # Enrichment data from the Google Scholar/SerpAPI identity-match pass, not
        # hand-sourced — kept separate from completeness_score/fill_counts the same
        # way dber_field_inferred is. This site publishes Google Scholar data only;
        # scholar_data_source is an allowlist check (not a Semantic-Scholar blocklist)
        # so unmatched rows and any future/unrecognized source are excluded too, not
        # just rows explicitly tagged "semantic_scholar". Also excludes weak matches
        # (see is_weak_scholar_match) regardless of source — a same-name coincidence
        # with zero institution/field agreement isn't a verified match either.
        # A hand-verified "manual_correction" is trusted too, but only when its own
        # scholar_id_format confirms the corrected profile is Google Scholar, not
        # Semantic Scholar — a human fixing a bad match doesn't change which service
        # the resulting profile lives on.
        source = row.get("scholar_data_source", "").strip()
        is_google = source == "google_scholar" or (
            source == "manual_correction"
            and row.get("scholar_id_format", "").strip() == "google_scholar"
        )
        if is_google and not is_weak_scholar_match(row.get("match_notes", "")):
            scholar["n_citations"] = coerce_int(row.get("n_citations", ""))
            scholar["h_index"] = coerce_int(row.get("h_index", ""))
            scholar["match_confidence"] = row.get("match_confidence", "").strip() or None
        else:
            scholar["n_citations"] = None
            scholar["h_index"] = None
            scholar["match_confidence"] = None
        scholars.append(scholar)

        if dber_field_inferred:
            dber_field_inferred_people += 1
            dber_field_inferred_distinct.update(d["code"] for d in dber_field_inferred)

        if scholar["n_citations"] is not None:
            n_citations_known += 1
        match_confidence_counts[scholar["match_confidence"] or "none"] += 1

        for inst in institutions:
            group_members["institution"][inst["name"]].append(person_id)
        for prog in programs:
            group_members["program"][prog].append(person_id)
        # Inferred DBER fields feed into the same hub-clustering as sourced ones (an
        # inferred "EER" merges into the sourced "EER" hub, since both key on the same
        # code/label) — the network graph doesn't distinguish sourced vs. inferred
        # membership; only the detail-panel chip does, via dber_field_inferred above.
        all_dber_labels = list(dict.fromkeys(dber_fields + [d["code"] for d in dber_field_inferred]))
        for field in all_dber_labels:
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
        "dber_field_inferred_people": dber_field_inferred_people,
        "dber_field_inferred_distinct_tags": len(dber_field_inferred_distinct),
        "n_citations_known": n_citations_known,
        "match_confidence_counts": dict(match_confidence_counts),
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
