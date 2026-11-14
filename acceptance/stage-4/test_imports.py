"""Stage 1/2/3-shaped import compatibility and new investors defaults (F81-F85)."""
from __future__ import annotations

from copy import deepcopy
from urllib.parse import quote, urlsplit

from conftest import (API, DOMAIN, FIELDS8, create, downgrade_export, feed, history, key,
                      refresh)


def test_older_stage_imports_make_investors_unknown_without_history(api: API, token: str) -> None:
    """F81/F84: synthetic older envelopes keep dossiers but add an empty investors field/history."""
    idem = key()
    create(api, token, idem=idem)
    source = api.get("/_test/export")
    assert source.status_code == 200, source.text
    exported = source.json()
    for stage in (1, 2, 3):
        legacy = downgrade_export(deepcopy(exported), stage)
        result = api.post("/_test/import", json=legacy, timeout=20)
        assert result.status_code == 204, (stage, result.text)
        replay = api.post("/dossiers", token=token, headers={"Idempotency-Key": idem},
                          json={"domain": DOMAIN})
        assert replay.status_code == 200, replay.text
        dossier = api.get(f"/dossiers/{DOMAIN}", token=token)
        assert dossier.status_code == 200, dossier.text
        fields = dossier.json()["fields"]
        assert tuple(fields) == FIELDS8
        if dossier.json()["researched_at"] is not None:
            timestamp = quote(dossier.json()["researched_at"], safe="")
            at = api.get(f"/dossiers/{DOMAIN}?as_of={timestamp}", token=token)
            assert at.status_code == 200, at.text
            assert at.json()["fields"]["investors"]["value"] is None
        investors = fields["investors"]
        assert investors["value"] is None and investors["status"] == "unknown"
        assert investors["candidates"] == []
        assert investors["origins"] == [] and investors["corroborated"] is False
        assert history(api, token)["fields"]["investors"] == []
        assert feed(api, token)["changes"] == []
        for name in FIELDS8[:6]:
            for candidate in fields[name]["candidates"]:
                host = (urlsplit(candidate["url"]).hostname or "").lower().removesuffix(".")
                if host.startswith("www."):
                    host = host[4:]
                assert candidate["origin"] == host
        rebuilt = refresh(api, token)
        if rebuilt["fields"]["investors"]["value"] is not None:
            entries = history(api, token)["fields"]["investors"]
            assert entries and entries[-1]["type"] == "change"


def test_stage3_export_round_trip_preserves_history_feed_and_candidate_origins(api: API,
                                                                                token: str) -> None:
    """F82-F83: importing a stage-3-shaped export preserves kept history/build snapshots."""
    create(api, token)
    current = api.get(f"/dossiers/{DOMAIN}", token=token).json()
    before = {
        "dossier": api.get(f"/dossiers/{DOMAIN}", token=token).json(),
        "history": history(api, token),
        "feed": feed(api, token),
        "values": api.get(f"/dossiers/{DOMAIN}/values?true_at=2099-12-31", token=token).json(),
        "as_of": api.get(f"/dossiers/{DOMAIN}?as_of={quote(current['researched_at'], safe='')}", token=token).json(),
    }
    export = api.get("/_test/export")
    assert export.status_code == 200, export.text
    legacy = downgrade_export(deepcopy(export.json()), 3)
    imported = api.post("/_test/import", json=legacy, timeout=20)
    assert imported.status_code == 204, imported.text
    after = {
        "dossier": api.get(f"/dossiers/{DOMAIN}", token=token).json(),
        "history": history(api, token),
        "feed": feed(api, token),
        "values": api.get(f"/dossiers/{DOMAIN}/values?true_at=2099-12-31", token=token).json(),
        "as_of": api.get(f"/dossiers/{DOMAIN}?as_of={quote(current['researched_at'], safe='')}", token=token).json(),
    }
    assert after["dossier"]["dossier_id"] == before["dossier"]["dossier_id"]
    old_history_fields = {name: entries for name, entries in before["history"]["fields"].items()
                          if name != "investors"}
    assert {name: entries for name, entries in after["history"]["fields"].items()
            if name != "investors"} == old_history_fields
    assert [entry for entry in after["feed"]["changes"] if entry["field"] != "investors"] == \
        [entry for entry in before["feed"]["changes"] if entry["field"] != "investors"]
    assert _without_stage4_values(after["values"]) == _without_stage4_values(before["values"])
    assert _without_stage4_dossier_fields(after["as_of"]) == \
        _without_stage4_dossier_fields(before["as_of"])
    assert after["dossier"]["fields"]["investors"]["value"] is None
    assert after["history"]["fields"]["investors"] == []
    assert after["as_of"]["fields"]["investors"]["value"] is None


def _without_stage4_values(response: dict) -> dict:
    result = deepcopy(response)
    result["fields"].pop("investors", None)
    for field in result["fields"].values():
        for name in ("origins", "corroborated", "corroborated_since"):
            field.pop(name, None)
    return result


def _without_stage4_dossier_fields(response: dict) -> dict:
    result = deepcopy(response)
    result["fields"].pop("investors", None)
    for field in result["fields"].values():
        for name in ("origins", "corroborated", "corroborated_since"):
            field.pop(name, None)
        for candidate in field.get("candidates", []):
            candidate.pop("origin", None)
    return result
