// The single-page app: routes, the shared header, and navigation between screens.
//
// Each screen module exports mount(main, params, ctx) and may return a cleanup function
// (to stop polling) that runs when the screen is left.

import { session, signOut, whenUnauthenticated } from "./api.js";
import { h, replace } from "./dom.js";
import { normaliseDomain } from "./format.js";
import * as auth from "./screens/auth.js";
import * as contested from "./screens/contested.js";
import * as dossier from "./screens/dossier.js";
import * as evidence from "./screens/evidence.js";
import * as list from "./screens/list.js";

const ROUTES = [
  { pattern: /^\/$/, screen: list, title: "Dossiers", signedIn: true, nav: "/" },
  { pattern: /^\/contested$/, screen: contested, title: "Contested fields", signedIn: true,
    nav: "/contested" },
  { pattern: /^\/signup$/, screen: auth, mode: "signup", title: "Sign up", signedIn: false },
  { pattern: /^\/login$/, screen: auth, mode: "login", title: "Sign in", signedIn: false },
  { pattern: /^\/dossiers\/(.+)\/evidence$/, screen: evidence, title: "Evidence", signedIn: true,
    domainRoute: (d) => `/dossiers/${d}/evidence` },
  { pattern: /^\/dossiers\/(.+)$/, screen: dossier, title: "Dossier", signedIn: true,
    domainRoute: (d) => `/dossiers/${d}` },
];

let cleanup = null;

export function navigate(path, { replace: replaceEntry = false } = {}) {
  if (replaceEntry) history.replaceState(null, "", path);
  else history.pushState(null, "", path);
  render();
}

function renderHeader(route) {
  const user = session();
  const link = (href, text) => h("a", {
    href, "data-link": "", "aria-current": route?.nav === href ? "page" : null }, text);
  replace(document.getElementById("site-header"), h("div", { class: "site-header__inner" },
    h("a", { class: "brand", href: "/", "data-link": "" },
      h("span", { class: "brand__mark", "aria-hidden": "true" }, "D"), "Dossier"),
    user
      ? [h("nav", { class: "nav", "aria-label": "Main" },
           link("/", "Dossiers"), link("/contested", "Contested")),
         h("div", { class: "user" },
           h("span", { testid: "current-user", class: "muted small" }, "Signed in as ",
             h("strong", {}, user.display_name)),
           h("button", { type: "button", class: "button button--quiet", testid: "logout-button",
                         onclick: () => { signOut(); navigate("/login"); } }, "Sign out"))]
      : h("nav", { class: "nav", "aria-label": "Account" },
          link("/login", "Sign in"), link("/signup", "Sign up"))));
}

function render() {
  if (cleanup) { cleanup(); cleanup = null; }
  const path = decodeURIComponent(location.pathname);
  const route = ROUTES.find((r) => r.pattern.test(path));
  const main = document.getElementById("main");
  if (!route) {
    renderHeader(null);
    document.title = "Not found · Dossier";
    replace(main, h("div", { class: "empty" }, h("h1", {}, "Page not found"),
      h("p", {}, h("a", { href: "/", "data-link": "" }, "Back to the dossiers"))));
    return;
  }
  if (route.signedIn && !session()) { navigate("/login", { replace: true }); return; }
  const params = { mode: route.mode };
  if (route.domainRoute) {
    const raw = path.match(route.pattern)[1];
    params.domain = normaliseDomain(raw);
    params.rawDomain = raw;
    if (params.domain && params.domain !== raw) {
      history.replaceState(null, "", route.domainRoute(params.domain));
    }
  }
  renderHeader(route);
  document.title = `${route.title} · Dossier`;
  main.replaceChildren();
  cleanup = route.screen.mount(main, params, { navigate }) || null;
}

document.addEventListener("click", (event) => {
  const anchor = event.target.closest("a[data-link]");
  if (!anchor || event.defaultPrevented || event.button !== 0 || event.metaKey
      || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  navigate(anchor.getAttribute("href"));
});
window.addEventListener("popstate", render);
whenUnauthenticated(() => { signOut(); navigate("/login", { replace: true }); });
render();
