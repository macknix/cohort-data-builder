/* The selection, beside the list: what you have picked so far, kept in view
   while you pick, so a click visibly lands somewhere.

   A summary rather than the whole Selection view: a count, the variables
   grouped by sweep or by file, a filter for when there are hundreds, and a
   way out to the Selection view for renaming columns and downloading. Built
   to stay quick with thousands selected: a group shows its first
   GROUP_SHOWN rows until asked for the rest, and a closed group draws none. */

import { $ } from "./dom.js";
import { capitalise, esc, state, waveKeys } from "./state.js";
import { switchView } from "./views.js";
import * as basket from "./basket.js";

const GROUP_SHOWN = 200;

const keyOf = (b) => `${b.file}:${b.name}`;
const closed = new Set();     // groups folded away, by key
const full = new Set();       // groups showing every row
let filter = "";
let clearArmed = null;        // the timer while "Clear" waits for a second click

function groupsOf(items) {
  const byFile = state.options.panelGroup === "file";
  const keys = waveKeys();
  const groups = new Map();
  for (const b of items) {
    const g = byFile ? b.file : b.wave;
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(b);
  }
  return [...groups].sort(([a], [b]) => byFile ? a.localeCompare(b) : keys.indexOf(a) - keys.indexOf(b));
}

function rowHtml(b, bad) {
  const problem = bad.get(keyOf(b));
  return `<li class="sp-row${problem ? " is-bad" : ""}">
    <span class="sp-name" title="${esc(b.name)}">${problem ? `<span class="sp-flag" title="${esc(problem)}">⚠</span>` : ""}${esc(b.name)}</span>
    <span class="sp-label" title="${esc(b.label || "no label")}">${esc(b.label || "no label")}</span>
    <span class="sp-meta" title="${esc(b.file)}">${esc(state.options.panelGroup === "file" ? b.wave : b.file)}</span>
    <button class="sp-x" data-remove="${esc(keyOf(b))}" aria-label="Remove ${esc(b.name)}" title="Remove">✕</button>
  </li>`;
}

export function render() {
  if (!state.manifest) return;
  const n = state.bundle.length;
  const term = state.manifest.wave.term;
  $("#sp-toggle").textContent = `Selected (${n.toLocaleString()})`;
  $("#sp-count").innerHTML = n
    ? `<strong>${n.toLocaleString()}</strong> variable${n === 1 ? "" : "s"} selected`
    : "Nothing selected yet";
  $("#sp-clear").hidden = !n;
  $("#sp-tools").hidden = !n;
  $("#sp-review").hidden = !n;
  $("#sp-group-wave").textContent = capitalise(term);
  for (const b of document.querySelectorAll("#spanel [data-group]")) {
    b.setAttribute("aria-pressed", String(b.dataset.group === (state.options.panelGroup || "wave")));
  }

  const bad = basket.problems();
  const warn = $("#sp-warn");
  warn.hidden = !bad.size;
  if (bad.size) {
    warn.innerHTML = `⚠ ${bad.size} column name${bad.size === 1 ? "" : "s"} clash
      <button class="link-btn" id="sp-fix">fix</button>`;
  }

  const list = $("#sp-list");
  if (!n) {
    list.innerHTML = `<p class="sp-empty">Click a variable to add it here.</p>`;
    return;
  }
  const q = filter.trim().toLowerCase();
  const items = q
    ? state.bundle.filter((b) => b.name.toLowerCase().includes(q) || (b.label || "").toLowerCase().includes(q))
    : state.bundle;
  if (!items.length) {
    list.innerHTML = `<p class="sp-empty">None of the ${n.toLocaleString()} match “${esc(filter.trim())}”.</p>`;
    return;
  }
  list.innerHTML = groupsOf(items).map(([g, rows]) => {
    const open = !closed.has(g);
    const shown = open ? (full.has(g) ? rows : rows.slice(0, GROUP_SHOWN)) : [];
    return `<section class="sp-grp">
      <button class="sp-grp-head" data-grp="${esc(g)}" aria-expanded="${open}">
        <span class="sp-caret" aria-hidden="true">${open ? "▾" : "▸"}</span>
        <span class="sp-grp-name">${esc(g)}</span>
        <span class="sp-grp-n">${rows.length.toLocaleString()}</span></button>
      ${open ? `<ul class="sp-rows">${shown.map((b) => rowHtml(b, bad)).join("")}</ul>` : ""}
      ${open && shown.length < rows.length
        ? `<button class="link-btn sp-all" data-all="${esc(g)}">Show all ${rows.length.toLocaleString()}</button>` : ""}
    </section>`;
  }).join("");
}

function setOpen(open) {
  state.options.panelOpen = open;
  $(".vwork").classList.toggle("is-panel-open", open);
  $("#sp-toggle").setAttribute("aria-expanded", String(open));
  basket.saveOptions();
}

export function wire() {
  setOpen(!!state.options.panelOpen);
  $("#sp-toggle").addEventListener("click", () => setOpen(!state.options.panelOpen));

  $("#sp-q").addEventListener("input", (e) => { filter = e.target.value; render(); });

  $("#spanel").addEventListener("click", (e) => {
    const group = e.target.closest("[data-group]");
    if (group) {
      state.options.panelGroup = group.dataset.group;
      basket.saveOptions();
      closed.clear(); full.clear();
      render();
      return;
    }
    const head = e.target.closest("[data-grp]");
    if (head) {
      const g = head.dataset.grp;
      if (closed.has(g)) closed.delete(g); else closed.add(g);
      render();
      $(`#sp-list [data-grp="${CSS.escape(g)}"]`)?.focus();
      return;
    }
    const all = e.target.closest("[data-all]");
    if (all) { full.add(all.dataset.all); render(); return; }

    const x = e.target.closest("[data-remove]");
    if (x) {
      // Focus moves to the next ✕, so a keyboard user can keep removing.
      const at = [...document.querySelectorAll("#sp-list .sp-x")].indexOf(x);
      const had = document.activeElement === x;
      basket.remove(x.dataset.remove);
      if (had) {
        const rest = document.querySelectorAll("#sp-list .sp-x");
        (rest[Math.min(at, rest.length - 1)] || $("#sp-list")).focus();
      }
      return;
    }
    if (e.target.closest("#sp-fix")) {
      switchView("basket");
      document.querySelector("#basket-detail .col-row.is-bad .col-input")?.focus();
      return;
    }
    if (e.target.closest("#sp-review")) { switchView("basket"); return; }
    if (e.target.closest("#sp-clear")) {
      // Two clicks: a few hundred picks shouldn't go on one slip.
      const btn = $("#sp-clear");
      if (clearArmed) {
        clearTimeout(clearArmed); clearArmed = null;
        btn.textContent = "Clear";
        basket.clear();
      } else {
        btn.textContent = `Clear all ${state.bundle.length.toLocaleString()}?`;
        clearArmed = setTimeout(() => { clearArmed = null; btn.textContent = "Clear"; }, 4000);
      }
    }
  });
}
