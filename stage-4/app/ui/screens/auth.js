// Sign up and sign in.

import { request, signIn } from "../api.js";
import { banner, h } from "../dom.js";

const FORMS = {
  signup: {
    title: "Create your account", submit: "Sign up", path: "/auth/signup", prefix: "signup",
    inputs: [["email", "Email", "email", "email"], ["display_name", "Display name", "text", "name"],
             ["password", "Password (8 characters or more)", "password", "new-password"]],
    other: ["Already have an account?", "/login", "Sign in"],
  },
  login: {
    title: "Sign in", submit: "Sign in", path: "/auth/login", prefix: "login",
    inputs: [["email", "Email", "email", "email"], ["password", "Password", "password",
                                                    "current-password"]],
    other: ["New here?", "/signup", "Create an account"],
  },
};

const TESTIDS = { display_name: "display-name" };

export function mount(main, { mode }, { navigate }) {
  const form = FORMS[mode];
  const errorSlot = h("div");
  const button = h("button", { type: "submit", class: "button button--primary",
                               testid: `${form.prefix}-submit` }, form.submit);
  const inputs = Object.fromEntries(form.inputs.map(([name, , type, autocomplete]) => [name,
    h("input", { id: `${form.prefix}-${name}`, name, type, autocomplete, required: true,
                 testid: `${form.prefix}-${TESTIDS[name] || name}` })]));

  async function submit(event) {
    event.preventDefault();
    button.disabled = true;
    errorSlot.replaceChildren(banner("loading", {}, "Checking…"));
    const body = Object.fromEntries(Object.entries(inputs).map(([k, el]) => [k, el.value]));
    const result = await request("POST", form.path, { body, auth: false });
    button.disabled = false;
    if (result.outcome === "ok") {
      signIn(result.data);
      navigate("/");
      return;
    }
    const message = result.outcome === "uncertain"
      ? "No answer from the service. Please try again."
      : friendly(result);
    errorSlot.replaceChildren(banner("error", { testid: "auth-error" }, message));
  }

  main.append(h("section", { class: "panel narrow", "aria-labelledby": "auth-title" },
    h("h1", { id: "auth-title" }, form.title),
    h("form", { class: "stack", onsubmit: submit, novalidate: true },
      form.inputs.map(([name, label]) => h("div", { class: "field-control" },
        h("label", { for: `${form.prefix}-${name}` }, label), inputs[name])),
      errorSlot, button),
    h("p", { class: "muted small" }, form.other[0], " ",
      h("a", { href: form.other[1], "data-link": "" }, form.other[2]))));
  inputs.email.focus();
}

function friendly(result) {
  if (result.status === 401) return "That email and password do not match an account.";
  if (result.code === "email_taken") return "An account with that email already exists.";
  return result.message;
}
