// `/dossiers/{domain}/evidence`: every candidate of every field, in selection-rule order.
// Executives (stage 3) and investors (stage 4) are listed in their own sections, with no
// data-testid. Each candidate also shows its origin (stage 4).

import { request } from "../api.js";
import { banner, chip, h, replace } from "../dom.js";
import { EXECUTIVES, EXECUTIVES_LABEL, EXTRA_FIELDS, FIELDS, FIELD_LABELS, INVESTORS,
         INVESTORS_LABEL, STATUS_LABELS, TITLE_LABELS, formatDate, hostOf, kindLabel,
         providerLabel, rawValue } from "../format.js";
import { createReader } from "../reader.js";
import { notFound, valueNode } from "./dossier.js";

function candidate(field, c, n) {
  const executives = field === EXECUTIVES;
  return h("li", { class: "candidate",
                   testid: EXTRA_FIELDS.includes(field) ? null : `candidate-${field}-${n}`,
                   "data-title": c.title ?? null,
                   "data-value": rawValue(c.value), "data-provider": c.provider,
                   "data-kind": c.kind ?? "", "data-url": c.url,
                   "data-published-at": c.published_at ?? "",
                   "data-selected": c.selected ? "true" : "false" },
    h("div", { class: "row" },
      executives && h("span", { class: "muted" }, `${TITLE_LABELS[c.title] || c.title}:`),
      valueNode(field, c.value, { class: "candidate__value" }),
      c.selected && h("span", { class: "selected-tag" }, "✓ Selected")),
    h("blockquote", { class: "wrap" }, `“${c.excerpt}”`),
    h("p", { class: "meta" },
      h("span", {}, kindLabel(c.kind)),
      h("span", {}, c.published_at ? `Published ${formatDate(c.published_at)}`
        : "Publication date not stated"),
      h("span", {}, `via ${providerLabel(c.provider)}`),
      c.origin && h("span", {}, `source ${c.origin}`),
      h("a", { href: c.url, rel: "noopener noreferrer", target: "_blank", class: "wrap" },
        hostOf(c.url))));
}

function section(name, field) {
  return h("section", { class: "stack", "aria-labelledby": `evidence-title-${name}` },
    h("div", { class: "section-title" },
      h("h2", { id: `evidence-title-${name}` }, FIELD_LABELS[name]),
      chip(field.status, STATUS_LABELS[field.status]),
      h("span", { class: "muted small" }, `${field.candidates.length} ` +
        (field.candidates.length === 1 ? "source" : "sources"))),
    field.candidates.length
      ? h("ol", { class: "candidates", testid: `evidence-${name}` },
          field.candidates.map((c, i) => candidate(name, c, i + 1)))
      : h("div", { testid: `evidence-${name}` },
          h("p", { class: "empty", testid: `evidence-empty-${name}` },
            "No source states this field.")));
}

function extraSection(name, label, field, empty) {
  return h("section", { class: "stack", "data-section": name,
                        "aria-labelledby": `evidence-title-${name}` },
    h("div", { class: "section-title" },
      h("h2", { id: `evidence-title-${name}` }, label),
      chip(field.status, STATUS_LABELS[field.status]),
      h("span", { class: "muted small" }, `${field.candidates.length} ` +
        (field.candidates.length === 1 ? "source" : "sources"))),
    field.candidates.length
      ? h("ol", { class: "candidates" },
          field.candidates.map((c, i) => candidate(name, c, i + 1)))
      : h("p", { class: "empty" }, empty));
}

export function mount(main, { domain }) {
  if (!domain) { notFound(main, null); return null; }
  const body = h("div", { class: "stack" }, banner("loading", {}, "Loading evidence…"));
  const reader = createReader(() => request("GET", `/dossiers/${domain}`), (result) => {
    if (result.outcome === "refused" && (result.status === 404 || result.status === 422)) {
      notFound(main, domain);
      return;
    }
    if (result.outcome !== "ok") {
      replace(body, banner("error", {}, "The evidence could not be loaded. ",
        h("button", { type: "button", class: "button button--quiet",
                      onclick: () => reader.read() }, "Try again")));
      return;
    }
    const d = result.data;
    replace(body,
      d.state === "building" && banner("info", {},
        "A new research run is in progress; this shows the last completed results."),
      FIELDS.map((name) => section(name, d.fields[name])),
      d.fields[EXECUTIVES] && extraSection(EXECUTIVES, EXECUTIVES_LABEL, d.fields[EXECUTIVES],
                                           "No source names a CFO, COO or CTO."),
      d.fields[INVESTORS] && extraSection(INVESTORS, INVESTORS_LABEL, d.fields[INVESTORS],
                                          "No source names an investor."));
  });
  main.append(
    h("section", { class: "stack" },
      h("p", { class: "small" }, h("a", { href: `/dossiers/${domain}`, "data-link": "" },
        `← Back to ${domain}`)),
      h("h1", { class: "wrap" }, `Evidence for ${domain}`),
      h("p", { class: "muted" }, "Every value a source supports, best-ranked first: company " +
        "sites and filings, then news, then data aggregators; newer before older.")),
    body);
  reader.read();
  return null;
}
