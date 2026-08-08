"""Shared DBER-field keyword/venue taxonomy, used by both the coauthor
re-verification pass (to score DBER-relevance of a fetched author's papers)
and the DBER_Field inference pass (to guess a field tag from text already in
the CSV). One taxonomy, two consumers, so "DBER-relevant" means the same
thing in both places.

Codes match the short labels already dominant in data/groups.json (EER, PER,
BER, CER, GER, MER, CS Ed) rather than inventing a new vocabulary.
"""
from __future__ import annotations

import re

FIELD_TAXONOMY: dict[str, dict] = {
    "EER": {
        "label": "Engineering Education Research (EER)",
        "venue_patterns": [
            r"journal of engineering education",
            r"asee annual conference",
            r"\bijee\b",
            r"advances in engineering education",
            r"studies in engineering education",
            r"international journal of engineering education",
        ],
        "keyword_patterns": [
            r"engineering education",
            r"engineering identity",
            r"first-year engineering",
        ],
    },
    "PER": {
        "label": "Physics Education Research (PER)",
        "venue_patterns": [
            r"physical review physics education research",
            r"\bprper\b",
            r"physics education research conference",
            r"\bperc\b proceedings",
            r"the physics teacher",
            r"american journal of physics",
        ],
        "keyword_patterns": [
            r"physics education",
            r"introductory physics",
        ],
    },
    "BER": {
        "label": "Biology Education Research (BER)",
        "venue_patterns": [
            r"cbe.{0,3}life sciences education",
            r"\bcbe-lse\b",
            r"journal of microbiology .{0,4}biology education",
        ],
        "keyword_patterns": [
            r"biology education",
            r"undergraduate biology",
        ],
    },
    "CER": {
        "label": "Chemistry Education Research (CER)",
        "venue_patterns": [
            r"journal of chemical education",
            r"chemistry education research and practice",
        ],
        "keyword_patterns": [
            r"chemistry education",
        ],
    },
    "GER": {
        "label": "Geoscience Education Research (GER)",
        "venue_patterns": [
            r"journal of geoscience education",
        ],
        "keyword_patterns": [
            r"geoscience education",
            r"earth science education",
        ],
    },
    "MER": {
        "label": "Mathematics Education Research (MER/RUME)",
        "venue_patterns": [
            r"journal for research in mathematics education",
            r"international journal of research in undergraduate mathematics education",
            r"\bprimus\b",
            r"educational studies in mathematics",
        ],
        "keyword_patterns": [
            r"mathematics education",
            r"undergraduate mathematics education",
        ],
    },
    "CS Ed": {
        "label": "Computing Education Research (CS Ed)",
        "venue_patterns": [
            r"\bsigcse\b",
            r"\bicer\b",
            r"computer science education",
            r"transactions on computing education",
            r"koli calling",
        ],
        "keyword_patterns": [
            r"computing education",
            r"computer science education",
        ],
    },
}

_COMPILED = {
    code: {
        "venue_re": [re.compile(p, re.IGNORECASE) for p in spec["venue_patterns"]],
        "keyword_re": [re.compile(p, re.IGNORECASE) for p in spec["keyword_patterns"]],
    }
    for code, spec in FIELD_TAXONOMY.items()
}

VENUE_WEIGHT = 3
KEYWORD_WEIGHT = 1


def score_fields(
    interests: str,
    dissertation: str,
    publications: list[dict],
    evidence_venues: list[str] | None = None,
    evidence_titles: list[str] | None = None,
    min_score: int = 2,
) -> dict[str, dict]:
    """Score each taxonomy field against a person's text signals.

    `publications` is a list of {"title": ..., "journal": ...} dicts (the
    shape already used by the CSV's `publications_json` column) — but for
    prolific authors this tends to be their top-*cited* papers, which often
    have an empty `journal` and aren't necessarily their DBER-relevant work.
    `evidence_venues`/`evidence_titles` — the CSV's
    `coauthor_dber_evidence_venues`/`_titles` columns, already curated
    specifically as DBER-relevance evidence for coauthor-mined candidates —
    are folded in as additional, often stronger, venue/title signal when
    present. Venue hits are weighted higher than keyword hits since a venue
    match is much stronger evidence than a phrase appearing in free text.

    Returns {code: {"score": int, "tier": "high"|"medium", "matched": [...]}}
    for every field meeting `min_score`, `matched` being the literal
    substrings that triggered the match (for an evidence trail).
    """
    keyword_haystack = " ".join([interests or "", dissertation or ""])
    keyword_haystack += " " + " ".join(p.get("title", "") or "" for p in publications)
    keyword_haystack += " " + " ".join(evidence_titles or [])
    venue_haystack_parts = [p.get("journal", "") or "" for p in publications]
    venue_haystack_parts += list(evidence_venues or [])

    results: dict[str, dict] = {}
    for code, compiled in _COMPILED.items():
        score = 0
        matched: list[str] = []
        has_venue_hit = False

        for pattern, venue_text in _iter_venue_matches(compiled["venue_re"], venue_haystack_parts):
            score += VENUE_WEIGHT
            has_venue_hit = True
            matched.append(f"venue:{venue_text}")

        for regex in compiled["keyword_re"]:
            m = regex.search(keyword_haystack)
            if m:
                score += KEYWORD_WEIGHT
                matched.append(f"keyword:{m.group(0)}")

        if score >= min_score:
            results[code] = {
                "score": score,
                "tier": "high" if has_venue_hit else "medium",
                "matched": matched,
            }

    return results


def _iter_venue_matches(venue_regexes, venue_texts):
    seen = set()
    for regex in venue_regexes:
        for text in venue_texts:
            if not text or text in seen:
                continue
            if regex.search(text):
                seen.add(text)
                yield regex.pattern, text
