/* The first row of the overview chart: every matching variable, by sweep.

   Drawing only; the click that filters to one sweep is wired by the search
   view. Sweeps with no matches are drawn as gaps rather than left out:
   absence is usually the thing you need to know. */

import { $ } from "./dom.js";
import { esc, state } from "./state.js";
import { selectionTitle } from "./topics.js";

export function renderSpine() {
  if (!state.manifest) return;
  const waves = state.manifest.wave.list;
  const counts = new Array(waves.length).fill(0);
  state.matches.forEach((row) => { counts[row[3]] += 1; });

  const max = Math.max(1, ...counts);
  const topic = selectionTitle();
  const filtered = state.query || state.fileFilter !== null || state.levelFilter !== null ||
    state.waveFilter !== null || topic;
  $("#spine-title").textContent = topic || (filtered ? "Matching variables" : "All variables");
  $("#spine-title").title = topic;
  $("#spine-note").textContent = state.matches.length.toLocaleString();

  $("#spine-track").innerHTML = waves.map((wave, i) => {
    const n = counts[i];
    const pct = n ? Math.max(6, Math.round((n / max) * 100)) : 0;
    const on = state.waveFilter === i;
    return `<li>
      <button class="node${n ? "" : " is-empty"}" data-wave="${i}" aria-pressed="${on}"
              title="${esc(wave.key)}${wave.label ? ` · ${esc(wave.label)}` : ""} — ${n.toLocaleString()} ${n === 1 ? "variable" : "variables"}. Click to show only this ${esc(state.manifest.wave.term)}.">
        <span class="node-bar"><span class="node-fill" style="height:${pct}%"></span></span>
        <span class="node-age">${esc(wave.key)}</span>
        <span class="node-n">${n ? n.toLocaleString() : "—"}</span>
      </button></li>`;
  }).join("");
}
