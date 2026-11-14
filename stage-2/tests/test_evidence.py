"""Choosing among supported values (§4, plan D7/D32)."""
from app.evidence import Candidate, decide
from app.support import supports

D = "acme-robotics.test"


def cand(field, value, url, excerpt, order):
    return Candidate(field, value, url, excerpt, "nimble", order)


def test_no_candidates_all_unknown():
    assert all(f == {"value": None, "status": "unknown", "citations": []}
               for f in decide([]).values())


def test_conflict_cites_only_chosen_value():
    fields = decide([cand("founded_year", 2014, "u1", "Acme Robotics was founded in 2014.", 0),
                     cand("founded_year", 2015, "u2", "Acme Robotics was founded in 2015.", 1),
                     cand("founded_year", 2015, "u3", "Acme Robotics was founded in 2015.", 2)])
    assert fields["founded_year"]["value"] == 2015
    assert {c["url"] for c in fields["founded_year"]["citations"]} == {"u2", "u3"}
    for c in fields["founded_year"]["citations"]:
        assert supports(c["excerpt"], "founded_year", D) == 2015


def test_hq_city_prefers_comma_then_shorter():
    a = cand("hq_city", "Lisbon Portugal", "u1", "Acme Robotics is based in Lisbon Portugal.", 0)
    b = cand("hq_city", "Lisbon", "u2", "Acme Robotics is based in Lisbon, Portugal.", 1)
    assert decide([a, a, b])["hq_city"]["value"] == "Lisbon"
    c = cand("hq_city", "Lisbon", "u3", "Acme Robotics is based in Lisbon now.", 2)
    assert decide([a, c])["hq_city"]["value"] == "Lisbon"


def test_same_excerpt_on_two_urls_gives_two_citations():
    e = "Acme Robotics was founded in 2014."
    fields = decide([cand("founded_year", 2014, "u1", e, 0), cand("founded_year", 2014, "u1", e, 1),
                     cand("founded_year", 2014, "u2", e, 2)])
    assert len(fields["founded_year"]["citations"]) == 2
