"""Observable origin, corroboration and investors contracts (F18-F54)."""
from __future__ import annotations

from datetime import datetime

from conftest import API, DOMAIN, FIELDS8, create, feed, history


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None and parsed.utcoffset() is not None
    return parsed


def _candidate_order(candidate: dict) -> tuple:
    """Stage 2's public rank order; lower tuple means higher rank."""
    kind = candidate.get("kind")
    authority = 0 if kind in ("own", "filing") else 1 if kind == "news" else 2
    published = candidate.get("published_at")
    recency = -_instant(published).timestamp() if published else float("inf")
    provider_order = {"nimble": 0, "tavily": 1, "kernel": 2, "browserbase": 3}
    value = candidate.get("value")
    value_key = (0, value) if isinstance(value, int) and not isinstance(value, bool) else (1, str(value).strip())
    return authority, published is None, recency, tuple(map(ord, candidate["url"])), \
        provider_order.get(candidate["provider"], 99), value_key


def test_all_fields_expose_origin_corroboration_and_investor_members(api: API, token: str) -> None:
    """F19-F54: origins are sorted/distinct; investor membership and member corroboration hold."""
    dossier, _ = create(api, token)
    fields = dossier["fields"]
    assert tuple(fields) == FIELDS8
    for name, field in fields.items():
        assert {"origins", "corroborated", "corroborated_since"} <= field.keys(), name
        assert field["origins"] == sorted(set(field["origins"])), name
        assert isinstance(field["corroborated"], bool), name
        if field["corroborated_since"] is not None:
            _instant(field["corroborated_since"])
        for candidate in field["candidates"]:
            assert isinstance(candidate.get("origin"), str) and candidate["origin"], candidate
        assert field["candidates"] == sorted(field["candidates"], key=_candidate_order), name

    investors = fields["investors"]
    candidates = investors["candidates"]
    names: dict[str, list[dict]] = {}
    for candidate in candidates:
        names.setdefault(candidate["value"], []).append(candidate)
    members = set()
    for investor, group in names.items():
        origins = {candidate["origin"] for candidate in group}
        if any(candidate.get("kind") in ("own", "filing") for candidate in group) or len(origins) >= 2:
            members.add(investor)
    assert investors["value"] == (sorted(members) if members else None)
    assert investors["status"] == ("known" if members else "unknown")
    assert all(candidate["selected"] == (candidate["value"] in members)
               for candidate in candidates)
    for candidate in candidates:
        assert candidate["value"] in candidate["excerpt"], candidate
    assert candidates == sorted(candidates, key=_candidate_order)
    expected_investor_citations = [
        {key: candidate[key] for key in ("url", "excerpt", "provider")}
        for member in (investors["value"] or []) for candidate in candidates
        if candidate["value"] == member
    ]
    assert investors["citations"] == expected_investor_citations
    assert investors["origins"] == sorted({candidate["origin"] for candidate in candidates
                                            if candidate["value"] in members})
    assert investors["corroborated"] == bool(members) and all(
        len({candidate["origin"] for candidate in names[member]}) >= 2 for member in members)
    if not members:
        assert investors["origins"] == [] and investors["corroborated"] is False
    investor_history = history(api, token)["fields"]["investors"]
    for entry in investor_history:
        assert entry["type"] in ("initial", "change", "correction")
        assert entry["value"] is None or isinstance(entry["value"], list)
    investor_feed = [entry for entry in feed(api, token)["changes"] if entry["field"] == "investors"]
    for entry in investor_feed:
        assert entry["from"] is None or isinstance(entry["from"], list)
        assert entry["to"] is None or isinstance(entry["to"], list)
        assert entry["seq"] > 0

    for name in FIELDS8[:6]:
        field = fields[name]
        selected = [candidate for candidate in field["candidates"] if candidate["selected"]]
        assert len(selected) <= 1
        selected_value = field["value"]
        origins = sorted({candidate["origin"] for candidate in field["candidates"]
                          if candidate["value"] == selected_value})
        assert field["origins"] == origins
        assert field["corroborated"] == (len(origins) >= 2)
        expected_citations = [
            {key: candidate[key] for key in ("url", "excerpt", "provider")}
            for candidate in field["candidates"] if candidate["value"] == selected_value
        ]
        assert field["citations"] == expected_citations

    executives = fields["executives"]
    exec_members = executives["value"] or []
    title_order = {"cfo": 0, "coo": 1, "cto": 2}
    assert [member["title"] for member in exec_members] == sorted(
        (member["title"] for member in exec_members), key=title_order.get)
    per_member_origins = []
    for title in {candidate["title"] for candidate in executives["candidates"]}:
        group = [candidate for candidate in executives["candidates"] if candidate["title"] == title]
        assert sum(candidate["selected"] for candidate in group) == 1
        assert min(group, key=_candidate_order)["selected"] is True
    for member in exec_members:
        group = [candidate for candidate in executives["candidates"]
                 if candidate.get("title") == member["title"]
                 and candidate["value"] == member["name"]]
        assert group and any(candidate["selected"] for candidate in group)
        per_member_origins.append({candidate["origin"] for candidate in group})
    all_exec_origins = sorted(set().union(*per_member_origins) if per_member_origins else set())
    assert executives["origins"] == all_exec_origins
    assert executives["corroborated"] == bool(per_member_origins) and all(
        len(origins) >= 2 for origins in per_member_origins)


def test_values_include_stage4_keys_computed_at_true_at(api: API, token: str) -> None:
    """F20/F50: /values has origins and corroborated, but no undefined since timestamp."""
    create(api, token)
    response = api.get(f"/dossiers/{DOMAIN}/values?true_at=2099-12-31", token=token)
    assert response.status_code == 200, response.text
    fields = response.json()["fields"]
    assert tuple(fields) == FIELDS8
    for field in fields.values():
        assert {"value", "true_from", "citations", "origins", "corroborated"} <= field.keys()
        assert "corroborated_since" not in field
        assert field["origins"] == sorted(set(field["origins"]))
        assert isinstance(field["corroborated"], bool)


def test_public_dossier_shell_contains_no_dossier_evidence(api: API, token: str) -> None:
    """E19/F54: public HTML is only a shell; JSON data remains bearer-authenticated."""
    dossier, _ = create(api, token)
    shell = api.get(f"/dossiers/{DOMAIN}", headers={"Accept": "text/html"})
    assert shell.status_code == 200, shell.text
    assert "text/html" in shell.headers.get("content-type", "")
    for field in dossier["fields"].values():
        for candidate in field["candidates"]:
            assert candidate["excerpt"] not in shell.text
    unauthenticated = api.get(f"/dossiers/{DOMAIN}")
    assert unauthenticated.status_code == 401, unauthenticated.text
