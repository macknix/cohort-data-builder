/* Which view is on screen. Its own module so the views can switch to each
   other without importing each other. */

import { $$ } from "./dom.js";
import { state } from "./state.js";
import { renderSpine } from "./spine.js";

export function switchView(name) {
  state.view = name;
  $$(".view-tab").forEach((t) => {
    const on = t.dataset.view === name;
    t.classList.toggle("is-current", on);
    if (on) t.setAttribute("aria-current", "page"); else t.removeAttribute("aria-current");
  });
  $$(".view").forEach((v) => v.classList.toggle("is-current", v.dataset.view === name));
  renderSpine();
}
