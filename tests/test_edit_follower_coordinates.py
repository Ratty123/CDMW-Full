"""An edit held in neutral coordinates says so, so no preview follows it out of place (P5).

The Rust engine lets other previews of the edited file follow the edit read-only.
An edit in a refit's or a replacement's neutral space would be drawn where the
file's own parts are not; the session manifest's source block now says which
coordinates the edit uses, and the engine follows only "source" (section 8.1,
item 5, the V5 follower limits).
"""

from __future__ import annotations

from types import SimpleNamespace

from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession


def _session(*, appearance=None, context=None, replacement=None):
    shadow = SimpleNamespace(archive_refit_context=context, replacement_state=replacement)
    service = SimpleNamespace(_session=lambda _session_id: shadow)
    return SimpleNamespace(shadow_service=service, shadow_session_id="shadow", neutral_appearance=appearance)


def test_the_edit_s_coordinates_are_named_for_its_followers() -> None:
    coordinates = RustMeshAuthoringSession._shadow_coordinates
    assert coordinates(_session()) == "source"
    assert coordinates(_session(appearance=object())) == "neutral"
    assert coordinates(_session(context=SimpleNamespace(neutral_coordinates=True))) == "neutral"
    assert coordinates(_session(context=SimpleNamespace(neutral_coordinates=False))) == "source"
    assert coordinates(_session(replacement=SimpleNamespace(neutral_coordinates=True))) == "neutral"


def test_a_session_that_is_gone_reads_as_source() -> None:
    def missing(_session_id):
        raise KeyError(_session_id)

    session = SimpleNamespace(shadow_service=SimpleNamespace(_session=missing), shadow_session_id="gone",
                              neutral_appearance=None)
    assert RustMeshAuthoringSession._shadow_coordinates(session) == "source"
