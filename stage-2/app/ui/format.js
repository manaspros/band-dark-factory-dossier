// Formatting for people: field labels, values, dates, sources (stage-2 product direction).

export const FIELDS = ["legal_name", "hq_city", "ceo", "founded_year", "headcount_range",
                       "funding_total"];

export const FIELD_LABELS = {
  legal_name: "Legal name", hq_city: "Headquarters", ceo: "Chief executive",
  founded_year: "Founded", headcount_range: "Employees", funding_total: "Total funding",
};

const KIND_LABELS = {
  own: "Company site", filing: "Filing registry", news: "News report",
  aggregator: "Data aggregator",
};
const PROVIDER_LABELS = { nimble: "Nimble", tavily: "Tavily", kernel: "Kernel",
                          browserbase: "Browserbase" };

const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD",
                                               maximumFractionDigits: 0 });
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });
const grouped = new Intl.NumberFormat("en-US");
const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const dateOnly = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });

// The API value exactly as text, for data-value.
export function rawValue(value) {
  return value === null || value === undefined ? "" : String(value);
}

export function formatValue(field, value) {
  if (value === null || value === undefined) return "";
  if (field === "founded_year") return String(value);
  if (field === "funding_total") {
    return `US${money.format(value)}${value >= 1e6 ? ` (≈ $${compact.format(value)})` : ""}`;
  }
  if (field === "headcount_range") {
    const [low, high] = String(value).split("-");
    if (value.endsWith("+")) return `${grouped.format(Number(value.slice(0, -1)))}+ employees`;
    return `${grouped.format(Number(low))}–${grouped.format(Number(high))} employees`;
  }
  return String(value);
}

// The formatted value, and the API value when the formatted text does not contain it
// (screens add it as hidden text so the page text still holds the value itself).
export function valueParts(field, value) {
  const shown = formatValue(field, value);
  const raw = rawValue(value);
  return { shown, raw: shown.includes(raw) ? null : raw };
}

export function formatDateTime(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : dateTime.format(d);
}

export function formatDate(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : dateOnly.format(d);
}

export function kindLabel(kind) {
  return kind ? (KIND_LABELS[kind] || kind) : "Unknown source type (imported)";
}

export function providerLabel(provider) {
  return PROVIDER_LABELS[provider] || provider;
}

export function hostOf(url) {
  try { return new URL(url).host; } catch { return url; }
}

export function units(n) {
  return `${grouped.format(n)} ${n === 1 ? "unit" : "units"}`;
}

export const STATUS_LABELS = { known: "Known", unknown: "Unknown", contested: "Contested" };
export const STATE_LABELS = { building: "Building", ready: "Ready", failed: "Failed" };

// §4 domain normalisation, as the server does it: null when not a valid host name.
export function normaliseDomain(raw) {
  let d = String(raw).trim().toLowerCase();
  if (d.endsWith(".")) d = d.slice(0, -1);
  if (d.startsWith("www.")) d = d.slice(4);
  if (d.length > 253) return null;
  const labels = d.split(".");
  if (labels.length < 2) return null;
  const ok = labels.every((l) => /^[a-z0-9-]{1,63}$/.test(l) && !l.startsWith("-") && !l.endsWith("-"));
  return ok ? d : null;
}
