from __future__ import annotations


def _dashboard_html(run_id: str | None = None) -> str:
    initial_run_id = run_id or ""
    return f"""<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>HyperAgent Workflow Dashboard</title>
  <link rel=\"icon\" href=\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='18' fill='%230f151b'/%3E%3Cpath d='M18 44 30 18h4l12 26h-6l-2.6-6H26.6L24 44h-6Zm10.7-11h6.6L32 25.6 28.7 33Z' fill='%233fbf7f'/%3E%3C/svg%3E\" />
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0b0d10;
      --panel: #12161b;
      --panel-2: #171c22;
      --panel-3: #1d232b;
      --border: #28303a;
      --border-strong: #364252;
      --text: #f5f7fb;
      --muted: #96a1b2;
      --muted-2: #758095;
      --accent: #3fbf7f;
      --accent-strong: #65d79a;
      --ok-bg: #0c2919;
      --ok-text: #b8f2ca;
      --warn-bg: #2d210b;
      --warn-text: #f7dda1;
      --danger-bg: #341214;
      --danger-text: #ffcbcf;
      --radius: 18px;
      --shadow: 0 24px 60px rgba(4, 10, 20, 0.28);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI Variable", "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
      background:
        radial-gradient(circle at top, rgba(63, 191, 127, 0.1), transparent 30%),
        linear-gradient(180deg, #0d1015 0%, var(--bg) 45%);
      color: var(--text);
      min-height: 100dvh;
    }}
    .shell {{ max-width: 1400px; margin: 0 auto; padding: 28px; }}
    .header {{ display: grid; gap: 14px; margin-bottom: 22px; }}
    .title {{ display: flex; justify-content: space-between; gap: 16px; align-items: end; flex-wrap: wrap; }}
    .title-copy {{ display: grid; gap: 8px; }}
    h1 {{ margin: 0; font-size: clamp(30px, 4vw, 40px); line-height: 0.96; letter-spacing: -0.045em; text-wrap: balance; }}
    .sub {{ color: var(--muted); max-width: 56ch; font-size: 14px; line-height: 1.5; }}
    .toolbar {{ display: grid; gap: 12px; }}
    .controls, .upload-controls {{
      display: grid;
      gap: 10px;
      align-items: center;
      padding: 10px;
      border: 1px solid rgba(255,255,255,0.05);
      background: rgba(18, 22, 27, 0.78);
      border-radius: 18px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }}
    .controls {{ grid-template-columns: minmax(0,1fr) auto; }}
    .upload-controls {{ grid-template-columns: auto minmax(0,1fr) auto auto; }}
    input, button, .button-like {{
      border-radius: 999px;
      border: 1px solid var(--border);
      background: var(--panel);
      color: var(--text);
      padding: 11px 15px;
      font: inherit;
      transition: transform 180ms ease, border-color 180ms ease, background-color 180ms ease, box-shadow 180ms ease, color 180ms ease;
    }}
    input {{ min-width: 0; background: rgba(255,255,255,0.02); }}
    input::placeholder {{ color: var(--muted-2); }}
    button {{
      background: var(--accent);
      color: #062815;
      border: 0;
      font-weight: 600;
      cursor: pointer;
      box-shadow: 0 12px 28px rgba(63, 191, 127, 0.2);
    }}
    button:hover, .button-like:hover, input:hover {{ border-color: var(--border-strong); }}
    button:hover {{ background: var(--accent-strong); transform: translateY(-1px); }}
    button:active, .button-like:active {{ transform: translateY(1px) scale(0.99); }}
    button[disabled] {{ opacity: 0.62; cursor: progress; box-shadow: none; transform: none; }}
    input:focus-visible,
    button:focus-visible,
    .button-like:focus-visible,
    .file-picker:focus-within,
    .toggle:focus-within {{
      outline: none;
      border-color: rgba(101, 215, 154, 0.88);
      box-shadow: 0 0 0 4px rgba(63, 191, 127, 0.18);
    }}
    .button-like {{ display: inline-flex; align-items: center; justify-content: center; cursor: pointer; user-select: none; text-decoration: none; }}
    .secondary-button {{ background: rgba(255,255,255,0.02); color: var(--text); border: 1px solid var(--border); font-weight: 600; }}
    .file-picker {{ position: relative; display: inline-flex; align-items: center; justify-content: center; overflow: hidden; }}
    .file-picker input[type="file"] {{ position: absolute; inset: 0; width: 100%; height: 100%; opacity: 0; cursor: pointer; padding: 0; margin: 0; }}
    .file-name {{ color: var(--muted); font-size: 13px; min-height: 20px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding: 0 4px; }}
    .toggle {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 0 14px;
      border: 1px solid var(--border);
      border-radius: 999px;
      background: rgba(255,255,255,0.02);
      color: var(--muted);
      min-height: 44px;
    }}
    .toggle input {{ width: 16px; height: 16px; margin: 0; padding: 0; accent-color: var(--accent); }}
    .status-text {{ color: var(--muted); font-size: 13px; min-height: 18px; padding: 0 4px; }}
    .status-text.ready {{ color: var(--text); }}
    .status-text.success {{ color: var(--ok-text); }}
    .status-text.failed {{ color: var(--danger-text); }}
    .grid {{ display: grid; grid-template-columns: 300px minmax(0,1fr); gap: 18px; align-items: start; }}
    .stack {{ display: grid; gap: 16px; min-width: 0; }}
    .card {{
      min-width: 0;
      background: linear-gradient(180deg, rgba(22, 27, 33, 0.94), rgba(18, 22, 27, 0.94));
      border: 1px solid rgba(255,255,255,0.06);
      border-radius: var(--radius);
      padding: 18px;
      box-shadow: var(--shadow);
    }}
    .card h2 {{ margin: 0 0 14px; font-size: 13px; line-height: 1.2; letter-spacing: 0.01em; color: var(--muted); font-weight: 600; }}
    .meta {{ display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 12px 14px; }}
    .meta-row {{ display: grid; gap: 5px; min-width: 0; }}
    .meta-row.wide {{ grid-column: 1 / -1; }}
    .label {{ font-size: 11px; color: var(--muted-2); letter-spacing: 0.08em; text-transform: uppercase; }}
    .value {{ font-size: 14px; line-height: 1.4; word-break: break-word; color: var(--text); }}
    .value.mono, .chip.mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-variant-numeric: tabular-nums; }}
    .value.truncate, .chip.path-chip, .artifact-path {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border-radius: 999px;
      padding: 9px 13px;
      width: fit-content;
      font-size: 12px;
      font-weight: 700;
      background: var(--warn-bg);
      color: var(--warn-text);
      text-transform: capitalize;
      box-shadow: inset 0 0 0 1px rgba(255,255,255,0.04);
    }}
    .badge.running, .badge.processing {{ background: #102840; color: #b8dcff; }}
    .badge.completed, .badge.success {{ background: var(--ok-bg); color: var(--ok-text); }}
    .badge.failed, .badge.error {{ background: var(--danger-bg); color: var(--danger-text); }}
    .badge.queued, .badge.pending, .badge.idle {{ background: var(--panel-3); color: var(--muted); }}
    .board {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }}
    .column {{
      display: grid;
      gap: 10px;
      align-content: start;
      background: rgba(255,255,255,0.02);
      border: 1px solid rgba(255,255,255,0.05);
      border-radius: 16px;
      padding: 12px;
      min-height: 260px;
    }}
    .column-head {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; }}
    .column-title {{ font-weight: 600; letter-spacing: -0.01em; }}
    .task-list, .tree {{ display: grid; gap: 10px; align-content: start; }}
    .timeline {{
      display: grid;
      width: 100%;
      max-width: 100%;
      min-width: 0;
      grid-auto-flow: column;
      grid-auto-columns: 168px;
      gap: 8px;
      align-items: start;
      overflow-x: auto;
      overflow-y: hidden;
      padding: 12px 4px 18px;
      scrollbar-gutter: stable;
      scroll-snap-type: x proximity;
      overscroll-behavior-x: contain;
    }}
    .timeline-card #timeline::-webkit-scrollbar {{ height: 10px; }}
    .timeline-card #timeline::-webkit-scrollbar-thumb {{ background: rgba(255,255,255,0.12); border-radius: 999px; }}
    .timeline-card #timeline::-webkit-scrollbar-track {{ background: transparent; }}
    .timeline-tooltip-portal {{
      position: fixed;
      left: 12px;
      top: 12px;
      width: min(260px, calc(100vw - 24px));
      padding: 10px 12px;
      border-radius: 12px;
      border: 1px solid rgba(255,255,255,0.08);
      background: rgba(16, 20, 25, 0.98);
      box-shadow: 0 22px 48px rgba(0,0,0,0.38);
      display: grid;
      gap: 6px;
      pointer-events: none;
      opacity: 0;
      visibility: hidden;
      transition: opacity 120ms ease;
      z-index: 35;
    }}
    .timeline-tooltip-portal.open {{
      opacity: 1;
      visibility: visible;
    }}
    .timeline-tooltip-portal .chip {{ max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .timeline-tooltip-portal .chip.path-chip {{ max-width: 100%; }}
    .timeline > * {{ min-width: 0; }}
    .task-list {{
      max-height: 640px;
      overflow-y: auto;
      padding-right: 4px;
      scrollbar-gutter: stable;
    }}
    .task-card {{
      border: 1px solid rgba(255,255,255,0.05);
      border-radius: 14px;
      padding: 12px;
      background: rgba(255,255,255,0.025);
      display: grid;
      gap: 8px;
      transition: transform 180ms ease, border-color 180ms ease, background-color 180ms ease;
    }}
    .task-card:hover {{
      transform: translateY(-1px);
      border-color: rgba(101, 215, 154, 0.28);
      background: rgba(255,255,255,0.04);
    }}
    .task-top {{ display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; flex-wrap: wrap; }}
    .task-title {{ font-weight: 600; line-height: 1.25; letter-spacing: -0.01em; }}
    .task-id {{ color: var(--muted-2); font-size: 12px; }}
    .task-summary {{ font-size: 13px; line-height: 1.5; color: var(--muted); word-break: break-word; }}
    .timeline-label {{
      font-size: 12px;
      line-height: 1.35;
      color: var(--text);
      text-align: center;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
      min-height: 32px;
    }}
    .timeline-time {{
      font-size: 11px;
      line-height: 1;
      color: var(--muted-2);
      text-align: center;
      font-variant-numeric: tabular-nums;
      letter-spacing: 0.04em;
    }}
    .timeline-tooltip-title {{ font-size: 12px; font-weight: 600; color: var(--text); line-height: 1.35; }}
    .timeline-tooltip-meta {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .timeline-tooltip-msg {{ font-size: 12px; line-height: 1.45; color: var(--muted); word-break: break-word; }}
    .task-summary {{ display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
    .task-meta, .task-foot, .event-meta {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .task-card-body, .task-output-body {{ display: grid; gap: 8px; }}
    .chip {{
      display: inline-flex;
      align-items: center;
      min-width: 0;
      border-radius: 999px;
      padding: 5px 9px;
      border: 1px solid rgba(255,255,255,0.06);
      color: var(--muted);
      font-size: 11px;
      line-height: 1.35;
      background: rgba(255,255,255,0.02);
    }}
    .chip.subtle {{ color: var(--muted-2); background: rgba(255,255,255,0.015); }}
    .terminal-badge {{ display: inline-flex; align-items: center; border-radius: 999px; padding: 4px 8px; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; }}
    .terminal-badge.success {{ background: var(--ok-bg); color: var(--ok-text); }}
    .terminal-badge.failed {{ background: var(--danger-bg); color: var(--danger-text); }}
    .terminal-badge.skipped, .terminal-badge.cancelled {{ background: var(--panel-3); color: #d7deea; }}
    .empty-state {{ border: 1px dashed rgba(255,255,255,0.08); border-radius: 12px; padding: 12px; color: var(--muted); font-size: 13px; background: rgba(255,255,255,0.015); }}
    .timeline-event {{
      position: relative;
      display: grid;
      justify-items: center;
      gap: 8px;
      width: 168px;
      min-width: 168px;
      max-width: 168px;
      scroll-snap-align: start;
      padding-top: 6px;
    }}
    .timeline-rail {{
      position: relative;
      display: flex;
      align-items: center;
      width: 100%;
      min-height: 22px;
      padding: 0 2px;
    }}
    .timeline-rail::before,
    .timeline-rail::after {{
      content: "";
      flex: 1 1 auto;
      height: 2px;
      background: linear-gradient(90deg, rgba(255,255,255,0.03), rgba(255,255,255,0.18));
    }}
    .timeline-event.is-first .timeline-rail::before,
    .timeline-event.is-last .timeline-rail::after {{
      opacity: 0;
    }}
    .timeline-dot {{
      position: relative;
      z-index: 1;
      flex: none;
      width: 11px;
      height: 11px;
      border-radius: 999px;
      border: 2px solid rgba(255,255,255,0.08);
      background: rgba(190, 199, 214, 0.7);
      box-shadow: 0 0 0 5px rgba(190, 199, 214, 0.08);
    }}
    .timeline-started .timeline-dot,
    .timeline-running .timeline-dot,
    .timeline-processing .timeline-dot {{
      background: rgba(126, 191, 255, 0.95);
      box-shadow: 0 0 0 5px rgba(126, 191, 255, 0.14);
    }}
    .timeline-completed .timeline-dot,
    .timeline-success .timeline-dot {{
      background: rgba(101, 215, 154, 0.95);
      box-shadow: 0 0 0 5px rgba(101, 215, 154, 0.14);
    }}
    .timeline-failed .timeline-dot,
    .timeline-error .timeline-dot {{
      background: rgba(255, 110, 124, 0.95);
      box-shadow: 0 0 0 5px rgba(255, 110, 124, 0.14);
    }}
    .tree {{ gap: 8px; }}
    .tree-item {{ display: flex; align-items: center; gap: 8px; min-width: 0; padding-left: 10px; border-left: 1px solid rgba(255,255,255,0.08); }}
    .process-shell {{ display: grid; gap: 10px; }}
    .process-stats {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }}
    .process-stat {{
      padding: 10px 12px;
      border-radius: 14px;
      border: 1px solid rgba(255,255,255,0.05);
      background: rgba(255,255,255,0.02);
      display: grid;
      gap: 4px;
    }}
    .process-stat .value {{ font-size: 18px; line-height: 1; letter-spacing: -0.03em; }}
    .process-list {{ display: grid; gap: 10px; max-height: 420px; overflow-y: auto; padding-right: 4px; scrollbar-gutter: stable; }}
    .process-card {{
      border: 1px solid rgba(255,255,255,0.05);
      border-radius: 14px;
      padding: 12px;
      background: rgba(255,255,255,0.025);
      display: grid;
      gap: 8px;
    }}
    .process-head {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }}
    .process-title {{ font-weight: 600; line-height: 1.3; letter-spacing: -0.01em; }}
    .process-subtitle {{ color: var(--muted-2); font-size: 12px; }}
    .process-meta {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .process-actions {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .process-command {{
      font: 12px/1.6 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      color: #d8dfeb;
      word-break: break-word;
      padding: 10px 12px;
      border-radius: 12px;
      border: 1px solid rgba(255,255,255,0.05);
      background: rgba(255,255,255,0.02);
    }}
    .danger-button {{
      background: rgba(255, 110, 124, 0.12);
      color: var(--danger-text);
      border: 1px solid rgba(255, 110, 124, 0.24);
      box-shadow: none;
    }}
    .danger-button:hover {{
      background: rgba(255, 110, 124, 0.18);
      color: #fff3f4;
    }}
    .artifact-type {{
      flex: none;
      border-radius: 999px;
      padding: 4px 8px;
      font-size: 10px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      background: rgba(63, 191, 127, 0.12);
      color: var(--ok-text);
    }}
    .artifact-path {{ min-width: 0; color: var(--muted); font-size: 13px; }}
    .summary-shell {{ display: grid; gap: 14px; }}
    .task-output-shell {{ display: grid; gap: 12px; }}
    .task-output-header {{ display: grid; gap: 8px; }}
    .task-output-title {{ font-size: 15px; font-weight: 600; letter-spacing: -0.01em; }}
    .task-output-meta {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .task-output-result {{ display: grid; gap: 10px; }}
    .task-output-actions {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .task-action {{
      background: rgba(255,255,255,0.02);
      color: var(--text);
      border: 1px solid var(--border);
      box-shadow: none;
      padding: 8px 12px;
      font-size: 12px;
      font-weight: 600;
    }}
    .task-action:hover {{ background: rgba(255,255,255,0.05); }}
    .task-action.active {{
      background: rgba(63, 191, 127, 0.14);
      border-color: rgba(101, 215, 154, 0.42);
      color: var(--ok-text);
    }}
    .modal-overlay {{
      position: fixed;
      inset: 0;
      display: grid;
      place-items: center;
      padding: 24px;
      background: rgba(7, 10, 14, 0.72);
      backdrop-filter: blur(10px);
      opacity: 0;
      visibility: hidden;
      pointer-events: none;
      transition: opacity 180ms ease, visibility 180ms ease;
      z-index: 40;
    }}
    .modal-overlay.open {{
      opacity: 1;
      visibility: visible;
      pointer-events: auto;
    }}
    .modal-dialog {{
      width: min(860px, calc(100vw - 32px));
      max-height: min(82dvh, 900px);
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      border-radius: 22px;
      border: 1px solid rgba(255,255,255,0.08);
      background: rgba(12, 16, 21, 0.98);
      box-shadow: 0 28px 80px rgba(0,0,0,0.42);
      overflow: hidden;
    }}
    .modal-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 16px 18px;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      background: rgba(255,255,255,0.015);
    }}
    .modal-title {{ font-size: 14px; font-weight: 600; letter-spacing: -0.01em; }}
    .modal-close {{
      width: 34px;
      height: 34px;
      min-width: 34px;
      padding: 0;
      border-radius: 10px;
      font-size: 18px;
      line-height: 1;
    }}
    .modal-body {{
      min-height: 0;
      overflow: auto;
      padding: 18px;
    }}
    .summary-stats {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }}
    .summary-stat {{
      padding: 12px;
      border-radius: 14px;
      border: 1px solid rgba(255,255,255,0.05);
      background: rgba(255,255,255,0.02);
      display: grid;
      gap: 5px;
    }}
    .summary-stat .label {{ font-size: 10px; }}
    .summary-stat .value {{ font-size: 20px; line-height: 1; letter-spacing: -0.04em; }}
    .summary-panels {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }}
    .summary-panel {{
      border: 1px solid rgba(255,255,255,0.05);
      border-radius: 14px;
      padding: 12px;
      background: rgba(255,255,255,0.02);
      display: grid;
      gap: 10px;
      min-width: 0;
    }}
    .summary-panel-title {{ font-size: 12px; font-weight: 600; letter-spacing: -0.01em; }}
    .summary-list {{ margin: 0; padding-left: 18px; display: grid; gap: 8px; color: var(--muted); font-size: 13px; }}
    .summary-list li {{ line-height: 1.45; word-break: break-word; }}
    .summary-empty, .list-more {{ color: var(--muted); font-size: 13px; }}
    .details-block {{ border: 1px solid rgba(255,255,255,0.05); border-radius: 14px; background: rgba(255,255,255,0.015); overflow: hidden; }}
    .details-block summary {{ cursor: pointer; list-style: none; padding: 12px 14px; font-size: 12px; font-weight: 600; color: var(--text); }}
    .details-block summary::-webkit-details-marker {{ display: none; }}
    .details-block[open] summary {{ border-bottom: 1px solid rgba(255,255,255,0.05); }}
    .details-block pre {{ padding: 12px 14px 14px; margin: 0; }}
    pre {{ white-space: pre-wrap; word-break: break-word; margin: 0; font: 12px/1.65 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; color: #d8dfeb; font-variant-numeric: tabular-nums; }}
    @media (max-width: 1180px) {{
      .grid {{ grid-template-columns: 1fr; }}
      .board {{ grid-template-columns: 1fr; }}
      .summary-stats, .summary-panels {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 980px) {{
      .shell {{ padding: 20px; }}
      .controls, .upload-controls {{ grid-template-columns: 1fr; }}
      .summary-stats, .summary-panels, .meta {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class=\"shell\">
    <div class=\"header\">
      <div class=\"title\">
        <div class=\"title-copy\">
          <h1>HyperAgent Workflow Dashboard</h1>
          <div class=\"sub\">Open a run, watch task flow, and scan the result.</div>
        </div>
        <div id=\"statusBadge\" class=\"badge\">Idle</div>
      </div>
      <div class=\"toolbar\">
        <div class=\"controls\">
          <input id=\"runIdInput\" placeholder=\"Enter run_id to inspect\" value=\"{initial_run_id}\" />
          <button id=\"openRunButton\" type=\"button\">Open run</button>
        </div>
        <div class=\"upload-controls\">
          <label id=\"chooseFileButton\" class=\"button-like secondary-button file-picker\">
            <span>Choose file</span>
            <input id=\"uploadFileInput\" type=\"file\" />
          </label>
          <div id=\"selectedFileName\" class=\"file-name\">No file selected.</div>
          <label class=\"toggle\"><input id=\"keepFileInput\" type=\"checkbox\" /> Keep file</label>
          <button id=\"uploadRunButton\" type=\"button\">Upload run</button>
        </div>
        <div id=\"uploadStatus\" class=\"status-text\"></div>
      </div>
    </div>
    <div class=\"grid\">
      <aside class=\"stack\">
        <section class=\"card\">
          <h2>Run</h2>
          <div class=\"meta\" id=\"runMeta\"></div>
        </section>
        <section class=\"card\">
          <h2>Artifacts</h2>
          <div id=\"artifactTree\" class=\"tree\"></div>
        </section>
        <section class=\"card\">
          <h2>Related processes</h2>
          <div id=\"processPanel\" class=\"process-shell\">
            <div class=\"process-actions\"><button type=\"button\" id=\"stopRunButton\" class=\"task-action danger-button\" disabled>Stop run<\/button></div>
            <div class=\"summary-empty\">Open a run to observe related OS processes.</div>
          </div>
        </section>
      </aside>
      <main class=\"stack\">
        <section class=\"card\">
          <h2>Task board</h2>
          <div class=\"board\">
            <div class=\"column\">
              <div class=\"column-head\"><span class=\"column-title\">Pending</span><span id=\"pendingCount\" class=\"chip mono\">0</span></div>
              <div id=\"pendingTasks\" class=\"task-list\"></div>
            </div>
            <div class=\"column\">
              <div class=\"column-head\"><span class=\"column-title\">Processing</span><span id=\"processingCount\" class=\"chip mono\">0</span></div>
              <div id=\"processingTasks\" class=\"task-list\"></div>
            </div>
            <div class=\"column\">
              <div class=\"column-head\"><span class=\"column-title\">Completed</span><span id=\"completedCount\" class=\"chip mono\">0</span></div>
              <div id=\"completedTasks\" class=\"task-list\"></div>
            </div>
          </div>
        </section>
        <section class=\"card timeline-card\">
          <h2>Timeline</h2>
          <div id=\"timeline\" class=\"timeline\"></div>
        </section>
        <section class=\"card\">
          <h2>Summary</h2>
          <div id=\"summary\" class=\"summary-shell\">
            <div class=\"summary-empty\">Open a run to inspect findings, IOCs, verdict, and report output.</div>
          </div>
        </section>
      </main>
    </div>
  </div>
  <div id="taskOutputModal" class="modal-overlay" aria-hidden="true">
    <div class="modal-dialog" role="dialog" aria-modal="true" aria-labelledby="taskOutputModalTitle">
      <div class="modal-header">
        <div id="taskOutputModalTitle" class="modal-title">Task output</div>
        <button id="taskOutputClose" type="button" class="secondary-button modal-close" aria-label="Close task output">×</button>
      </div>
      <div class="modal-body">
        <div id="taskOutput" class="task-output-shell">
          <div class="summary-empty">Select a task to inspect its output.</div>
        </div>
      </div>
    </div>
  </div>
  <div id="timelineTooltipPortal" class="timeline-tooltip-portal" aria-hidden="true">
    <div id="timelineTooltipTitle" class="timeline-tooltip-title"></div>
    <div id="timelineTooltipMeta" class="timeline-tooltip-meta"></div>
    <div id="timelineTooltipMsg" class="timeline-tooltip-msg"></div>
  </div>
  <script>
    const runIdInput = document.getElementById('runIdInput');
    const openRunButton = document.getElementById('openRunButton');
    const uploadFileInput = document.getElementById('uploadFileInput');
    const selectedFileName = document.getElementById('selectedFileName');
    const keepFileInput = document.getElementById('keepFileInput');
    const uploadRunButton = document.getElementById('uploadRunButton');
    const uploadStatus = document.getElementById('uploadStatus');
    const runMeta = document.getElementById('runMeta');
    const pendingTasks = document.getElementById('pendingTasks');
    const processingTasks = document.getElementById('processingTasks');
    const completedTasks = document.getElementById('completedTasks');
    const pendingCount = document.getElementById('pendingCount');
    const processingCount = document.getElementById('processingCount');
    const completedCount = document.getElementById('completedCount');
    const timeline = document.getElementById('timeline');
    const artifactTree = document.getElementById('artifactTree');
    const processPanel = document.getElementById('processPanel');
    const summary = document.getElementById('summary');
    let currentProcessSnapshot = {{ processes: [] }};
    const taskOutput = document.getElementById('taskOutput');
    const taskOutputModal = document.getElementById('taskOutputModal');
    const taskOutputClose = document.getElementById('taskOutputClose');
    const taskOutputModalTitle = document.getElementById('taskOutputModalTitle');
    const timelineTooltipPortal = document.getElementById('timelineTooltipPortal');
    const timelineTooltipTitle = document.getElementById('timelineTooltipTitle');
    const timelineTooltipMeta = document.getElementById('timelineTooltipMeta');
    const timelineTooltipMsg = document.getElementById('timelineTooltipMsg');
    const statusBadge = document.getElementById('statusBadge');
    let currentRunId = runIdInput.value.trim();
    let currentTaskId = null;
    let pollHandle = null;
    let currentTaskMap = new Map();

    function captureScrollState(node) {{
      if (!node) return null;
      return {{ top: node.scrollTop, left: node.scrollLeft }};
    }}

    function restoreScrollState(node, state) {{
      if (!node || !state) return;
      node.scrollTop = state.top || 0;
      node.scrollLeft = state.left || 0;
    }}

    function captureDetailsState(container) {{
      if (!container) return [];
      return Array.from(container.querySelectorAll('details')).map((node) => node.open);
    }}

    function restoreDetailsState(container, detailsState) {{
      if (!container || !Array.isArray(detailsState)) return;
      const details = Array.from(container.querySelectorAll('details'));
      detailsState.forEach((isOpen, index) => {{
        if (details[index]) details[index].open = Boolean(isOpen);
      }});
    }}

    function captureTaskOutputState() {{
      const modalBody = taskOutputModal.querySelector('.modal-body');
      return {{
        scroll: captureScrollState(modalBody),
        details: captureDetailsState(taskOutput),
      }};
    }}

    function restoreTaskOutputState(state) {{
      if (!state) return;
      restoreDetailsState(taskOutput, state.details);
      const modalBody = taskOutputModal.querySelector('.modal-body');
      restoreScrollState(modalBody, state.scroll);
    }}

    function setBadge(status) {{
      const normalized = String(status || 'idle').toLowerCase().replace(/\s+/g, '-');
      statusBadge.textContent = status || 'idle';
      statusBadge.className = 'badge ' + normalized;
    }}

    function escapeHtml(value) {{
      return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }}

    function metaRow(label, value, options = {{}}) {{
      const displayValue = value ?? '-';
      const classes = ['value'];
      if (options.mono) classes.push('mono');
      if (options.truncate) classes.push('truncate');
      return `<div class=\"meta-row${{options.wide ? ' wide' : ''}}\"><div class=\"label\">${{escapeHtml(label)}}</div><div class=\"${{classes.join(' ')}}\" title=\"${{escapeHtml(displayValue)}}\">${{escapeHtml(displayValue)}}<\/div><\/div>`;
    }}

    function chip(text, options = {{}}) {{
      const classes = ['chip'];
      if (options.subtle) classes.push('subtle');
      if (options.mono) classes.push('mono');
      if (options.path) classes.push('path-chip');
      return `<span class=\"${{classes.join(' ')}}\" title=\"${{escapeHtml(text)}}\">${{escapeHtml(text)}}<\/span>`;
    }}

    function formatCount(value) {{
      if (Array.isArray(value)) return String(value.length);
      if (typeof value === 'number') return String(value);
      return '0';
    }}

    function renderList(items, emptyText) {{
      if (!items || !items.length) return `<div class=\"summary-empty\">${{escapeHtml(emptyText)}}<\/div>`;
      const visible = items.slice(0, 4);
      const rows = visible.map((item) => `<li>${{escapeHtml(typeof item === 'string' ? item : JSON.stringify(item))}}<\/li>`).join('');
      const more = items.length > visible.length ? `<div class=\"list-more\">+${{items.length - visible.length}} more<\/div>` : '';
      return `<ol class=\"summary-list\">${{rows}}<\/ol>${{more}}`;
    }}

    function renderMeta(snapshot) {{
      const result = snapshot.result || {{}};
      runMeta.innerHTML = [
        metaRow('Run ID', snapshot.run_id, {{ mono: true, truncate: true }}),
        metaRow('Detected type', result.detected_type || snapshot.status),
        metaRow('Started', snapshot.started_at, {{ mono: true }}),
        metaRow('Finished', snapshot.finished_at, {{ mono: true }}),
        metaRow('File path', result.file_path || snapshot.file_name, {{ wide: true, mono: true, truncate: true }}),
        snapshot.error ? metaRow('Error', snapshot.error, {{ wide: true }}) : ''
      ].join('');
    }}

    function formatTimelineTime(timestamp) {{
      if (!timestamp) return '--:--';
      const match = String(timestamp).match(/T(\d{2}:\d{2})/);
      if (match) return match[1];
      const date = new Date(timestamp);
      if (!Number.isNaN(date.getTime())) {{
        return date.toLocaleTimeString([], {{ hour: '2-digit', minute: '2-digit', hour12: false }});
      }}
      return '--:--';
    }}

    function timelineTitle(event) {{
      const taskId = event && event.data && typeof event.data.task_id === 'string' ? event.data.task_id : null;
      const task = taskId ? currentTaskMap.get(taskId) : null;
      return task?.title || event.display_stage || event.stage || event.status_label || `#${{event.sequence || ''}}`;
    }}

    function timelineMetaMarkup(event) {{
      const data = event.data || {{}};
      const chips = [];
      if (event.stage) chips.push(chip(event.stage));
      if (event.timestamp) chips.push(chip(event.timestamp, {{ mono: true }}));
      if (event.status_label) chips.push(chip(event.status_label));
      if (data.transition_label) chips.push(chip(data.transition_label));
      if (data.agent) chips.push(chip(data.agent));
      if (data.file_path) chips.push(chip(data.file_path, {{ path: true }}));
      return chips.join('');
    }}

    function encodeEventPayload(event) {{
      return escapeHtml(JSON.stringify(event)).replace(/'/g, '&#39;');
    }}

    function decodeEventPayload(raw) {{
      return JSON.parse(raw.replace(/&#39;/g, "'"));
    }}

    function positionTimelineTooltip(anchor) {{
      const anchorRect = anchor.getBoundingClientRect();
      const portalRect = timelineTooltipPortal.getBoundingClientRect();
      const gap = 10;
      const minLeft = 12;
      const maxLeft = Math.max(minLeft, window.innerWidth - portalRect.width - 12);
      const desiredLeft = anchorRect.left + (anchorRect.width / 2) - (portalRect.width / 2);
      const left = Math.min(Math.max(desiredLeft, minLeft), maxLeft);
      const top = Math.max(12, anchorRect.top - portalRect.height - gap);

      timelineTooltipPortal.style.left = `${{left}}px`;
      timelineTooltipPortal.style.top = `${{top}}px`;
    }}

    function scheduleTimelineTooltipPosition(anchor) {{
      requestAnimationFrame(() => positionTimelineTooltip(anchor));
    }}

    let activeTimelineTooltipAnchor = null;

    function refreshTimelineTooltipPosition() {{
      if (activeTimelineTooltipAnchor && timelineTooltipPortal.classList.contains('open')) {{
        positionTimelineTooltip(activeTimelineTooltipAnchor);
      }}
    }}

    window.addEventListener('resize', refreshTimelineTooltipPosition);
    window.addEventListener('scroll', refreshTimelineTooltipPosition, true);

    function clearTimelineTooltipAnchor(anchor) {{
      if (!anchor || activeTimelineTooltipAnchor !== anchor) return;
      activeTimelineTooltipAnchor = null;
      hideTimelineTooltip();
    }}

    function activateTimelineTooltip(anchor, event) {{
      activeTimelineTooltipAnchor = anchor;
      showTimelineTooltip(anchor, event);
    }}

    document.addEventListener('keydown', (event) => {{
      if (event.key === 'Escape') {{
        activeTimelineTooltipAnchor = null;
        hideTimelineTooltip();
      }}
    }});

    document.addEventListener('pointerdown', (event) => {{
      if (!timelineTooltipPortal.classList.contains('open')) return;
      if (timelineTooltipPortal.contains(event.target)) return;
      if (activeTimelineTooltipAnchor && activeTimelineTooltipAnchor.contains(event.target)) return;
      activeTimelineTooltipAnchor = null;
      hideTimelineTooltip();
    }});

    function showTimelineTooltip(anchor, event) {{
      if (!anchor || !event) return;
      timelineTooltipTitle.textContent = timelineTitle(event);
      timelineTooltipMeta.innerHTML = timelineMetaMarkup(event);
      timelineTooltipMsg.textContent = event.message || 'No detail available.';
      timelineTooltipPortal.classList.add('open');
      timelineTooltipPortal.setAttribute('aria-hidden', 'false');
      scheduleTimelineTooltipPosition(anchor);
    }}

    function bindTimelineTooltipHandlers() {{
      timeline.querySelectorAll('.timeline-event').forEach((node) => {{
        const rail = node.querySelector('.timeline-rail');
        const raw = node.getAttribute('data-event');
        if (!rail || !raw) return;
        const event = decodeEventPayload(raw);
        const show = () => activateTimelineTooltip(rail, event);
        rail.addEventListener('mouseenter', show);
        rail.addEventListener('focus', show);
        rail.addEventListener('mouseleave', () => clearTimelineTooltipAnchor(rail));
        rail.addEventListener('blur', () => clearTimelineTooltipAnchor(rail));
      }});
    }}

    function renderTimeline(events) {{
      if (!events || !events.length) {{
        timeline.innerHTML = '<div class="empty-state">Waiting for pipeline events.<\/div>';
        activeTimelineTooltipAnchor = null;
        hideTimelineTooltip();
        return;
      }}
      timeline.innerHTML = events.map((event, index) => {{
        const stateClass = String(event.status_label || '').toLowerCase().replace(/\s+/g, '-');
        const isFirst = index === 0 ? ' is-first' : '';
        const isLast = index === events.length - 1 ? ' is-last' : '';
        const title = timelineTitle(event);
        const time = formatTimelineTime(event.timestamp);
        return `
          <div class="timeline-event timeline-${{escapeHtml(stateClass)}}${{isFirst}}${{isLast}}" tabindex="0" data-event='${{encodeEventPayload(event)}}'>
            <div class="timeline-label" title="${{escapeHtml(title)}}">${{escapeHtml(title)}}<\/div>
            <div class="timeline-rail" tabindex="0">
              <span class="timeline-dot"><\/span>
            <\/div>
            <div class="timeline-time">${{escapeHtml(time)}}<\/div>
          <\/div>`;
      }}).join('');
      bindTimelineTooltipHandlers();
    }}

    function hideTimelineTooltip() {{
      timelineTooltipPortal.classList.remove('open');
      timelineTooltipPortal.setAttribute('aria-hidden', 'true');
    }}

    function renderTaskCard(task) {{
      const terminalBadge = task.terminal_state
        ? `<span class=\"terminal-badge ${{escapeHtml(task.terminal_state)}}\">${{escapeHtml(task.terminal_state)}}<\/span>`
        : '';
      const actionClass = currentTaskId === task.task_id ? 'task-action active' : 'task-action';
      const actionLabel = currentTaskId === task.task_id ? 'Viewing output' : 'View output';
      return `
        <div class=\"task-card\">
          <div class=\"task-card-body\">
            <div class=\"task-top\">
              <div>
                <div class=\"task-title\">${{escapeHtml(task.title || task.stage_key || task.task_id)}}<\/div>
                <div class=\"task-id\">${{escapeHtml(task.task_id)}}<\/div>
              <\/div>
              ${{terminalBadge}}
            <\/div>
            <div class=\"task-summary\">${{escapeHtml(task.summary || 'Waiting for execution.')}}<\/div>
            <div class=\"task-output-actions\"><button type=\"button\" class=\"${{actionClass}}\" data-task-id=\"${{escapeHtml(task.task_id)}}\">${{escapeHtml(actionLabel)}}<\/button><\/div>
          <\/div>
        <\/div>`;
    }}

    function renderTaskList(container, countNode, tasks, emptyText) {{
      countNode.textContent = String(tasks.length);
      container.innerHTML = tasks.length
        ? tasks.map(renderTaskCard).join('')
        : `<div class=\"empty-state\">${{escapeHtml(emptyText)}}<\/div>`;
    }}

    function renderTaskBoard(snapshot) {{
      const tasks = (snapshot && snapshot.tasks) || [];
      currentTaskMap = new Map(tasks.map((task) => [task.task_id, task]));
      const pending = tasks.filter((task) => task.status === 'pending');
      const processing = tasks.filter((task) => task.status === 'processing');
      const completed = tasks.filter((task) => task.status === 'completed');
      renderTaskList(pendingTasks, pendingCount, pending, 'No pending tasks.');
      renderTaskList(processingTasks, processingCount, processing, 'No tasks are currently processing.');
      renderTaskList(completedTasks, completedCount, completed, 'No completed tasks yet.');
      document.querySelectorAll('[data-task-id]').forEach((node) => {{
        node.addEventListener('click', () => {{
          const taskId = node.getAttribute('data-task-id');
          if (!taskId) return;
          openTaskOutput(currentRunId, taskId).catch((error) => {{
            taskOutputModalTitle.textContent = 'Task output';
            taskOutput.innerHTML = `<div class="summary-empty">${{escapeHtml(error.message)}}<\/div>`;
            showTaskOutputModal();
          }});
        }});
      }});
    }}

    function showTaskOutputModal() {{
      taskOutputModal.classList.add('open');
      taskOutputModal.setAttribute('aria-hidden', 'false');
    }}

    function hideTaskOutputModal() {{
      taskOutputModal.classList.remove('open');
      taskOutputModal.setAttribute('aria-hidden', 'true');
    }}

    function renderTaskOutput(detail) {{
      const task = detail && detail.task ? detail.task : null;
      const output = detail && detail.output ? detail.output : null;
      if (!task) {{
        taskOutputModalTitle.textContent = 'Task output';
        taskOutput.innerHTML = '<div class="summary-empty">Select a task to inspect its output.<\/div>';
        return;
      }}
      const header = output || {{
        title: task.title,
        stage_key: task.stage_key,
        executor_kind: task.executor_kind,
        status: task.status,
        terminal_state: task.terminal_state,
        summary: task.summary,
        events: []
      }};
      const displayTitle = header.title || task.title || task.task_id;
      taskOutputModalTitle.textContent = displayTitle;
      const events = Array.isArray(output && output.events) ? output.events : [];
      const rawResult = output && Object.prototype.hasOwnProperty.call(output, 'result') ? output.result : null;
      const stdoutText = rawResult && typeof rawResult.stdout === 'string' ? rawResult.stdout : '';
      const stderrText = rawResult && typeof rawResult.stderr === 'string' ? rawResult.stderr : '';
      const errorBlock = output && output.error
        ? `<div class="empty-state">${{escapeHtml(output.error)}}<\/div>`
        : '';
      const stdoutBlock = stdoutText
        ? `<details class="details-block" open><summary>Stdout<\/summary><pre>${{escapeHtml(stdoutText)}}<\/pre><\/details>`
        : '<div class="summary-empty">No stdout captured yet.<\/div>';
      const stderrBlock = stderrText
        ? `<details class="details-block"><summary>Stderr<\/summary><pre>${{escapeHtml(stderrText)}}<\/pre><\/details>`
        : '';
      const eventsBlock = events.length
        ? `<details class="details-block"><summary>Task events (${{events.length}})<\/summary><pre>${{escapeHtml(JSON.stringify(events, null, 2))}}<\/pre><\/details>`
        : '<div class="summary-empty">No task events captured yet.<\/div>';
      const resultBlock = rawResult !== null
        ? `<details class="details-block"><summary>Task result<\/summary><pre>${{escapeHtml(JSON.stringify(rawResult, null, 2))}}<\/pre><\/details>`
        : '<div class="summary-empty">No task result captured yet.<\/div>';
      taskOutput.innerHTML = `
        <div class="task-output-header">
          <div class="task-output-body">
            <div class="task-output-title">${{escapeHtml(displayTitle)}}<\/div>
            <div class="task-summary">${{escapeHtml(header.summary || task.summary || 'Waiting for execution.')}}<\/div>
          <\/div>
        <\/div>
        <div class="task-output-result">
          ${{errorBlock}}
          ${{stdoutBlock}}
          ${{stderrBlock}}
          ${{resultBlock}}
          ${{eventsBlock}}
        <\/div>`;
    }}

    taskOutputClose.addEventListener('click', hideTaskOutputModal);
    taskOutputModal.addEventListener('click', (event) => {{
      if (event.target === taskOutputModal) hideTaskOutputModal();
    }});
    document.addEventListener('keydown', (event) => {{
      if (event.key === 'Escape' && taskOutputModal.classList.contains('open')) hideTaskOutputModal();
    }});
    taskOutputModal.querySelector('.modal-dialog').addEventListener('click', (event) => event.stopPropagation());

    async function openTaskOutput(runId, taskId) {{
      await loadTaskOutput(runId, taskId);
      showTaskOutputModal();
    }}


    function _taskActionLabel(task) {{
      return task.terminal_state || task.status || 'idle';
    }}

    async function loadTaskOutput(runId, taskId) {{
      if (!runId || !taskId) return;
      currentTaskId = taskId;
      const payload = await loadRunTaskDetail(runId, taskId);
      renderTaskOutput(payload);
    }}

    function flattenTree(node, depth = 0, rows = []) {{
      if (!node) return rows;
      rows.push({{ depth, detected_type: node.detected_type || 'UNKNOWN', file_path: node.file_path || '-' }});
      const children = node.next_stage_results || [];
      children.forEach((child) => flattenTree(child, depth + 1, rows));
      return rows;
    }}

    function renderArtifacts(result) {{
      const rows = flattenTree(result);
      artifactTree.innerHTML = rows.length
        ? rows.map((row) => `<div class=\"tree-item\" style=\"margin-left:${{row.depth * 12}}px\"><span class=\"artifact-type\">${{escapeHtml(row.detected_type)}}<\/span><span class=\"artifact-path\" title=\"${{escapeHtml(row.file_path)}}\">${{escapeHtml(row.file_path)}}<\/span><\/div>`).join('')
        : '<div class=\"empty-state\">No artifact tree yet.<\/div>';
    }}

    function processCard(process) {{
      const status = String(process.status || 'unknown').toLowerCase();
      const statusBadge = `<span class=\"terminal-badge ${{escapeHtml(status)}}\">${{escapeHtml(status)}}<\/span>`;
      const pid = process.pid ?? '-';
      return `
        <div class=\"process-card\">
          <div class=\"process-head\">
            <div>
              <div class=\"process-title\">${{escapeHtml(process.title || process.command_name || 'process')}}<\/div>
              <div class=\"process-subtitle\">PID ${{escapeHtml(String(pid))}} · ${{escapeHtml(process.stage_key || 'process')}}<\/div>
            <\/div>
            ${{statusBadge}}
          <\/div>
          <div class=\"process-command\">${{escapeHtml(process.command_text || process.command_name || '')}}<\/div>
          <div class=\"process-meta\">
            ${{chip(`pid:${{pid}}`, {{ mono: true }})}}
            ${{process.task_id ? chip(`task:${{process.task_id}}`, {{ mono: true }}) : ''}}
            ${{process.session_id ? chip(`session:${{process.session_id}}`, {{ mono: true }}) : ''}}
            ${{process.executor_kind ? chip(process.executor_kind) : ''}}
            ${{process.return_code !== null && process.return_code !== undefined ? chip(`exit:${{process.return_code}}`, {{ mono: true }}) : ''}}
            ${{process.started_at ? chip(process.started_at, {{ mono: true }}) : ''}}
          <\/div>
          ${{process.error ? `<div class=\"task-summary\">${{escapeHtml(process.error)}}<\/div>` : ''}}
          <div class=\"process-actions\">
            ${{process.task_id ? `<button type=\"button\" class=\"task-action\" data-task-id=\"${{escapeHtml(process.task_id)}}\">View output<\/button>` : ''}}
          <\/div>
        <\/div>`;
    }}

    async function stopCurrentRun() {{
      if (!currentRunId) return;
      try {{
        const response = await fetch(`/runs/${{encodeURIComponent(currentRunId)}}/stop`, {{ method: 'POST' }});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || `Stop failed: ${{response.status}}`);
        uploadStatus.className = 'status-text ready';
        uploadStatus.textContent = payload.status === 'cancelled'
          ? 'Run cancelled.'
          : `Run is already ${{payload.status}}.`;
        await refresh();
      }} catch (error) {{
        uploadStatus.className = 'status-text failed';
        uploadStatus.textContent = error.message;
      }}
    }}

    function renderProcesses(processSnapshot) {{
      const processes = (processSnapshot && processSnapshot.processes) || [];
      currentProcessSnapshot = processSnapshot || {{ processes: [] }};
      const active = processes.filter((process) => process.status === 'running');
      const failed = processes.filter((process) => process.status === 'failed');
      const completed = processes.filter((process) => process.status === 'completed');
      const canStop = currentRunId && !['completed', 'failed', 'cancelled'].includes(String((processSnapshot && processSnapshot.status) || '').toLowerCase());
      const stopButton = `<button type=\"button\" id=\"stopRunButton\" class=\"task-action danger-button\"${{canStop ? '' : ' disabled'}}>Stop run<\/button>`;
      const emptyState = processes.length
        ? ''
        : '<div class=\"summary-empty\">No related OS processes recorded for this run yet.<\/div>';
      processPanel.innerHTML = `
        <div class=\"process-stats\">
          <div class=\"process-stat\"><div class=\"label\">Total<\/div><div class=\"value mono\">${{processes.length}}<\/div><\/div>
          <div class=\"process-stat\"><div class=\"label\">Active<\/div><div class=\"value mono\">${{active.length}}<\/div><\/div>
          <div class=\"process-stat\"><div class=\"label\">Failed<\/div><div class=\"value mono\">${{failed.length}}<\/div><\/div>
        <\/div>
        <div class=\"process-actions\">${{stopButton}}<\/div>
        ${{emptyState}}
        ${{processes.length ? `<div class=\"process-list\">${{processes.map(processCard).join('')}}<\/div>` : ''}}
        ${{completed.length ? `<div class=\"summary-empty\">${{completed.length}} process(es) completed successfully.<\/div>` : ''}}`;
      const stopRunButton = document.getElementById('stopRunButton');
      if (stopRunButton) stopRunButton.addEventListener('click', stopCurrentRun);
      processPanel.querySelectorAll('[data-task-id]').forEach((node) => {{
        node.addEventListener('click', () => {{
          const taskId = node.getAttribute('data-task-id');
          if (!taskId) return;
          openTaskOutput(currentRunId, taskId).catch((error) => {{
            taskOutputModalTitle.textContent = 'Task output';
            taskOutput.innerHTML = `<div class=\"summary-empty\">${{escapeHtml(error.message)}}<\/div>`;
            showTaskOutputModal();
          }});
        }});
      }});
    }}

    function renderSummary(snapshot) {{
      if (!snapshot.result) {{
        summary.innerHTML = `<div class=\"summary-empty\">${{escapeHtml(snapshot.error || 'Run has not produced a result yet.')}}<\/div>`;
        return;
      }}
      const result = snapshot.result;
      const findings = Array.isArray(result.findings) ? result.findings : [];
      const iocs = Array.isArray(result.iocs) ? result.iocs : [];
      const raw = {{
        verdict: result.verdict,
        findings: result.findings,
        iocs: result.iocs,
        final_report_markdown: result.final_report_markdown
      }};
      summary.innerHTML = `
        <div class=\"summary-stats\">
          <div class=\"summary-stat\"><div class=\"label\">Verdict<\/div><div class=\"value\">${{escapeHtml(result.verdict || '—')}}<\/div><\/div>
          <div class=\"summary-stat\"><div class=\"label\">Findings<\/div><div class=\"value mono\">${{formatCount(findings)}}<\/div><\/div>
          <div class=\"summary-stat\"><div class=\"label\">IOCs<\/div><div class=\"value mono\">${{formatCount(iocs)}}<\/div><\/div>
          <div class=\"summary-stat\"><div class=\"label\">Report<\/div><div class=\"value\">${{result.final_report_markdown ? 'Ready' : 'None'}}<\/div><\/div>
        <\/div>
        <div class=\"summary-panels\">
          <div class=\"summary-panel\">
            <div class=\"summary-panel-title\">Findings<\/div>
            ${{renderList(findings, 'No findings yet.')}}
          <\/div>
          <div class=\"summary-panel\">
            <div class=\"summary-panel-title\">IOCs<\/div>
            ${{renderList(iocs, 'No IOCs yet.')}}
          <\/div>
        <\/div>
        <details class=\"details-block\">
          <summary>Raw output<\/summary>
          <pre>${{escapeHtml(JSON.stringify(raw, null, 2))}}<\/pre>
        <\/details>`;
    }}

    async function loadRun(runId) {{
      const response = await fetch(`/runs/${{encodeURIComponent(runId)}}`);
      if (!response.ok) throw new Error(`Run lookup failed: ${{response.status}}`);
      return response.json();
    }}

    async function loadRunTasks(runId) {{
      const response = await fetch(`/runs/${{encodeURIComponent(runId)}}/tasks`);
      if (!response.ok) throw new Error(`Task lookup failed: ${{response.status}}`);
      return response.json();
    }}

    async function loadRunTaskDetail(runId, taskId) {{
      const response = await fetch(`/runs/${{encodeURIComponent(runId)}}/tasks/${{encodeURIComponent(taskId)}}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || `Task detail failed: ${{response.status}}`);
      return payload;
    }}

    async function loadRunProcesses(runId) {{
      const response = await fetch(`/runs/${{encodeURIComponent(runId)}}/processes`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || `Process lookup failed: ${{response.status}}`);
      return payload;
    }}

    async function refresh() {{
      if (!currentRunId) return;
      try {{
        const boardScroll = captureScrollState(processingTasks);
        const completedScroll = captureScrollState(completedTasks);
        const pendingScroll = captureScrollState(pendingTasks);
        const timelineScroll = captureScrollState(timeline);
        const processScroll = captureScrollState(processPanel.querySelector('.process-list'));
        const summaryScroll = captureScrollState(summary);
        const taskOutputState = currentTaskId && taskOutputModal.classList.contains('open') ? captureTaskOutputState() : null;

        const [snapshot, taskSnapshot, processSnapshot] = await Promise.all([
          loadRun(currentRunId),
          loadRunTasks(currentRunId),
          loadRunProcesses(currentRunId)
        ]);
        setBadge(snapshot.status);
        renderMeta(snapshot);
        renderTaskBoard(taskSnapshot);
        restoreScrollState(pendingTasks, pendingScroll);
        restoreScrollState(processingTasks, boardScroll);
        restoreScrollState(completedTasks, completedScroll);
        renderTimeline(snapshot.pipeline_log || []);
        restoreScrollState(timeline, timelineScroll);
        renderArtifacts(snapshot.result);
        renderProcesses(processSnapshot);
        restoreScrollState(processPanel.querySelector('.process-list'), processScroll);
        renderSummary(snapshot);
        restoreScrollState(summary, summaryScroll);
        const tasks = (taskSnapshot && taskSnapshot.tasks) || [];
        if (currentTaskId) {{
          const activeTask = tasks.find((task) => task.task_id === currentTaskId);
          if (activeTask) {{
            try {{
              const detail = await loadRunTaskDetail(currentRunId, currentTaskId);
              renderTaskOutput(detail);
              restoreTaskOutputState(taskOutputState);
            }} catch (error) {{
              taskOutputModalTitle.textContent = 'Task output';
              taskOutput.innerHTML = `<div class="summary-empty">${{escapeHtml(error.message)}}<\/div>`;
            }}
          }} else {{
            currentTaskId = null;
            hideTaskOutputModal();
            renderTaskOutput(null);
          }}
        }} else if (!taskOutputModal.classList.contains('open')) {{
          renderTaskOutput(null);
        }}
        if (!currentRunId) hideTaskOutputModal();
        if (snapshot.status === 'completed' || snapshot.status === 'failed' || snapshot.status === 'cancelled') {{
          uploadRunButton.disabled = false;
          uploadStatus.className = `status-text ${{
            snapshot.status === 'completed' ? 'success' : snapshot.status === 'failed' ? 'failed' : 'ready'
          }}`;
          uploadStatus.textContent = snapshot.status === 'completed'
            ? 'Upload run completed.'
            : snapshot.status === 'failed'
              ? 'Upload run failed.'
              : 'Run cancelled.';
          if (pollHandle) clearInterval(pollHandle);
          pollHandle = null;
        }} else {{
          uploadStatus.className = currentRunId ? 'status-text ready' : 'status-text';
        }}
      }} catch (error) {{
        setBadge('failed');
        runMeta.innerHTML = metaRow('Error', error.message, {{ wide: true }});
        renderTaskBoard({{ tasks: [] }});
        renderTimeline([]);
        renderArtifacts(null);
        renderProcesses({{ processes: [] }});
        renderSummary({{ error: error.message }});
        if (!taskOutputModal.classList.contains('open')) renderTaskOutput(null);
        uploadRunButton.disabled = false;
        uploadStatus.className = 'status-text failed';
        uploadStatus.textContent = error.message;
      }}
    }}

    function openRun() {{
      currentRunId = runIdInput.value.trim();
      if (!currentRunId) return;
      currentTaskId = null;
      hideTaskOutputModal();
      renderTaskOutput(null);
      window.history.replaceState(null, '', `/dashboard/${{encodeURIComponent(currentRunId)}}`);
      uploadStatus.className = 'status-text ready';
      uploadStatus.textContent = '';
      if (pollHandle) clearInterval(pollHandle);
      refresh();
      pollHandle = setInterval(refresh, 1500);
    }}

    async function startUploadRun() {{
      const file = uploadFileInput.files && uploadFileInput.files[0];
      if (!file) {{
        uploadStatus.className = 'status-text failed';
        uploadStatus.textContent = 'Choose a file first.';
        return;
      }}

      uploadRunButton.disabled = true;
      uploadStatus.className = 'status-text ready';
      uploadStatus.textContent = 'Uploading sample and creating run...';
      const formData = new FormData();
      formData.append('file', file);
      formData.append('keep_file', keepFileInput.checked ? 'true' : 'false');

      try {{
        const response = await fetch('/runs/upload', {{ method: 'POST', body: formData }});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || `Upload failed: ${{response.status}}`);
        runIdInput.value = payload.run_id;
        currentRunId = payload.run_id;
        uploadStatus.textContent = `Queued upload run ${{payload.run_id}}.`;
        window.history.replaceState(null, '', `/dashboard/${{encodeURIComponent(currentRunId)}}`);
        if (pollHandle) clearInterval(pollHandle);
        refresh();
        pollHandle = setInterval(refresh, 1500);
      }} catch (error) {{
        uploadRunButton.disabled = false;
        uploadStatus.textContent = error.message;
      }}
    }}

    uploadFileInput.addEventListener('change', () => {{
      const file = uploadFileInput.files && uploadFileInput.files[0];
      selectedFileName.textContent = file ? file.name : 'No file selected.';
      if (file) {{
        uploadStatus.className = 'status-text ready';
        uploadStatus.textContent = '';
      }}
    }});
    openRunButton.addEventListener('click', openRun);
    uploadRunButton.addEventListener('click', startUploadRun);
    if (currentRunId) openRun();
  </script>
</body>
</html>"""


