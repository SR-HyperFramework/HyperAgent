# HyperAgent Report Web UI

A small read-only Flask app for browsing finished HyperAgent runs.

Its **only** data source is the summary stage artifact:

```text
reports/<sha256>/09-summary.json
```

No other stage file is read, no sample binary is opened, and nothing under
`reports/` is ever written. The rest of the pipeline is untouched by this app.

## Install

```bash
python -m venv .venv
```

```bash
.venv\Scripts\python.exe -m pip install -r webui\requirements.txt
```

## Run

```bash
.venv\Scripts\python.exe webui\app.py
```

Then open <http://127.0.0.1:5000>.

Useful flags:

```bash
.venv\Scripts\python.exe webui\app.py --reports-dir H:\Dataset\files\malware\reports --port 5055
```

| Flag | Meaning |
|---|---|
| `--reports-dir` | Reports tree to browse |
| `--host` / `--port` | Bind address and port (default `127.0.0.1:5000`) |
| `--debug` | Flask debug reloader |

The reports tree is resolved in this order: `--reports-dir`, then
`$HYPERAGENT_REPORTS_DIR`, then `<repo>/reports`.

It also runs under the Flask CLI:

```bash
.venv\Scripts\python.exe -m flask --app webui.app run --port 5055
```

## Routes

| Route | Purpose |
|---|---|
| `/` | Report index: scoreboard, results table, verdict/risk/sort filters |
| `/search?q=` | Header search. A known SHA256 jumps straight to its report; anything else filters the index |
| `/runs/<sha256>` | Full report for one run |
| `/api/runs` | JSON index of every discovered run |
| `/api/runs/<sha256>` | That run's `09-summary.json`, verbatim |

## The report page

Layout follows the familiar public-sandbox report format: a file card with a
verdict gauge (the ring is coloured by verdict, the number is Deepdive's
confidence), the sample hash, and identity chips — then tabbed sections.

| Tab | Contents |
|---|---|
| Detection | Plain-language assessment, remaining decision point, and the three finding buckets |
| Details | Basic properties, classification, provenance, upstream stage inputs |
| Indicators | Confirmed IOCs split into network / host / persistence |
| Actions | Recommended actions, highest priority first |
| Limitations | What this run could not establish |

The three finding buckets — confirmed, caveated, and **not supported by
evidence** — stay three visually distinct sections on purpose. The summary stage
separates them so a reader cannot mistake a caveated or rejected claim for a
confirmed one, and the UI preserves that separation rather than merging them.

Tabs are progressive enhancement: the panels render expanded, and JavaScript
collapses them. With JS off the page is one long readable document. Deep links
work (`/runs/<sha256>#indicators`).

## Run discovery

A directory under the reports tree counts as a run when its name is a bare
SHA256 and it contains a summary file at either:

- `<sha256>/09-summary.json`, or
- `<sha256>/reports/<sha256>/09-summary.json`

The second form exists because some recorded runs wrote their artifacts one
level deeper — a stage passed a relative `reports/<sha256>/...` output path that
got joined onto a report dir already ending in `reports/<sha256>`. The viewer
reads those runs where they actually are; it does not try to repair them.

A run whose summary is missing keys, or is not valid JSON, still lists and still
opens — it renders as `unknown` with the parse error shown, instead of taking
the page down.

## Safety notes

- Report text comes from analyzed malware. Every template value is
  Jinja-autoescaped and nothing is rendered with `|safe`.
- Only bare SHA256 values resolve to a directory, so a crafted URL cannot walk
  out of the reports tree.
- Bind stays on `127.0.0.1` unless you pass `--host`. This is Flask's
  development server; put it behind a real WSGI server before exposing it.
