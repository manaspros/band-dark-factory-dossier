// Reading a resource where the latest read wins (stage-2 "Refresh and competing clients").
//
// Every read gets a sequence number when it is issued. A response is applied only if no
// later read has been applied already, so a slow earlier response can never overwrite a
// newer one, whatever order responses arrive in.

export function createReader(fetchResource, apply) {
  let issued = 0;
  let applied = 0;
  return {
    async read() {
      const seq = ++issued;
      const result = await fetchResource();
      if (seq <= applied) return false;
      applied = seq;
      apply(result);
      return true;
    },
  };
}

// Poll with `reader.read` every `ms` while `active()` says so; stop() ends it.
export function createPoller(reader, ms) {
  let timer = null;
  return {
    ensure(active) {
      if (active && timer === null) timer = setInterval(() => reader.read(), ms);
      if (!active) this.stop();
    },
    stop() {
      if (timer !== null) clearInterval(timer);
      timer = null;
    },
  };
}
