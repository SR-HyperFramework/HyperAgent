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
