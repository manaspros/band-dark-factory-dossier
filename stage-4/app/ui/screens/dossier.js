// `/dossiers/{domain}`: one dossier, its six fields with value, status and citations, and
// (stage 3) its executives and (stage 4) its investors, shown with their own markup and no
// data-testid. Each field also says how many independent sources stand behind it.
//
// The latest read always wins (reader.js). While the dossier is building, it is read again
// every 1.5 s until it is ready or failed.

import { request } from "../api.js";
import { banner, chip, h, replace } from "../dom.js";
import { EXECUTIVES, EXECUTIVES_LABEL, EXTRA_FIELDS, FIELDS, FIELD_LABELS, INVESTORS,
         INVESTORS_LABEL, STATE_LABELS, STATUS_LABELS, TITLE_LABELS, formatDateTime, hostOf,
         providerLabel, rawValue, sourcesNote, units, valueParts } from "../format.js";
import { createPoller, createReader } from "../reader.js";
import { submitWrite } from "../writes.js";

const POLL_MS = 1500;

export function valueNode(field, value, attrs = {}) {
  const { shown, raw } = valueParts(field, value);
  return h("span", { "data-value": rawValue(value), ...attrs }, shown,
    raw && h("span", { class: "visually-hidden", "aria-hidden": "true" }, ` ${raw}`));
}

export function notFound(main, domain) {
  replace(main, h("section", { class: "empty", testid: "dossier-not-found" },
    h("h1", {}, "No dossier for this domain"),
    h("p", {}, domain ? `Nobody has researched ${domain} yet.`
      : "This address does not name a valid domain."),
    h("p", {}, h("a", { href: "/", "data-link": "" }, "Research it from the dossier list"))));
}

function citation(field, c, n) {
  return h("li", { class: "citation",
                   testid: EXTRA_FIELDS.includes(field) ? null : `citation-${field}-${n}`,
                   "data-provider": c.provider },
    h("blockquote", {}, c.excerpt),
    h("p", { class: "source" },
      h("a", { href: c.url, rel: "noopener noreferrer", target: "_blank" }, hostOf(c.url)),
      h("span", {}, `via ${providerLabel(c.provider)}`)));
}

function fieldCard(name, field) {
  const known = field.value !== null && field.value !== undefined;
  const distinct = new Set(field.candidates.map((c) => JSON.stringify(c.value))).size;
  return h("article", { class: "field-card", testid: `field-${name}`, "data-status": field.status,
                        "aria-labelledby": `label-${name}` },
    h("div", { class: "field-card__head" },
      h("h2", { class: "field-card__label", id: `label-${name}` }, FIELD_LABELS[name]),
      chip(field.status, STATUS_LABELS[field.status])),
    known
      ? valueNode(name, field.value, { class: "field-card__value",
                                       testid: `field-value-${name}` })
      : h("p", { class: "field-card__value field-card__value--none" },
          "No source states this yet."),
    field.status === "contested" && h("p", { class: "contested-note",
                                             testid: `field-contested-${name}` },
      `Sources disagree: ${distinct} different values. Showing the best-ranked source.`),
    sourcesNote(field) && h("p", { class: "muted small" }, sourcesNote(field)),
    h("ol", { class: "citations", testid: `field-citations-${name}`,
              "aria-label": `Sources for ${FIELD_LABELS[name]}` },
      field.citations.map((c, i) => citation(name, c, i + 1))));
}

function executivesCard(field) {
  const members = field.value || [];
  const contested = new Set(field.candidates.filter((c) =>
    field.candidates.some((o) => o.title === c.title && o.value !== c.value)).map((c) => c.title));
  return h("article", { class: "field-card", "data-section": EXECUTIVES,
                        "data-status": field.status, "aria-labelledby": "label-executives" },
    h("div", { class: "field-card__head" },
      h("h2", { class: "field-card__label", id: "label-executives" }, EXECUTIVES_LABEL),
      chip(field.status, STATUS_LABELS[field.status])),
    members.length
      ? h("dl", { class: "members" }, members.map((m) => [
          h("dt", {}, TITLE_LABELS[m.title] || m.title),
          h("dd", { "data-title": m.title, "data-value": m.name }, m.name,
            contested.has(m.title) && h("span", { class: "contested-note" },
              " (sources disagree; best-ranked shown)"))]))
      : h("p", { class: "field-card__value field-card__value--none" },
          "No source names a CFO, COO or CTO yet."),
    h("ol", { class: "citations", "aria-label": `Sources for ${EXECUTIVES_LABEL}` },
      field.citations.map((c, i) => citation(EXECUTIVES, c, i + 1))));
}

function investorsCard(field) {
  const names = field.value || [];
  return h("article", { class: "field-card", "data-section": INVESTORS,
                        "data-status": field.status, "aria-labelledby": "label-investors" },
    h("div", { class: "field-card__head" },
      h("h2", { class: "field-card__label", id: "label-investors" }, INVESTORS_LABEL),
      chip(field.status, STATUS_LABELS[field.status])),
    names.length
      ? h("ul", { class: "members-list" },
          names.map((name) => h("li", { "data-value": name }, name)))
      : h("p", { class: "field-card__value field-card__value--none" },
          "No investor is confirmed by the company, a filing or two independent sources yet."),
    sourcesNote(field) && h("p", { class: "muted small" }, sourcesNote(field)),
    h("ol", { class: "citations", "aria-label": `Sources for ${INVESTORS_LABEL}` },
      field.citations.map((c, i) => citation(INVESTORS, c, i + 1))));
}

export function mount(main, { domain }) {
  if (!domain) { notFound(main, null); return null; }
  const actions = h("div", { class: "row" });
  const feedback = h("div", { "aria-live": "polite" });
  const head = h("div", { class: "dossier-head" });
  const body = h("div", { class: "stack" }, banner("loading", {}, "Loading dossier…"));
  let shown = null;

  const reader = createReader(() => request("GET", `/dossiers/${domain}`), apply);
  const poller = createPoller(reader, POLL_MS);

  function apply(result) {
    if (result.outcome === "refused" && (result.status === 404 || result.status === 422)) {
      poller.stop();
      notFound(main, domain);
      return;
    }
    if (result.outcome !== "ok") {
      if (!shown) {
        replace(body, banner("error", {}, "The dossier could not be loaded. ",
          h("button", { type: "button", class: "button button--quiet",
                        onclick: () => reader.read() }, "Try again")));
      }
      return;
    }
    shown = result.data;
    render(shown);
    poller.ensure(shown.state === "building");
  }

  function render(d) {
    replace(head,
      h("div", { class: "row" },
        h("h1", { testid: "dossier-domain" }, d.domain),
        h("span", { class: `chip chip--${d.state}` },
          h("span", { class: "icon", "aria-hidden": "true" },
            { building: "↻", ready: "✓", failed: "✕" }[d.state]),
          h("span", { testid: "dossier-state" }, d.state))),
      h("p", { class: "facts" },
        h("span", {}, "Spent ", h("strong", { testid: "dossier-spent", "data-units": d.spent_units },
          units(d.spent_units))),
        d.researched_at && h("span", {}, "Researched ",
          h("strong", { testid: "dossier-researched-at" },
            h("time", { datetime: d.researched_at }, formatDateTime(d.researched_at)))),
        !d.researched_at && h("span", {}, "Not researched successfully yet")));
    const status = {
      building: banner("loading", {}, "Research in progress. This page updates by itself."),
      failed: banner("error", {}, "The latest research could not reach any source. " +
        (d.researched_at ? "Showing the last successful results." : "Try refreshing.")),
    }[d.state];
    replace(body, status || null, h("div", { class: "fields" },
      FIELDS.map((name) => fieldCard(name, d.fields[name])),
      d.fields[EXECUTIVES] && executivesCard(d.fields[EXECUTIVES]),
      d.fields[INVESTORS] && investorsCard(d.fields[INVESTORS])));
  }

  const refreshButton = h("button", { type: "button", class: "button button--primary",
                                      testid: "dossier-refresh", onclick: refresh }, "Refresh");

  async function refresh() {
    refreshButton.disabled = true;
    feedback.replaceChildren(banner("loading", {}, "Starting a new research run…"));
    const result = await submitWrite(request, "POST", `/dossiers/${domain}/refresh`, undefined);
    refreshButton.disabled = false;
    if (result.outcome === "ok") {
      feedback.replaceChildren(banner("success", {}, "Research started. Results appear here when it finishes."));
      await reader.read();
    } else if (result.outcome === "refused") {
      feedback.replaceChildren(banner("error", { testid: "refresh-error" },
        result.status === 404 ? "This dossier no longer exists." : result.message));
    } else {
      feedback.replaceChildren(banner("uncertain", { testid: "refresh-uncertain" },
        "We could not confirm whether the refresh started. Retrying is safe: it will not " +
        "start a second build.",
        h("button", { type: "button", class: "button button--secondary", onclick: refresh },
          "Retry")));
    }
  }

  replace(actions, refreshButton,
    h("button", { type: "button", class: "button button--secondary", testid: "dossier-reload",
                  onclick: () => reader.read() }, "Reload"),
    h("a", { class: "button button--quiet", href: `/dossiers/${domain}/evidence`, "data-link": "",
             testid: "dossier-evidence-link" }, "All evidence"));
  main.append(h("section", { class: "stack", "aria-label": `Dossier for ${domain}` },
    head, actions, feedback), body);
  reader.read();
  return () => poller.stop();
}
