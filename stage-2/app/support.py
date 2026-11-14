"""Appendix A of the stage-1 spec: when an excerpt supports a value.

Pure functions, no I/O. Everything here follows the appendix literally:

- ``prose`` drops a page's header lines (§4 Pages).
- ``sentences`` splits prose into sentences (A.1).
- ``supports`` applies the five conditions of A.2 for one field and returns the
  normalised value (A.5), or ``None``.
- ``candidates`` runs ``supports`` over every citable sentence of a page.

All matching happens on the whitespace-collapsed excerpt, which is also the text
the service cites, so a value is always "written as the excerpt writes it".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterator

FIELDS = ("legal_name", "hq_city", "ceo", "founded_year", "headcount_range", "funding_total")

MAX_EXCERPT_CHARS = 500

# A.3 statement phrases, verbatim.
STATEMENT_PHRASES: dict[str, tuple[str, ...]] = {
    "legal_name": ("legal name", "registered name", "registered as", "registered company",
                   "legal entity", "name of record"),
    "hq_city": ("headquartered in", "headquarters in", "head office in", "based in",
                "registered office in", "registered seat in"),
    "ceo": ("chief executive officer", "chief executive", "CEO"),
    "founded_year": ("founded", "founding", "established", "incorporated"),
    "headcount_range": ("employs", "employees", "staff", "people", "headcount", "workforce"),
    "funding_total": ("raised", "funding", "invested", "investment"),
}

# A.3 negating phrases, verbatim.
NEGATING_PHRASES = ("in talks to", "plans to", "planning to", "wants to", "expects to",
                    "hopes to", "aims to", "seeking", "could", "would", "might", "reportedly",
                    "rumoured", "former", "formerly", "will become", "not")

# A.4 legal-form suffixes, matched exactly (case-sensitive) as written.
LEGAL_SUFFIXES = ("Inc.", "Corp.", "LLC", "LLP", "L.P.", "Ltd", "Limited", "Pty Ltd", "plc",
                  "PLC", "GmbH", "AG", "KG", "SE", "AS", "A/S", "ASA", "AB", "Oy", "Oyj",
                  "B.V.", "N.V.", "S.A.", "S.A.S.", "S.L.", "S.r.l.", "S.p.A.", "s.r.o.",
                  "a.s.", "K.K.")
_SUFFIXES_SHORTEST_FIRST = tuple(sorted(LEGAL_SUFFIXES, key=len))
_DOT_SUFFIXES = tuple(s for s in LEGAL_SUFFIXES if s.endswith("."))

# §4 headcount ranges as (low, high, label); high None means unbounded.
HEADCOUNT_RANGES = ((1, 10, "1-10"), (11, 50, "11-50"), (51, 200, "51-200"),
                    (201, 500, "201-500"), (501, 1000, "501-1000"), (1001, 5000, "1001-5000"),
                    (5001, 10000, "5001-10000"), (10001, None, "10001+"))

_SENTENCE_ENDS = ".!?"
_CLOSERS = "\"”’)"

# A.4 number: digits, optional `,` before each group of three, optional decimal part.
_NUMBER = r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?"
# A digit run joined by `,`/`.`; validated against _NUMBER_FULL afterwards.
_DIGIT_RUN = re.compile(r"[0-9]+(?:[.,][0-9]+)*")
_NUMBER_FULL = re.compile(rf"{_NUMBER}")
# "no letter or digit directly before/after": [^\W_] is a Unicode letter or digit.
_NOT_ALNUM_BEFORE = r"(?<![^\W_])"
_NOT_ALNUM_AFTER = r"(?![^\W_])"
# A number must not continue as part of a longer digit group (`1,20`, `1.2.3`).
_NUMBER_END = r"(?![.,][0-9])"
_NUMBER_START = r"(?<![0-9][.,])"
_AMOUNT = re.compile(
    rf"{_NOT_ALNUM_BEFORE}(?:"
    rf"(?P<cur>US\$|USD|\$) ?(?P<n1>{_NUMBER}){_NUMBER_END}"
    rf"(?:(?P<s1>mn|bn|k|m)| (?P<w1>thousand|million|billion))?"
    rf"|{_NUMBER_START}(?P<n2>{_NUMBER}){_NUMBER_END}(?: (?P<w2>thousand|million|billion))?"
    rf" (?:dollars|US dollars)"
    rf"){_NOT_ALNUM_AFTER}",
    re.IGNORECASE,
)
_SCALES = {"k": 1_000, "thousand": 1_000, "m": 1_000_000, "mn": 1_000_000,
           "million": 1_000_000, "bn": 1_000_000_000, "billion": 1_000_000_000}


# --------------------------------------------------------------------------- text basics

def collapse(text: str) -> str:
    """Write every run of whitespace as one space and strip the ends."""
    return " ".join(text.split())


def _fold(text: str) -> str:
    """Lowercase character by character, keeping indexes aligned with ``text``."""
    return "".join(c.lower() if len(c.lower()) == 1 else c for c in text)


def _is_alnum(c: str) -> bool:
    return c.isalpha() or c.isdigit()


def _whole_word_at(text: str, start: int, end: int) -> bool:
    before_ok = start == 0 or not _is_alnum(text[start - 1])
    after_ok = end >= len(text) or not _is_alnum(text[end])
    return before_ok and after_ok


def _find_phrase(folded: str, phrase: str) -> list[tuple[int, int]]:
    """Every whole-word, case-insensitive occurrence of ``phrase`` in ``folded``."""
    needle = _fold(phrase)
    spans, start = [], folded.find(needle)
    while start != -1:
        end = start + len(needle)
        if _whole_word_at(folded, start, end):
            spans.append((start, end))
        start = folded.find(needle, start + 1)
    return spans


def company_name(domain: str) -> str:
    """The company's name: the first label of its domain with each `-` read as a space."""
    return domain.split(".", 1)[0].replace("-", " ")


# --------------------------------------------------------------------------- pages (§4)

def _is_capitalised(token: str) -> bool:
    return len(token) >= 2 and token[0].isupper() and all(c.islower() for c in token[1:])


def _is_header_line(line: str) -> bool:
    """`Name: value`, the name one or more capitalised words joined by `-`."""
    colon = line.find(":")
    if colon <= 0:
        return False
    name, rest = line[:colon], line[colon + 1:]
    if rest and not rest.startswith(" "):
        return False
    return all(_is_capitalised(part) for part in name.split("-"))


def _lines(text: str) -> list[str]:
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def prose(text: str) -> str:
    """The page's prose: everything after the header, which ends at the first empty line.

    A text whose first line is not a header line has no header and is all prose; a text
    that starts with header lines and has no empty line has no prose.
    """
    lines = _lines(text)
    if not lines or not _is_header_line(lines[0]):
        return "\n".join(lines)
    for index, line in enumerate(lines):
        if line.strip() == "":
            return "\n".join(lines[index + 1:])
    return ""


# --------------------------------------------------------------------------- sentences (A.1)

def _ends_legal_suffix(line: str, dot_index: int) -> bool:
    """Whether the `.` at ``dot_index`` ends a legal-form suffix written as a whole word."""
    head = line[:dot_index + 1]
    for suffix in _DOT_SUFFIXES:
        if head.endswith(suffix):
            start = len(head) - len(suffix)
            if start == 0 or not _is_alnum(line[start - 1]):
                return True
    return False


def _split_line(line: str) -> list[str]:
    parts, start, i = [], 0, 0
    while i < len(line):
        if line[i] in _SENTENCE_ENDS:
            j = i + 1
            while j < len(line) and line[j] in _CLOSERS:
                j += 1
            if (j == len(line) or line[j].isspace()) and not (
                    line[i] == "." and _ends_legal_suffix(line, i)):
                parts.append(line[start:j])
                start, i = j, j
                continue
        i += 1
    parts.append(line[start:])
    return [p.strip() for p in parts if p.strip()]


def sentences(text: str) -> list[str]:
    """Split prose into sentences: per line, then at each sentence end (A.1)."""
    return [s for line in _lines(text) for s in _split_line(line)]


def is_single_sentence(excerpt: str) -> bool:
    return len(sentences(collapse(excerpt))) == 1


# --------------------------------------------------------------------------- tokens (A.4)

@dataclass(frozen=True)
class _Span:
    start: int
    end: int


def _letter_runs(text: str) -> Iterator[_Span]:
    i = 0
    while i < len(text):
        if text[i].isalpha():
            j = i
            while j < len(text) and text[j].isalpha():
                j += 1
            yield _Span(i, j)
            i = j
        else:
            i += 1


def _word_ok(text: str, span: _Span) -> bool:
    """No digit directly before or after (letters are excluded by maximal runs)."""
    before = span.start == 0 or not text[span.start - 1].isdigit()
    after = span.end >= len(text) or not text[span.end].isdigit()
    return before and after


def _capitalised_words(text: str) -> list[_Span]:
    return [s for s in _letter_runs(text)
            if _is_capitalised(text[s.start:s.end]) and _word_ok(text, s)]


def _uppercase_words(text: str) -> list[_Span]:
    return [s for s in _letter_runs(text)
            if s.end - s.start >= 2 and all(c.isupper() for c in text[s.start:s.end])
            and _word_ok(text, s)]


@dataclass(frozen=True)
class _Number:
    start: int
    end: int
    text: str

    @property
    def integral(self) -> bool:
        return "." not in self.text

    @property
    def value(self) -> Decimal:
        return Decimal(self.text.replace(",", ""))


def _numbers(text: str) -> list[_Number]:
    """Every A.4 number: a valid digit group not directly next to a letter."""
    found = []
    for match in _DIGIT_RUN.finditer(text):
        start, end = match.span()
        if start > 0 and text[start - 1].isalpha():
            continue
        if end < len(text) and text[end].isalpha():
            continue
        if _NUMBER_FULL.fullmatch(match.group()):
            found.append(_Number(start, end, match.group()))
    return found


@dataclass(frozen=True)
class _Amount:
    start: int
    end: int
    dollars: int | None  # None when it does not come to whole dollars


def _amounts(text: str) -> list[_Amount]:
    found = []
    for match in _AMOUNT.finditer(text):
        number = match.group("n1") or match.group("n2")
        scale_word = match.group("s1") or match.group("w1") or match.group("w2")
        scale = _SCALES[scale_word.lower()] if scale_word else 1
        try:
            dollars = Decimal(number.replace(",", "")) * scale
        except InvalidOperation:  # pragma: no cover - the pattern only admits digits
            continue
        whole = int(dollars) if dollars == dollars.to_integral_value() else None
        found.append(_Amount(match.start(), match.end(), whole))
    return found


def _outside(spans: list[_Amount], start: int, end: int) -> bool:
    return all(end <= a.start or start >= a.end for a in spans)


# --------------------------------------------------------------------------- values per field

def _name_spans(text: str, folded: str, domain: str) -> list[tuple[int, int]]:
    return _find_phrase(folded, company_name(domain)) + _find_phrase(folded, domain)


def _legal_names(text: str, folded: str, domain: str) -> set:
    values = set()
    words = {s.start: s.end for s in _capitalised_words(text) + _uppercase_words(text)}
    for start, end in _name_spans(text, folded, domain):
        pos = end
        while True:
            suffix_end = _suffix_after(text, pos)
            if suffix_end is not None:
                values.add(text[start:suffix_end])
                break
            if pos < len(text) and text[pos] == " " and (pos + 1) in words:
                pos = words[pos + 1]
                continue
            break
    return values


def _suffix_after(text: str, pos: int) -> int | None:
    """End of `[,] <suffix>` starting at ``pos``, shortest suffix first, else None."""
    if text.startswith(", ", pos):
        at = pos + 2
    elif text.startswith(" ", pos):
        at = pos + 1
    else:
        return None
    for suffix in _SUFFIXES_SHORTEST_FIRST:
        end = at + len(suffix)
        if text.startswith(suffix, at) and (end >= len(text) or not _is_alnum(text[end])):
            return end
    return None


def _capitalised_run(text: str, words: dict[int, int], start: int, joiners: str) -> int:
    """End of the run of capitalised words starting at ``start`` (joined by ``joiners``)."""
    end = words[start]
    while end < len(text) and text[end] in joiners and (end + 1) in words:
        end = words[end + 1]
    return end


def _hq_cities(text: str, folded: str) -> set:
    """Place names directly after an hq_city phrase and one space.

    The phrase itself is never part of the place name, whatever its case: in
    `Headquartered In Lisbon` the place name is `Lisbon` (lead ruling on R192/R201).
    """
    values = set()
    words = {s.start: s.end for s in _capitalised_words(text)}
    for phrase in STATEMENT_PHRASES["hq_city"]:
        for _, end in _find_phrase(folded, phrase):
            start = end + 1
            if text.startswith(" ", end) and start in words:
                values.add(text[start:_capitalised_run(text, words, start, " -")])
    return values


def _ceo_names(text: str, folded: str, domain: str) -> set:
    removed = _find_phrase(folded, company_name(domain))
    for phrase in STATEMENT_PHRASES["ceo"]:
        removed += _find_phrase(folded, phrase)
    kept = [w for w in _capitalised_words(text)
            if all(w.end <= s or w.start >= e for s, e in removed)]
    values, run = set(), []
    for word in kept + [None]:
        if word is not None and run and text[run[-1].end:word.start] == " ":
            run.append(word)
            continue
        if 2 <= len(run) <= 3:
            values.add(text[run[0].start:run[-1].end])
        run = [word] if word is not None else []
    return values


def _years(text: str) -> set:
    amounts = _amounts(text)
    return {int(n.text) for n in _numbers(text)
            if len(n.text) == 4 and n.text.isdigit() and 1800 <= int(n.text) <= 2099
            and _outside(amounts, n.start, n.end)}


def headcount_range(count: int) -> str | None:
    for low, high, label in HEADCOUNT_RANGES:
        if count >= low and (high is None or count <= high):
            return label
    return None


def _headcounts(text: str) -> set:
    amounts = _amounts(text)
    values = set()
    for n in _numbers(text):
        if n.integral and _outside(amounts, n.start, n.end):
            label = headcount_range(int(n.value))
            if label is not None:
                values.add(label)
    return values


def _funding(text: str) -> set:
    return {a.dollars for a in _amounts(text) if a.dollars is not None}


def _values(field: str, text: str, folded: str, domain: str) -> set:
    if field == "legal_name":
        return _legal_names(text, folded, domain)
    if field == "hq_city":
        return _hq_cities(text, folded)
    if field == "ceo":
        return _ceo_names(text, folded, domain)
    if field == "founded_year":
        return _years(text)
    if field == "headcount_range":
        return _headcounts(text)
    if field == "funding_total":
        return _funding(text)
    raise ValueError(f"unknown field {field!r}")


# --------------------------------------------------------------------------- A.2

def names_company(excerpt: str, domain: str) -> bool:
    folded = _fold(collapse(excerpt))
    return bool(_find_phrase(folded, company_name(domain)) or _find_phrase(folded, domain))


def supports(excerpt: str, field: str, domain: str):
    """The value ``excerpt`` supports for ``field`` of the company at ``domain``, or None.

    ``domain`` must already be normalised. The returned value is normalised per A.5:
    a string for legal_name/hq_city/ceo/headcount_range, an int for founded_year and
    funding_total.
    """
    text = collapse(excerpt)
    if not text or not is_single_sentence(text):
        return None
    folded = _fold(text)
    if not (_find_phrase(folded, company_name(domain)) or _find_phrase(folded, domain)):
        return None
    if not any(_find_phrase(folded, p) for p in STATEMENT_PHRASES[field]):
        return None
    if any(_find_phrase(folded, p) for p in NEGATING_PHRASES):
        return None
    values = _values(field, text, folded, domain)
    return next(iter(values)) if len(values) == 1 else None


@dataclass(frozen=True)
class Support:
    field: str
    value: object
    excerpt: str


def candidates(text: str, domain: str, fields: tuple[str, ...] = FIELDS) -> list[Support]:
    """Every (field, value, excerpt) a page's prose supports, in page order.

    Excerpts are whole sentences with whitespace collapsed, 1 to 500 characters long.
    """
    found = []
    for sentence in sentences(prose(text)):
        excerpt = collapse(sentence)
        if not 1 <= len(excerpt) <= MAX_EXCERPT_CHARS or not names_company(excerpt, domain):
            continue
        for field in fields:
            value = supports(excerpt, field, domain)
            if value is not None:
                found.append(Support(field, value, excerpt))
    return found
