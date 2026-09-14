#!/usr/bin/env python3
"""
Build data/collaboration_edges.json from the coauthor_source_scholar_names column of
the DBER scholars merged CSV — for each co-author-mined scholar, an edge back to each
named scholar they were mined from. This is a real but partial and unverified
relationship signal (see about.html's "algorithmically surfaced, not hand-vetted"
caveat) — not a confirmed collaboration or advising record.

Must be run after build_data.py, since it matches names against the id assignment in
data/scholars.json rather than re-deriving ids itself.

Usage:
    python3 build/build_collaboration_edges.py /path/to/1000_DBER_scholars_merged.csv
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

csv.field_size_limit(10_000_000)  # same as build_data.py — publications_json etc. can exceed the 128KB default

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"


def name_key(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def build(csv_path: Path):
    scholars = json.loads((DATA_DIR / "scholars.json").read_text())

    # Map normalized name -> id, but only for names unique in the roster — a name
    # shared by two+ people is ambiguous, so it's left unmatched rather than guessed,
    # matching this project's existing "verify individually, don't fuzzy-merge" stance.
    ids_by_name: dict[str, list[str]] = defaultdict(list)
    for s in scholars:
        ids_by_name[name_key(s["name"])].append(s["id"])
    unique_id_by_name = {k: v[0] for k, v in ids_by_name.items() if len(v) == 1}

    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    edges: set[tuple[str, str]] = set()
    rows_with_sources = 0
    unresolved_names: set[str] = set()

    idx = -1
    for row in rows:
        name = row.get("Name", "").strip()
        if not name:
            continue
        idx += 1
        target_key = name_key(name)
        target_id = unique_id_by_name.get(target_key)
        if target_id is None:
            continue  # this scholar itself isn't uniquely resolvable; skip its edges

        sources = row.get("coauthor_source_scholar_names", "").strip()
        if not sources:
            continue
        rows_with_sources += 1

        for source_name in sources.split("||"):
            source_name = source_name.strip()
            if not source_name:
                continue
            source_id = unique_id_by_name.get(name_key(source_name))
            if source_id is None or source_id == target_id:
                unresolved_names.add(source_name)
                continue
            edge = tuple(sorted((source_id, target_id)))
            edges.add(edge)

    edge_list = [{"source": a, "target": b} for a, b in sorted(edges)]
    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / "collaboration_edges.json").write_text(
        json.dumps(edge_list, indent=1, ensure_ascii=False)
    )

    print(f"Wrote {len(edge_list)} collaboration edges to {DATA_DIR / 'collaboration_edges.json'}")
    print(f"  {rows_with_sources} rows had coauthor_source_scholar_names")
    print(f"  {len(unresolved_names)} distinct source names didn't resolve to a unique scholar")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <path-to-DBER_scholars_merged.csv>")
        sys.exit(1)
    build(Path(sys.argv[1]).expanduser())
