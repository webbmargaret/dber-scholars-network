# DBER Scholars Network

A static, interactive site mapping people connected to discipline-based education
research (DBER). See [about.html](about.html) (or the deployed `/about.html`) for the
visitor-facing explanation of the dataset and its limitations.

## Structure

- `index.html` — the network view (force-directed graph, hub-and-spoke by
  Institution / Program / DBER Field / PhD Era)
- `about.html` — how the dataset and site were built
- `contribute.html` — add-yourself / request-a-correction form (builds a `mailto:` link)
- `data/` — generated JSON (`scholars.json`, `groups.json`, `build_meta.json`);
  **committed, not built by GitHub Pages**
- `build/build_data.py` — regenerates everything in `data/` from the source CSV

## Rebuilding the data

The source CSV lives outside this repo (it still has an Email column that must never
be committed here). Rerun the pipeline whenever the CSV is updated:

```
python3 build/build_data.py /path/to/1000_DBER_scholars_merged.csv
```

This overwrites `data/scholars.json`, `data/groups.json`, and `data/build_meta.json`.
Commit the results.

## Running locally

No build step for the site itself — it's static HTML/CSS/JS. Serve it with any static
file server, e.g.:

```
python3 -m http.server 8000
```

then open `http://localhost:8000`.

## Privacy

The `Email` column from the source CSV is deliberately excluded from every file in this
repo — `build_data.py` never reads it into any output. Do not add it back without
explicit consent from the people involved.
