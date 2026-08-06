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

// --- Report tabs -------------------------------------------------------------
// Panels render expanded so the page still reads top-to-bottom without JS; this
// collapses them into tabs once scripting is available.
(() => {
  const tablist = document.querySelector(".tabs");
  if (!tablist) return;

  const tabs = [...tablist.querySelectorAll(".tab")];
  const panels = new Map(
    tabs.map((tab) => [tab.dataset.panel, document.getElementById(tab.dataset.panel)]),
  );

  function select(name, { updateHash = true } = {}) {
    if (!panels.has(name)) return;
    for (const tab of tabs) {
      const active = tab.dataset.panel === name;
      tab.setAttribute("aria-selected", active ? "true" : "false");
      tab.tabIndex = active ? 0 : -1;
      panels.get(tab.dataset.panel).hidden = !active;
    }
    if (updateHash) history.replaceState(null, "", `#${name}`);
  }

  tablist.addEventListener("click", (event) => {
    const tab = event.target.closest(".tab");
    if (tab) select(tab.dataset.panel);
  });

  tablist.addEventListener("keydown", (event) => {
    const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
    if (!step) return;
    event.preventDefault();
    const index = tabs.findIndex((tab) => tab.getAttribute("aria-selected") === "true");
    const next = tabs[(index + step + tabs.length) % tabs.length];
    select(next.dataset.panel);
    next.focus();
  });

  const fromHash = decodeURIComponent(location.hash.slice(1));
  select(panels.has(fromHash) ? fromHash : tabs[0].dataset.panel, { updateHash: false });
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
