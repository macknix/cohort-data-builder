/* Loading the catalogue, switching dataset, and starting the views.

   The only module that knows all the others exist. The dataset in view is
   named in the URL hash (#bcs70), so a link can point at one. */

import { $, $$ } from "./dom.js";
import { indexTopics, state, storeKey } from "./state.js";
import { switchView } from "./views.js";
import * as search from "./search.js";
import * as basket from "./basket.js";
import * as panel from "./panel.js";

async function getJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return res.json();
}

function fail(msg) {
  document.body.innerHTML =
    '<p style="font-family:var(--mono);padding:40px;max-width:60ch">' + msg + "</p>";
}

/* Settings and selections were stored under the tool's old name,
   survey-merge; move them across once so nobody loses them. */
function migrateStorage() {
  try {
    const old = "survey-merge:";
    for (const key of Object.keys(localStorage)) {
      if (!key.startsWith(old)) continue;
      const renamed = `cohort-data-builder:${key.slice(old.length)}`;
      if (localStorage.getItem(renamed) === null) localStorage.setItem(renamed, localStorage.getItem(key));
      localStorage.removeItem(key);
    }
  } catch { /* storage unavailable: nothing to move */ }
}

async function boot() {
  migrateStorage();
  try {
    state.catalogue = (await getJson("data/datasets.json")).datasets;
  } catch {
    fail("Could not load the site data. Build it first:<br><br>" +
         "<code>python3 build.py</code><br>" +
         "<code>python3 -m http.server -d site</code>");
    return;
  }
  if (!state.catalogue.length) { fail("No datasets have been built."); return; }

  $("#dataset").innerHTML = state.catalogue.map((d) =>
    `<option value="${d.key}">${d.name}</option>`).join("");
  basket.restoreOptions();
  wire();
  await openDataset(chooseDataset());
}

function chooseDataset() {
  const keys = state.catalogue.map((d) => d.key);
  const fromHash = decodeURIComponent(location.hash.slice(1));
  if (keys.includes(fromHash)) return fromHash;
  try {
    const last = localStorage.getItem(storeKey("dataset", "_site"));
    if (keys.includes(last)) return last;
  } catch { /* fine */ }
  return keys[0];
}

async function openDataset(key) {
  if (state.manifest?.key === key) return;
  $("#dataset").value = key;
  $("#dataset").disabled = true;
  try {
    const [manifest, vars] = await Promise.all([
      getJson(`data/${key}/manifest.json`),
      getJson(`data/${key}/index.json`),
    ]);
    state.manifest = manifest;
    state.vars = vars;
    state.anchor = null;   // a range never starts in another dataset
  } catch (err) {
    fail(`Could not load the ${key} data: ${err.message}`);
    return;
  } finally {
    $("#dataset").disabled = false;
  }

  if (location.hash.slice(1) !== key) history.replaceState(null, "", `#${key}`);
  try { localStorage.setItem(storeKey("dataset", "_site"), key); } catch { /* fine */ }

  // Filters and the open variable belong to the dataset being left.
  Object.assign(state, { query: "", waveFilter: null, fileFilter: null,
                         levelFilter: null, topicSel: [], topicMode: "any",
                         gridExpanded: new Set(), expanded: new Set(), allValues: new Set() });
  indexTopics();
  $("#q").value = "";

  const m = state.manifest;
  document.title = `${m.name} · Cohort Data Builder`;
  $("#mark-sub").textContent = m.fullName;
  $("#foot-counts").textContent =
    `${m.counts.variables.toLocaleString()} variables · ${m.counts.files} files · ` +
    `${m.wave.list.length} ${m.wave.plural} · built ${m.built}`;

  basket.restore();
  search.buildLabelIndex();
  search.renderAbout();
  search.runSearch();
  basket.render();
}

/* ── Resizing the list column ─────────────────────────────────────────
   One width for both views, stored once for the site. Pointer events so a
   trackpad, touch and pen all work; arrow keys too. */
const RAIL_MIN = 260;
const RAIL_DEFAULT = 400;      // must match --rail in styles.css
const railMax = () => Math.max(RAIL_MIN, Math.round(window.innerWidth * 0.7));
const currentRail = () =>
  parseInt(getComputedStyle(document.documentElement).getPropertyValue("--rail"), 10);

function setRail(px, remember = true) {
  const w = Math.min(railMax(), Math.max(RAIL_MIN, Math.round(px)));
  document.documentElement.style.setProperty("--rail", `${w}px`);
  $$(".grip").forEach((g) => g.setAttribute("aria-valuenow", String(w)));
  if (!remember) return;
  try { localStorage.setItem(storeKey("rail", "_site"), `${w}px`); } catch { /* fine */ }
}

function wireGrips() {
  try {
    const saved = localStorage.getItem(storeKey("rail", "_site"));
    if (saved) setRail(parseInt(saved, 10) || RAIL_DEFAULT, false);
  } catch { /* private browsing */ }

  $$(".grip").forEach((grip) => {
    grip.setAttribute("aria-valuemin", String(RAIL_MIN));
    grip.addEventListener("pointerdown", (e) => {
      grip.setPointerCapture(e.pointerId);
      document.body.classList.add("is-resizing");
      e.preventDefault();
    });
    grip.addEventListener("pointermove", (e) => {
      if (!grip.hasPointerCapture(e.pointerId)) return;
      setRail(e.clientX - grip.parentElement.getBoundingClientRect().left, false);
    });
    const end = (e) => {
      if (!grip.hasPointerCapture(e.pointerId)) return;
      grip.releasePointerCapture(e.pointerId);
      document.body.classList.remove("is-resizing");
      setRail(currentRail());
    };
    grip.addEventListener("pointerup", end);
    grip.addEventListener("pointercancel", end);
    grip.addEventListener("dblclick", () => setRail(RAIL_DEFAULT));
    grip.addEventListener("keydown", (e) => {
      const step = e.shiftKey ? 64 : 16;
      if (e.key === "ArrowLeft") setRail(currentRail() - step);
      else if (e.key === "ArrowRight") setRail(currentRail() + step);
      else if (e.key === "Home") setRail(RAIL_DEFAULT);
      else return;
      e.preventDefault();
    });
  });

  window.addEventListener("resize", () => {
    if (currentRail() > railMax()) setRail(railMax());
  });
}

/* A row scrolled to on the long page stops clear of the masthead, whose
   height depends on how its contents wrap; measured rather than guessed. */
function trackMastheadHeight() {
  const mast = $(".masthead");
  const set = () => document.documentElement.style.setProperty("--mast-h", `${mast.offsetHeight}px`);
  set();
  if (typeof ResizeObserver === "function") new ResizeObserver(set).observe(mast);
}

function wire() {
  $$(".view-tab").forEach((t) => t.addEventListener("click", () => switchView(t.dataset.view)));
  $("#dataset").addEventListener("change", (e) => openDataset(e.target.value));
  window.addEventListener("hashchange", () => {
    const key = decodeURIComponent(location.hash.slice(1));
    if (state.catalogue.some((d) => d.key === key)) openDataset(key);
  });

  search.wire();
  search.onOptions(basket.saveOptions);
  basket.wire();
  panel.wire();
  basket.onChange(() => {
    panel.render();
    if (state.view === "search") search.refreshSelection();
  });
  basket.onOpenFile((name) => {
    const i = state.manifest.files.findIndex((f) => f.name === name);
    if (i >= 0) search.filterToFile(i);
  });
  wireGrips();
  trackMastheadHeight();

  const theme = $("#theme");
  try {
    const stored = localStorage.getItem(storeKey("theme", "_site"));
    if (stored) document.documentElement.dataset.theme = stored;
  } catch { /* fine */ }
  theme.addEventListener("click", () => {
    const now = document.documentElement.dataset.theme ||
      (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = now === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem(storeKey("theme", "_site"), next); } catch { /* fine */ }
  });
}

boot();
