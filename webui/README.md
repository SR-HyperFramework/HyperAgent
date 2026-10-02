# HyperAgent Report Web UI

A small read-only Flask app for browsing HyperAgent runs: finished reports, and
runs still in progress.

The report pages read **only** the summary stage artifact:

```text
reports/<sha256>/09-summary.json
```

Besides the reports root, the app lists every run folder recorded in the run
index `~/.hyperagent/runs.json` (`HYPERAGENT_RUN_INDEX` overrides the path).
The pipeline records each run there, and `hyperagent link-reports <folder>`
adds older ones, so reports written next to samples in other trees still show
up. The report page names the folder a run was read from.

The live page (`/live/<sha256>`) follows a run in progress instead, so it reads
`STATE.json` plus the stage artifacts it summarises (findings and evidence from
`02`–`05`, indicators from `05-dynamic.json` and `09-summary.json`, the verdict
from `07-deepdive.json` / `09-summary.json`), plus the run console's transcript
`console.jsonl` when one was saved. No sample binary is opened, and
nothing under `reports/` is ever written. The rest of the pipeline is untouched
by this app.

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
| `/` | Report index: readable run cards plus verdict/risk/sort filters |
| `/search?q=` | Header search. A known SHA256 jumps straight to its report; anything else filters the index |
| `/runs/<sha256>` | Full report for one run |
| `/live/<sha256>` | Live view of a run: stages, IoCs, evidence, and the agent trace (streamed from the CLI, or its saved transcript) |
| `/api/runs` | JSON index of every discovered run |
| `/api/runs/<sha256>` | That run's `09-summary.json`, verbatim |
| `/api/live/<sha256>` | The live view as JSON: stage snapshot plus console state |
| `/console/<sha256>.txt` | The run's saved console transcript as plain text |
| `/api/console/<sha256>` | The saved transcript as JSON records (newest 4 MB of the file) |

## The live page

`hyperagent analyze <sample> --mdebug` serves this app in-process on
`127.0.0.1:5000` (or the next free port; `--dashboard-port` picks another start,
`--no-dashboard` turns it off) and prints a **Watch live in browser** link at the
top of the console sidebar. Served that way, the app gets the run console as a
*live feed*, so `/live/<sha256>` shows the same agent trace the terminal shows,
next to the stage list, IoCs and findings read from the report directory. The
index page links the active run.

The page renders on the server and works without JavaScript (it falls back to
reloading itself). With JavaScript it re-fetches `/live/<sha256>?fragment=1`
every couple of seconds and swaps in only the regions whose markup changed, so
it never builds markup from run data in the browser. The dashboard stops with
the CLI process; the page then says it lost contact and keeps the last update.

The run console also saves what it shows to `reports/<sha256>/console.jsonl`.
Without a live feed -- the CLI has exited, or the app was started standalone
(`python webui\app.py`) -- the live page renders that transcript instead (the
newest 1,000 events, with each console session marked; each burst of tool calls
is one expandable "Read 3 files, ran 1 command" row that stays open across
updates), and a report page links
to it as **Console output**. A standalone app re-reads the file on every poll,
so it also follows a run going on in another process, though it cannot tell such
a run from an abandoned one.

## The report page

The detail view is a top-to-bottom forensic dossier, not a tabbed technical dump.
It opens with the Deepdive verdict, confidence, risk, and one-sentence headline,
then shows the sample identity and a plain-language assessment before any lower
level evidence.

| Section | Contents |
|---|---|
| Summary | Plain-language assessment and the remaining decision point |
| Findings | Confirmed findings, caveated findings, and not-supported claims as separate bands |
| Classification | Conservative malware type, family status, verdict, and risk |
| Indicators | Confirmed IOCs split into network / host / persistence |
| Actions | Recommended actions, highest priority first |
| Limits | What this run could not establish |
| Provenance | Summary path, modified time, stage status, and upstream inputs |

The three finding buckets — confirmed, caveated, and **not supported by
evidence** — stay visually distinct on purpose. The summary stage separates them
so a reader cannot mistake a caveated or rejected claim for a confirmed one, and
the UI preserves that separation rather than merging them.

JavaScript is not required for report readability. It only enhances timestamps,
the theme toggle, and copy-to-clipboard buttons. Deep links still work through
normal anchors such as `/runs/<sha256>#indicators`.

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
  out of the reports tree. The live page also ignores a `STATE.json`
  `output_path` that points outside the run's report directory.
- Bind stays on `127.0.0.1` unless you pass `--host`. This is Flask's
  development server; put it behind a real WSGI server before exposing it.
