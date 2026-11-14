// `/contested`: every contested field across all dossiers, by domain then field order.

import { request } from "../api.js";
import { banner, h, replace } from "../dom.js";
import { FIELDS, FIELD_LABELS, rawValue, valueParts } from "../format.js";
import { createReader } from "../reader.js";
import { valueNode } from "./dossier.js";
import { listAll } from "./list.js";

const AT_ONCE = 6;

async function contestedFields() {
  const listed = await listAll();
  if (listed.outcome !== "ok") return listed;
  const dossiers = [];
  for (let i = 0; i < listed.data.length; i += AT_ONCE) {
    const batch = await Promise.all(listed.data.slice(i, i + AT_ONCE)
      .map((d) => request("GET", `/dossiers/${d.domain}`)));
    if (batch.some((r) => r.outcome !== "ok" && r.status !== 404)) {
      return batch.find((r) => r.outcome !== "ok");
    }
    dossiers.push(...batch.filter((r) => r.outcome === "ok").map((r) => r.data));
  }
  const items = [];
  for (const d of dossiers) {  // the list API returns dossiers by domain, ascending
    for (const name of FIELDS) {
      if (d.fields[name].status === "contested") items.push({ domain: d.domain, name, field: d.fields[name] });
    }
  }
  return { outcome: "ok", data: items };
}

function item({ domain, name, field }) {
  const values = [];
  for (const c of field.candidates) {
    if (!values.some((v) => JSON.stringify(v) === JSON.stringify(c.value))) values.push(c.value);
  }
  return h("li", {},
    h("a", { class: "list-item", href: `/dossiers/${domain}/evidence`, "data-link": "",
             testid: `contested-item-${domain}-${name}`, "data-value": rawValue(field.value) },
      h("span", { class: "list-item__main" },
        h("span", { class: "list-item__title" }, domain),
        h("span", {}, h("strong", {}, FIELD_LABELS[name]), " ",
          h("code", { class: "muted small" }, name))),
      h("span", { class: "stack small" },
        h("span", {}, "Selected: ", valueNode(name, field.value, { class: "wrap" })),
        h("span", { class: "muted wrap" }, "Values found: ",
          values.map((v, i) => [i ? "; " : "", valueParts(name, v).shown,
            valueParts(name, v).raw && h("span", { class: "visually-hidden",
                                                   "aria-hidden": "true" },
              ` ${valueParts(name, v).raw}`)])))));
}

export function mount(main) {
  const body = h("div", { class: "stack", "aria-live": "polite" },
    banner("loading", {}, "Looking through every dossier…"));
  const reader = createReader(contestedFields, (result) => {
    if (result.outcome !== "ok") {
      replace(body, banner("error", {}, "The contested fields could not be loaded. ",
        h("button", { type: "button", class: "button button--quiet",
                      onclick: () => reader.read() }, "Try again")));
      return;
    }
    replace(body, result.data.length
      ? h("ul", { class: "list", testid: "contested-list" }, result.data.map(item))
      : h("div", { class: "empty", testid: "empty-contested" },
          "No field is contested: wherever sources state a value, they agree."));
  });
  main.append(h("section", { class: "stack" },
    h("h1", {}, "Contested fields"),
    h("p", { class: "muted" }, "Fields where sources disagree. Open one to compare every " +
      "source and see which value the selection rule picked.")), body);
  reader.read();
  return null;
}
