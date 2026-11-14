# Builder notes — stage 1 toolchain (dossier)

Source inspected: `webrouter-0.12.0-py3-none-any.whl` and `nimble-python` (latest <2) downloaded
with `pip download --no-deps` and read as source; nothing installed. The harness venv
(`sf-buildathon-2026/.venv`) does NOT contain `web_router` — the service image must install it.

## Environment

- Docker: running, server 29.1.3.
- `webrouter` 0.12.0 needs Python >= 3.11. Base image: `python:3.12-slim` (or alpine; slim avoids
  musl wheel issues for pydantic-core).
- Install in the Dockerfile exactly as the spec says:
  `pip install "webrouter[search,extract,research]>=0.12.0"` (pulls `nimble-python`,
  `tavily-python`, `httpx`, `pydantic`). Dependency manifest must list `webrouter>=0.12.0`.
- No outbound network at runtime except provider endpoints: vendor everything at build time.

## Public API (module `web_router`)

```python
from web_router import AsyncWebRouter, WebRouter, ProviderError, WebRouterError, ResearchTimeoutError

AsyncWebRouter(provider="auto", *, provider_config: dict[str, dict] | None = None, ...)
# use: async with AsyncWebRouter("nimble", provider_config=...) as router: ...

await router.search(query, *, provider=None, max_results=None, search_depth=None,  # "lite"|"fast"|"deep"
                    include_domains=None, exclude_domains=None, country=None, locale=None,
                    recency=None, effort=None, provider_options=None, budget=None) -> SearchResponse
await router.extract(urls: str | list[str], *, provider=None, format=None,  # "markdown"|"html"|"text"
                     profile=None, provider_options=None, budget=None) -> ExtractResponse
await router.research(query, *, provider=None, output_schema: dict | None = None, records=None,
                      effort=None, include_domains=None, exclude_domains=None,
                      timeout: float | None = 600.0, provider_options=None, budget=None) -> ResearchResponse
await router.submit_research(...same args...) -> ResearchJob   # job.aresult(timeout=...) to wait
```

Response types (pydantic, `extra="forbid"`):

- `SearchResponse(provider, query, results: list[SearchResult], answer, request_id, raw)`;
  `SearchResult(url, title, description, content, score, published_date, extra)`.
  `content` = page body when returned, else `description`.
- `ExtractResponse(provider, documents: list[ExtractedDocument], failures: list[ExtractFailure], request_id, raw)`;
  `ExtractedDocument(url, title, content, format, status_code, ...)`; `ExtractFailure(url, error)`.
  **A call where nothing came back raises `ProviderError`** instead of returning an empty response.
- `ResearchResponse(provider, query, answer, structured: dict | list | None, citations: list[Citation], ...)`;
  `Citation(url, title, snippet, field, extra)`. Nimble sets `field` to the JSON path
  (`"$.legal_name"`) and `snippet` to the first excerpt; all excerpts are in `extra["excerpts"]`.
  Uncited bibliography sources follow with `field=None`, `snippet=""` — ignore those.

## Provider config and env

- `WebRouter`'s default provider is **`auto`**, not `nimble`. Always construct with `"nimble"` or pass
  `provider="nimble"` per call, otherwise `auto` may route to another backend.
- Naming a provider explicitly uses that provider only (no fallback chain; chains are `auto`-only).
- `NIMBLE_API_KEY`: read by WebRouter (`resolve_api_key`); missing key -> `ConfigurationError` at
  provider construction (first call), not at router construction.
- `NIMBLE_BASE_URL`: **not read by WebRouter** — `nimble-python`'s `Nimble`/`AsyncNimble`
  constructor does `os.environ.get("NIMBLE_BASE_URL")`, falling back to `https://sdk.nimbleway.com`
  only when unset. An **empty** value counts as set and breaks every call. Do not pass `base_url`
  ourselves; leave the env to the SDK. Treat "unset or host `sdk.nimbleway.com`" as live (§8 slow-provider
  timing rules).
- Tavily (optional): `TAVILY_API_KEY` read from env; base URL must be passed:
  `provider_config={"tavily": {"api_base_url": os.environ["TAVILY_BASE_URL"]}}`.
- Extra keys in `provider_config["nimble"]` are passed to the SDK client constructor
  (`timeout`, `max_retries`, ...).

## Depth mapping and cost (nimble)

| WebRouter `search_depth` | Nimble request | Mock returns per result | Units |
|---|---|---|---|
| `lite` | `search_depth=lite` | first 300 chars of the page's **prose** (snippet) | 1 |
| `fast` | `search_depth=standard` | first 1500 chars of the **served text (includes header lines)** | 5 |
| `deep` | `standard` + `full_content=True` | whole served text | 15 |

- Extract (nimble): 1 unit per URL requested, also for URLs with no page. WebRouter fans a URL
  list out as one SDK call per URL, concurrently. Do not set `render` (spec §9).
- Nimble extract default format is `html`; pass `format="markdown"` (supported: markdown, html).
  The mock serves the page's served text in that field.
- Nimble extract answers HTTP 200 with `status != "success"` for a missing page -> becomes an
  `ExtractFailure` (still costs 1).
- Research (nimble): 25 units when the run is created; polls free. Mock completes on first poll.
  Query must contain the normalised domain; `output_schema` properties = the six field names.
- Search returns at most 10 results (Nimble default 10).

## Gotchas that affect correctness

1. **SDK retries vs budget.** `nimble-python` defaults to `max_retries=2`, timeout 180 s
   (connect 5 s). A timed-out/connection-failed call costs its units; a retried timeout costs
   again, invisibly. Set `provider_config={"nimble": {"max_retries": 0, "timeout": <s>}}` and do
   retry + unit accounting ourselves, reserving units before each attempt.
2. **Cost classification of failures.** `ProviderError.original` holds the SDK exception:
   `nimble_python.APIStatusError` (has `status_code`, refused -> 0 units) vs
   `APITimeoutError` / `APIConnectionError` (no answer -> full units). 429/500 from the mock cost 0.
3. **Header lines.** Served text = header lines (`Name: value`), one empty line, then prose. Strip
   the header before sentence splitting; citations must come from prose only. `Facts:` is
   informative only. `fast` depth includes the header in its 1500 chars; `lite` is prose-only.
4. **Research citations are served text** (mock logs them as `served`) but must still pass the
   Appendix A rule; a research claim whose excerpt does not support its value is dropped.
   Research may cite non-searchable pages.
5. **Exactly one search with query == normalised domain** per build (counting only non-error
   answers); every other search must use a different query. Track this per build.
6. The mock is deterministic and BM25-ranked; a query containing the domain ranks that company's
   pages first.
7. Async router owns HTTP clients: create once per process (or per build) and `aclose()` it;
   the sync `research()` blocks — never call it on a request thread.
8. Mock routes for nimble live under `<NIMBLE_BASE_URL>/v2/...`; local runs use
   `NIMBLE_BASE_URL=http://web:8080/nimble` (see `sf-buildathon-2026/challenges/dossier/web/README.md`).
