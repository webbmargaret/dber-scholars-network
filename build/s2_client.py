"""Minimal Semantic Scholar Graph API client for the coauthor re-verification
pass. Reads the API key from build/.s2_api_key (gitignored, never committed)
or the S2_API_KEY env var — never logs or echoes the key itself.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

API_URL = "https://api.semanticscholar.org/graph/v1/author/batch"
DEFAULT_FIELDS = "name,affiliations,paperCount,hIndex,papers.title,papers.venue,papers.year"

DEFAULT_KEY_FILE = Path(__file__).resolve().parent / ".s2_api_key"


def load_api_key(key_file: Path = DEFAULT_KEY_FILE) -> str:
    import os

    env_key = os.environ.get("S2_API_KEY")
    if env_key:
        return env_key.strip()
    if key_file.exists():
        key = key_file.read_text().strip()
        if key:
            return key
    raise SystemExit(
        f"No Semantic Scholar API key found. Set S2_API_KEY or create {key_file}."
    )


class S2Client:
    def __init__(
        self,
        api_key: str,
        rate_limit_seconds: float = 1.0,
        max_retries: int = 6,
        fields: str = DEFAULT_FIELDS,
    ):
        self.api_key = api_key
        self.rate_limit_seconds = rate_limit_seconds
        self.max_retries = max_retries
        self.fields = fields
        self._last_call = 0.0

    def _throttle(self):
        elapsed = time.time() - self._last_call
        wait = self.rate_limit_seconds - elapsed
        if wait > 0:
            time.sleep(wait)

    def fetch_authors_batch(self, author_ids: list[str]) -> dict[str, dict | None]:
        """Returns {author_id: {name, affiliations, paperCount, hIndex, papers: [...]}} ;
        value is None if S2 has no record for that id."""
        if not author_ids:
            return {}

        url = f"{API_URL}?fields={self.fields}"
        body = json.dumps({"ids": author_ids}).encode()

        for attempt in range(self.max_retries):
            self._throttle()
            req = urllib.request.Request(
                url,
                data=body,
                method="POST",
                headers={"Content-Type": "application/json", "x-api-key": self.api_key},
            )
            self._last_call = time.time()
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    results = json.loads(resp.read())
                    return dict(zip(author_ids, results))
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < self.max_retries - 1:
                    wait = min(60, 2**attempt)
                    time.sleep(wait)
                    continue
                raise

        raise RuntimeError(f"Exhausted retries fetching batch of {len(author_ids)} authors")
