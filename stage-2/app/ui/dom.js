// A tiny DOM builder: h("a", {href, testid: "x"}, "text", child) creates elements.
// `testid` becomes data-testid; `on<Event>` attributes become listeners; null/false
// attributes and children are skipped, so conditional parts read naturally.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (name === "testid") el.dataset.testid = value;
    else if (name === "class") el.className = value;
    else if (name.startsWith("on") && typeof value === "function") {
      el.addEventListener(name.slice(2).toLowerCase(), value);
    } else if (name === "dataset") Object.assign(el.dataset, value);
    else el.setAttribute(name, value === true ? "" : String(value));
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : String(child));
  }
}

export function replace(el, ...children) {
  el.replaceChildren();
  append(el, children);
}

// A state chip: icon + word, so a state never depends on colour alone.
const ICONS = {
  known: "✓", ready: "✓", unknown: "?", contested: "⚑", building: "↻", failed: "✕",
};
export function chip(state, label = state, attrs = {}) {
  return h("span", { class: `chip chip--${state}`, ...attrs },
    h("span", { class: "icon", "aria-hidden": "true" }, ICONS[state] || "•"), label);
}

// Banners for loading, success, refusal (error), uncertainty and plain information.
const BANNER_ICONS = { loading: "…", success: "✓", error: "✕", uncertain: "?", info: "i" };
export function banner(kind, attrs, ...children) {
  return h("div", { class: `banner banner--${kind}`,
                    role: kind === "error" ? "alert" : "status", ...attrs },
    h("span", { class: "icon", "aria-hidden": "true" }, BANNER_ICONS[kind]), ...children);
}
