// Writes whose outcome may be unknown (stage-2 "Refresh and competing clients").
//
// Each pending write is keyed by (method, path, body) and keeps its Idempotency-Key until
// it is settled. A retry of an uncertain write sends the same key and body, so the server
// replays the original response instead of acting twice. A refusal or a success settles
// the write; the next attempt with the same body gets a new key.

const pending = new Map();

function slot(method, path, body) {
  return JSON.stringify([method, path, body ?? null]);
}

function newKey() {
  return crypto.randomUUID ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

export async function submitWrite(request, method, path, body) {
  const id = slot(method, path, body);
  let key = pending.get(id);
  if (!key) {
    key = newKey();
    pending.set(id, key);
  }
  const result = await request(method, path, { body, key });
  if (result.outcome !== "uncertain") pending.delete(id);
  return result;
}
