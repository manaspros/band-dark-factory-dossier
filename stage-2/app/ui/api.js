// The JSON API from the browser: the signed-in session, and every request's outcome.
//
// Outcomes (plan E11): "ok" (2xx), "refused" (4xx: the server answered and said no) and
// "uncertain" (no answer: network failure, a 15 s timeout, or a 5xx). An uncertain write
// may or may not have taken effect, so it is never shown as a refusal.

const SESSION_KEY = "dossier.session";
const TIMEOUT_MS = 15000;

export function session() {
  try { return JSON.parse(localStorage.getItem(SESSION_KEY)); } catch { return null; }
}

export function signIn(body) {
  localStorage.setItem(SESSION_KEY, JSON.stringify(
    { token: body.token, user_id: body.user_id, display_name: body.display_name }));
}

export function signOut() {
  localStorage.removeItem(SESSION_KEY);
}

let onUnauthenticated = () => {};
export function whenUnauthenticated(handler) { onUnauthenticated = handler; }

export async function request(method, path, { body, key, auth = true } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (key) headers["Idempotency-Key"] = key;
  const current = session();
  if (auth && current) headers.Authorization = `Bearer ${current.token}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  let response;
  try {
    response = await fetch(path, { method, headers, signal: controller.signal,
                                    body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    return { outcome: "uncertain", status: 0, data: null, message: "No answer from the service." };
  } finally {
    clearTimeout(timer);
  }
  let data = null;
  try { data = await response.json(); } catch { data = null; }
  if (response.ok) return { outcome: "ok", status: response.status, data };
  if (response.status >= 500) {
    return { outcome: "uncertain", status: response.status, data,
             message: "The service did not confirm the result." };
  }
  if (response.status === 401 && auth) onUnauthenticated();
  return { outcome: "refused", status: response.status, data,
           code: data?.error?.code, message: data?.error?.message || "The request was refused." };
}
