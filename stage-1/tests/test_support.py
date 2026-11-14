"""Appendix A (support) and §4 page rules."""
import pytest

from app.support import (candidates, collapse, company_name, is_single_sentence, prose,
                         sentences, supports)

D = "acme-robotics.test"


@pytest.mark.parametrize("excerpt, field, value", [
    # A.2 examples, verbatim.
    ("Dana Ruiz has led Acme Robotics as chief executive since 2021.", "ceo", "Dana Ruiz"),
    ("Acme Robotics CEO: Sam Ortiz.", "ceo", "Sam Ortiz"),
    ("Acme Robotics was founded in 2014.", "founded_year", 2014),
    ("Acme Robotics employs about 120 people.", "headcount_range", "51-200"),
    # §4 examples.
    ("Acme Robotics has raised $12M.", "funding_total", 12000000),
    ("Acme Robotics has raised 12 million dollars.", "funding_total", 12000000),
])
def test_examples_support(excerpt, field, value):
    assert supports(excerpt, field, D) == value


@pytest.mark.parametrize("excerpt, field", [
    ("Acme Robotics is reportedly in talks to raise $40M.", "funding_total"),
    ("Acme Robotics opened a sales office in Porto.", "hq_city"),
    ("Acme Robotics is not headquartered in Porto.", "hq_city"),
    ("Former CEO Dana Ruiz left Acme Robotics.", "ceo"),
    ("Dana Ruiz founded a company in 2014.", "founded_year"),  # no company name
    ("Acme Robotics CEOs met in 2014.", "ceo"),               # CEOs is not CEO
    ("Acme Robotics was unfounded in 2014.", "founded_year"),  # unfounded is not founded
])
def test_examples_support_nothing(excerpt, field):
    assert supports(excerpt, field, D) is None


@pytest.mark.parametrize("amount, dollars", [
    ("$12M", 12_000_000), ("$12.5 million", 12_500_000), ("US$12 million", 12_000_000),
    ("USD 12 million", 12_000_000), ("$12m", 12_000_000), ("$12,000,000", 12_000_000),
    ("12 million dollars", 12_000_000), ("12,000,000 US dollars", 12_000_000),
    ("$3mn", 3_000_000), ("$1.5bn", 1_500_000_000), ("$250k", 250_000),
    ("$40 thousand", 40_000),
])
def test_amount_forms(amount, dollars):
    assert supports(f"Acme Robotics has raised {amount} so far.", "funding_total", D) == dollars


@pytest.mark.parametrize("amount", ["€12M", "A$12M", "12 million euros", "$1.2345k", "$1,20"])
def test_not_amounts(amount):
    assert supports(f"Acme Robotics has raised {amount} so far.", "funding_total", D) is None


def test_conflicting_values_support_nothing():
    assert supports("Acme Robotics was founded in 2014 and 2015.", "founded_year", D) is None
    assert supports("Acme Robotics has 40-60 employees.", "headcount_range", D) is None
    assert supports("Acme Robotics has 51-200 employees.", "headcount_range", D) == "51-200"
    assert supports("Acme Robotics has 3,148 employees.", "headcount_range", D) == "1001-5000"


def test_year_inside_amount_is_not_a_year():
    assert supports("Acme Robotics was founded with $2014 of savings.", "founded_year", D) is None


def test_legal_name():
    assert supports("Acme Robotics, Inc. was founded in 2014.", "legal_name", D) is None  # no phrase
    assert supports("The registered name is Acme Robotics, Inc. and nothing else.",
                    "legal_name", D) == "Acme Robotics, Inc."
    assert supports("Its legal name is Acme Robotics Holdings GmbH.", "legal_name",
                    D) == "Acme Robotics Holdings GmbH"
    assert supports("Its legal name is Acme Robotics ASA.", "legal_name", D) == "Acme Robotics ASA"
    assert supports("Its legal name is Acme Robotics AS.", "legal_name", D) == "Acme Robotics AS"
    assert supports("Its legal name is Acme Robotics Pty Ltd.", "legal_name",
                    D) == "Acme Robotics Pty Ltd"
    assert supports("Its legal name is Acme Robotics Inc.", "legal_name", D) == "Acme Robotics Inc."
    assert supports("Its legal name is Acme Robotics Inc today.", "legal_name", D) is None


def test_suffix_dot_does_not_end_sentence():
    text = "Acme Robotics, Inc. was founded in 2014."
    assert sentences(text) == [text]
    assert supports(text, "founded_year", D) == 2014


def test_hq_city():
    assert supports("Acme Robotics is based in Valencia, Spain.", "hq_city", D) == "Valencia"
    assert supports("Acme Robotics is based in Lisbon Portugal.", "hq_city", D) == "Lisbon Portugal"
    assert supports("Acme Robotics is headquartered in Zürich.", "hq_city", D) == "Zürich"
    assert supports("Acme Robotics is headquartered in Saint-Étienne now.", "hq_city",
                    D) == "Saint-Étienne"
    assert supports("Acme Robotics is based in the city of Lisbon.", "hq_city", D) is None


def test_ceo_runs():
    assert supports("As CEO of Acme Robotics, Priya Dalton expanded abroad.", "ceo",
                    D) == "Priya Dalton"
    assert supports("Acme Robotics chief executive officer Hans Peter Müller spoke.", "ceo",
                    D) == "Hans Peter Müller"
    assert supports("In March Dana Ruiz became Acme Robotics CEO.", "ceo", D) is None  # 4 words


def test_sentences_and_closers():
    assert sentences('He said "it was founded in 2014." Then it grew.') == [
        'He said "it was founded in 2014."', "Then it grew."]
    assert sentences("One.\nTwo! Three?") == ["One.", "Two!", "Three?"]
    assert sentences("Version 1.2 shipped.") == ["Version 1.2 shipped."]
    assert is_single_sentence("Acme Robotics was\n founded in 2014.")
    assert not is_single_sentence("One. Two.")


def test_header_removed():
    text = ('Kind: news\nFacts: {"ceo": "Dana Ruiz"}\nFirst-Published-By: wire.test\n\n'
            "Dana Ruiz is the CEO of Acme Robotics.")
    assert prose(text) == "Dana Ruiz is the CEO of Acme Robotics."
    assert prose("Größe: 5\nÜber-Uns: x\n\nBody.") == "Body."
    assert prose("CEO: Sam Ortiz\nmore") == "CEO: Sam Ortiz\nmore"
    assert prose("Kind: news\nno empty line") == ""


def test_candidates_cite_prose_only():
    text = ("Kind: news\nFacts: {\"ceo\": \"Acme Robotics CEO: Sam Ortiz.\"}\n\n"
            "Acme Robotics   was founded\tin 2014.  Acme Robotics employs 120 people.")
    found = {(c.field, c.value, c.excerpt) for c in candidates(text, D)}
    assert found == {("founded_year", 2014, "Acme Robotics was founded in 2014."),
                     ("headcount_range", "51-200", "Acme Robotics employs 120 people.")}


def test_long_sentence_not_citable():
    text = "Acme Robotics was founded in 2014 " + "x" * 480 + "."
    assert candidates(text, D) == []


def test_domain_names_company_and_name():
    assert company_name(D) == "acme robotics"
    assert supports("ACME-ROBOTICS.TEST was founded in 2014.", "founded_year", D) == 2014
    assert collapse("  a \n b ") == "a b"


# ---------------------------------------------------------------- phrase case (A.2, A.3)

def _cases(phrase):
    """The phrase as written, in upper case and in title case."""
    return {phrase, phrase.upper(), phrase.title()}


@pytest.mark.parametrize("phrase", [p for base in (
    "headquartered in", "headquarters in", "head office in", "based in",
    "registered office in", "registered seat in") for p in _cases(base)])
def test_hq_city_phrase_in_any_case(phrase):
    assert supports(f"Acme Robotics is {phrase} Lisbon, Portugal.", "hq_city", D) == "Lisbon"
    assert supports(f"Acme Robotics is {phrase} São Paulo now.", "hq_city", D) == "São Paulo"


@pytest.mark.parametrize("phrase", [p for base in (
    "chief executive officer", "chief executive", "CEO") for p in _cases(base)])
def test_ceo_phrase_in_any_case(phrase):
    assert supports(f"{phrase} Dana Ruiz leads Acme Robotics.", "ceo", D) == "Dana Ruiz"
    assert supports(f"Acme Robotics {phrase} Dana Ruiz spoke.", "ceo", D) == "Dana Ruiz"


@pytest.mark.parametrize("phrase", [p for base in (
    "legal name", "registered name", "registered as", "registered company", "legal entity",
    "name of record") for p in _cases(base)])
def test_legal_name_phrase_in_any_case(phrase):
    assert supports(f"The {phrase} is Acme Robotics Holdings Ltd today.", "legal_name",
                    D) == "Acme Robotics Holdings Ltd"
    assert supports(f"ACME ROBOTICS: {phrase} Acme Robotics, Inc. in Delaware.", "legal_name",
                    D) == "Acme Robotics, Inc."


@pytest.mark.parametrize("field, sentence, value", [
    *[("founded_year", f"Acme Robotics was {p} in 2014.", 2014)
      for base in ("founded", "founding", "established", "incorporated") for p in _cases(base)],
    *[("headcount_range", f"Acme Robotics {p} 120 here.", "51-200")
      for base in ("employs", "employees", "staff", "people", "headcount", "workforce")
      for p in _cases(base)],
    *[("funding_total", f"Acme Robotics {p} $12M.", 12000000)
      for base in ("raised", "funding", "invested", "investment") for p in _cases(base)],
])
def test_other_phrases_in_any_case(field, sentence, value):
    assert supports(sentence, field, D) == value


@pytest.mark.parametrize("negation", [p for base in (
    "in talks to", "plans to", "planning to", "wants to", "expects to", "hopes to", "aims to",
    "seeking", "could", "would", "might", "reportedly", "rumoured", "former", "formerly",
    "will become", "not") for p in _cases(base)])
def test_negating_phrase_in_any_case(negation):
    assert supports(f"Acme Robotics {negation} founded in 2014.", "founded_year", D) is None


def test_company_name_in_any_case_for_legal_name():
    assert supports("The legal name is ACME ROBOTICS Ltd now.", "legal_name",
                    D) == "ACME ROBOTICS Ltd"
    assert supports("The legal name is acme robotics GmbH now.", "legal_name",
                    D) == "acme robotics GmbH"
