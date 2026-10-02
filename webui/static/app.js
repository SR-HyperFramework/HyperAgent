// --- Theme toggle ------------------------------------------------------------
// With nothing stored the page follows the OS; the first click adopts whatever
// is showing and flips it, so the button never appears to do nothing.
(() => {
  const button = document.getElementById("theme-toggle");
  if (!button) return;

  const root = document.documentElement;
  const dark = window.matchMedia("(prefers-color-scheme: dark)");

  function current() {
    return root.dataset.theme || (dark.matches ? "dark" : "light");
  }

  function label() {
    button.title = current() === "dark" ? "Switch to light theme" : "Switch to dark theme";
    button.setAttribute("aria-label", button.title);
  }

  button.addEventListener("click", () => {
    const next = current() === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try {
      localStorage.setItem("hyperagent-theme", next);
    } catch (err) { /* private mode: the choice just won't persist */ }
    label();
  });

  dark.addEventListener("change", label);
  label();
})();

// --- Locale-aware timestamps ------------------------------------------------
// The server can only emit an unambiguous ISO date; the viewer's locale is a
// client-side fact, so upgrade in place from the machine-readable datetime.
(() => {
  const stamps = document.querySelectorAll("time[data-stamp][datetime]");
  if (!stamps.length) return;

  const day = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
  const full = new Intl.DateTimeFormat(undefined, { dateStyle: "long", timeStyle: "short" });

  for (const stamp of stamps) {
    const when = new Date(stamp.dateTime);
    if (Number.isNaN(when.valueOf())) continue;
    stamp.textContent = day.format(when);
    stamp.title = full.format(when);
  }
})();

// --- Live time counters ------------------------------------------------------
(() => {
  const counters = document.querySelectorAll("time[data-time-counter][datetime]");
  if (!counters.length) return;

  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  const full = new Intl.DateTimeFormat(undefined, { dateStyle: "long", timeStyle: "medium" });
  const units = [
    ["year", 31536000],
    ["month", 2592000],
    ["week", 604800],
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
    ["second", 1],
  ];

  function relativeText(when) {
    const delta = Math.round((when.getTime() - Date.now()) / 1000);
    const abs = Math.abs(delta);
    for (const [unit, seconds] of units) {
      if (abs >= seconds || unit === "second") {
        return rtf.format(Math.round(delta / seconds), unit);
      }
    }
  }

  const valid = [];
  for (const counter of counters) {
    const when = new Date(counter.dateTime);
    if (Number.isNaN(when.valueOf())) continue;
    counter.title = full.format(when);
    valid.push([counter, when]);
  }

  function update() {
    for (const [counter, when] of valid) {
      counter.textContent = relativeText(when);
    }
  }

  update();
  setInterval(update, 1000);
})();

// --- Copy to clipboard -------------------------------------------------------
(() => {
  const announcer = document.createElement("p");
  announcer.className = "sr-only";
  announcer.setAttribute("aria-live", "polite");
  document.body.append(announcer);

  // navigator.clipboard needs a secure context, so fall back to a throwaway
  // textarea when the viewer is served over plain http.
  async function writeText(value) {
    if (navigator.clipboard && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(value);
        return true;
      } catch {
        /* fall through to the textarea path */
      }
    }

    const scratch = document.createElement("textarea");
    scratch.value = value;
    scratch.setAttribute("readonly", "");
    scratch.style.position = "fixed";
    scratch.style.opacity = "0";
    document.body.append(scratch);
    scratch.select();
    let copied = false;
    try {
      copied = document.execCommand("copy");
    } catch {
      copied = false;
    }
    scratch.remove();
    return copied;
  }

  document.addEventListener("click", async (event) => {
    const button = event.target.closest(".copy");
    if (!button) return;

    const copied = await writeText(button.dataset.copy || "");
    const original = button.dataset.label || button.textContent;
    button.dataset.label = original;
    button.textContent = copied ? "Copied" : "Failed";
    button.dataset.copied = copied ? "1" : "0";
    announcer.textContent = copied ? "Copied to clipboard." : "Copy failed. Select the value and copy it manually.";

    setTimeout(() => {
      button.textContent = original;
      delete button.dataset.copied;
    }, 1400);
  });
})();

// --- Live run page -------------------------------------------------------------
// Re-fetch the server-rendered regions and swap in only the ones that changed,
// so the page never builds markup from run data itself (it is all escaped by
// the template) and an unchanged region keeps its scroll position.
(() => {
  const shell = document.querySelector("[data-live-src]");
  if (!shell) return;

  const source = shell.dataset.liveSrc;
  const lost = document.getElementById("live-lost");
  const FINAL = new Set(["completed", "failed", "stopped"]);
  let failures = 0;

  function pinFeeds(root) {
    for (const feed of root.querySelectorAll("[data-live-scroll]")) feed.scrollTop = feed.scrollHeight;
  }

  function scrollState(region) {
    const state = new Map();
    for (const feed of region.querySelectorAll("[data-live-scroll][id]")) {
      const atBottom = feed.scrollTop + feed.clientHeight >= feed.scrollHeight - 8;
      state.set(feed.id, { atBottom, top: feed.scrollTop });
    }
    return state;
  }

  function restoreScroll(region, state) {
    for (const [id, saved] of state) {
      const feed = region.querySelector(`#${CSS.escape(id)}`);
      if (feed) feed.scrollTop = saved.atBottom ? feed.scrollHeight : saved.top;
    }
  }

  // A tool burst the reader expanded stays expanded across updates (and an
  // opened <details> alone is not a change worth swapping the region for).
  function keepOpen(region, incoming) {
    for (const details of region.querySelectorAll("details[data-key]")) {
      const twin = incoming.querySelector(`details[data-key="${CSS.escape(details.dataset.key)}"]`);
      if (twin) twin.open = details.open;
    }
  }

  function currentState() {
    const marker = document.getElementById("live-state");
    return marker ? marker.dataset.liveState : "";
  }

  async function refresh() {
    const response = await fetch(source, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const next = new DOMParser().parseFromString(await response.text(), "text/html");
    for (const incoming of next.querySelectorAll("[data-live-region][id]")) {
      const region = document.getElementById(incoming.id);
      if (!region) continue;
      keepOpen(region, incoming);
      if (region.outerHTML === incoming.outerHTML) continue;
      const saved = scrollState(region);
      const adopted = document.adoptNode(incoming);
      region.replaceWith(adopted);
      restoreScroll(adopted, saved);
    }
  }

  async function tick() {
    try {
      await refresh();
      failures = 0;
      if (lost) lost.hidden = true;
    } catch {
      failures += 1;
      // One miss can be a slow response; two in a row means the CLI that
      // hosts this dashboard has exited.
      if (lost && failures >= 2) lost.hidden = false;
    }
    if (failures >= 6) return;
    const state = currentState();
    const delay = failures ? 4000 : state === "running" ? 1500 : FINAL.has(state) ? 10000 : 4000;
    setTimeout(tick, delay);
  }

  pinFeeds(document);
  setTimeout(tick, 1500);
})();
