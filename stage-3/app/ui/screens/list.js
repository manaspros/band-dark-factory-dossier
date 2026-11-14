// `/`: research a domain, and the list of dossiers with search.

import { request } from "../api.js";
import { banner, chip, h, replace } from "../dom.js";
import { STATE_LABELS } from "../format.js";
import { createReader } from "../reader.js";
import { submitWrite } from "../writes.js";

const PAGE = 200;
const SEARCH_DELAY_MS = 250;

export async function listAll(q = "") {
  const dossiers = [];
  for (let offset = 0; ; offset += PAGE) {
    const params = new URLSearchParams({ limit: PAGE, offset });
    if (q) params.set("q", q);
    const result = await request("GET", `/dossiers?${params}`);
    if (result.outcome !== "ok") return result;
    dossiers.push(...result.data.dossiers);
    if (!result.data.has_more) return { outcome: "ok", data: dossiers };
  }
}

export function mount(main, _params, { navigate }) {
  const domainInput = h("input", { id: "research-domain", type: "text", testid: "research-domain",
                                   placeholder: "acme-robotics.com", autocomplete: "off",
                                   inputmode: "url", "aria-describedby": "research-help" });
  const submit = h("button", { type: "submit", class: "button button--primary",
                               testid: "research-submit" }, "Research");
  const feedback = h("div", { "aria-live": "polite" });
  const searchInput = h("input", { id: "dossier-search", type: "search", testid: "dossier-search",
                                   placeholder: "Domain or legal name", autocomplete: "off" });
  const results = h("div", { class: "stack", "aria-live": "polite" },
    banner("loading", {}, "Loading dossiers…"));

  async function research(event) {
    event?.preventDefault();
    const body = { domain: domainInput.value };
    submit.disabled = true;
    feedback.replaceChildren(banner("loading", {}, "Sending your request…"));
    const result = await submitWrite(request, "POST", "/dossiers", body);
    submit.disabled = false;
    if (result.outcome === "ok") {
      feedback.replaceChildren();
      navigate(`/dossiers/${result.data.domain}`);
    } else if (result.outcome === "refused") {
      feedback.replaceChildren(banner("error", { testid: "research-error" },
        result.status === 422
          ? "That is not a domain we can research. Enter a host name such as acme-robotics.com."
          : result.message));
    } else {
      feedback.replaceChildren(banner("uncertain", { testid: "research-uncertain" },
        "We could not confirm whether your request was received. Retrying is safe: it will " +
        "not start a second build.",
        h("button", { type: "button", class: "button button--secondary", onclick: research },
          "Retry")));
    }
  }

  const reader = createReader(() => listAll(searchInput.value), (result) => {
    if (result.outcome !== "ok") {
      replace(results, banner("error", {}, "The dossiers could not be loaded. ",
        h("button", { type: "button", class: "button button--quiet",
                      onclick: () => reader.read() }, "Try again")));
      return;
    }
    if (result.data.length === 0) {
      replace(results, h("div", { class: "empty", testid: "empty-dossiers" },
        searchInput.value ? `No dossier matches “${searchInput.value}”.`
          : "No dossiers yet. Research a domain above to create the first one."));
      return;
    }
    replace(results, h("ul", { class: "list", testid: "dossier-list" },
      result.data.map((d) => h("li", {},
        h("a", { class: "list-item", href: `/dossiers/${d.domain}`, "data-link": "",
                 testid: `dossier-item-${d.domain}`, "data-state": d.state },
          h("span", { class: "list-item__main" },
            h("span", { class: "list-item__title" }, d.domain),
            h("span", { class: "muted small wrap" }, d.legal_name ?? "Legal name not known yet")),
          chip(d.state, STATE_LABELS[d.state] || d.state))))));
  });

  let searchTimer = null;
  searchInput.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => reader.read(), SEARCH_DELAY_MS);
  });

  main.append(
    h("section", { class: "panel", "aria-labelledby": "research-title" },
      h("div", { class: "stack" },
        h("h1", { id: "research-title" }, "Research a company"),
        h("p", { class: "muted", id: "research-help" },
          "Enter a company's web domain. Dossier gathers its legal name, headquarters, chief " +
          "executive, founding year, headcount and funding, each with the sources that state it.")),
      h("form", { class: "form-row", onsubmit: research },
        h("div", { class: "field-control" },
          h("label", { for: "research-domain" }, "Company domain"), domainInput),
        submit),
      feedback),
    h("section", { class: "stack", "aria-labelledby": "list-title" },
      h("div", { class: "row" }, h("h2", { id: "list-title" }, "Dossiers")),
      h("div", { class: "field-control" },
        h("label", { for: "dossier-search" }, "Search dossiers"), searchInput),
      results));
  reader.read();
  return () => clearTimeout(searchTimer);
}
