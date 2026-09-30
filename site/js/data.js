/* Fetching a dataset's per-file dictionaries, and describing what they say. */

import { state } from "./state.js";

export async function loadDict(file) {
  const key = `${state.manifest.key}/${file}`;
  if (state.dictCache.has(key)) return state.dictCache.get(key);
  const res = await fetch(`data/${state.manifest.key}/dict/${encodeURIComponent(file)}.json`);
  if (!res.ok) throw new Error(`no dictionary for ${file}`);
  const data = await res.json();
  state.dictCache.set(key, data);
  return data;
}

/* "-9, -8, -3 to -1, -1 and below" — what 'missing codes to NA' replaces. */
export function describeNa(na) {
  if (!na) return "";
  const parts = na.values.map(String);
  for (const [lo, hi] of na.ranges) {
    parts.push(lo === null ? `${hi} and below` : hi === null ? `${lo} and above` : `${lo} to ${hi}`);
  }
  return parts.join(", ");
}
