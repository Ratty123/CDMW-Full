"""A deferred no-op round trip is computed once and seen by every session sharing the mesh."""

from __future__ import annotations

from types import SimpleNamespace

from cdmw.services import mesh_service


def _session(base, source=None):
    return SimpleNamespace(
        no_op_roundtrip_report=None,
        source_coordinate_base_mesh=source,
        base_mesh=base,
        working_mesh=SimpleNamespace(),
        base_mesh_is_original_parse=True,
        original_data=b"PAC bytes",
    )


def _deferred_mesh():
    mesh = SimpleNamespace(path="character/a.pac")
    mesh._cdmw_no_op_roundtrip_deferred = True
    return mesh


def test_shadow_and_authoritative_sessions_sharing_a_base_both_pass(monkeypatch):
    calls = []

    def roundtrip(data, path, parser=None, **_kwargs):
        calls.append(path)
        return SimpleNamespace(report={"result": "PASS", "byte_identical": True})

    monkeypatch.setattr(mesh_service, "roundtrip_mesh_bytes", roundtrip)
    base = _deferred_mesh()
    authoritative, shadow = _session(base), _session(base)
    # Finish checks the shadow first; the authoritative session used to read "not_run".
    assert mesh_service._session_roundtrip_status(shadow) == "PASS"
    assert mesh_service._session_roundtrip_status(authoritative) == "PASS"
    assert len(calls) == 1


def test_a_source_coordinate_base_shares_its_report(monkeypatch):
    monkeypatch.setattr(
        mesh_service, "roundtrip_mesh_bytes",
        lambda *a, **k: SimpleNamespace(report={"result": "PASS"}),
    )
    authoritative_base = _deferred_mesh()
    authoritative = _session(authoritative_base)
    neutral_shadow = _session(SimpleNamespace(path="neutral.pac"), source=authoritative_base)
    assert mesh_service._session_roundtrip_status(authoritative) == "PASS"
    assert mesh_service._session_roundtrip_status(neutral_shadow) == "PASS"


def test_a_session_whose_mesh_was_never_deferred_still_reports_not_run():
    assert mesh_service._session_roundtrip_status(_session(SimpleNamespace(path="x.pac"))) == "not_run"
