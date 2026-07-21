from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.preview_d3d11_runtime import (
    ArchivePreviewD3D11RuntimeMixin,
    archive_model_initial_view_state,
)
from cdmw.ui.archive_browser.preview_state import archive_model_preview_refresh_tooltip


def test_archive_model_preview_refresh_tooltip_preserves_copy() -> None:
    assert (
        archive_model_preview_refresh_tooltip()
        == "Refresh Archive Preview now. Works even while Mesh Replacement Builder is open."
    )


def test_archive_model_initial_view_state_is_front_facing_by_default() -> None:
    assert archive_model_initial_view_state() == {
        "role": "replacement",
        "reason": "archive_model_initial_front",
        "zoom_factor": 1.0,
        "fit_to_view": True,
        "yaw": 0.0,
        "pitch": 0.0,
        "pan": (0.0, 0.0, 0.0),
    }


def test_archive_model_initial_view_state_uses_overhead_only_for_weapon_paths() -> None:
    overhead_paths = (
        "character/model/1_pc/1_phm/weapon/1_longsword/blade.pac",
        "character/model/1_pc/1_phm/subweapon/quiver.pac",
        "character/model/1_pc/1_phm/shield/buckler.pac",
        "character/model/1_pc/1_phm/4_bow/bow.pac",
        "character/model/1_pc/1_phm/twohandweapon/axe.pac",
    )
    front_paths = (
        "character/model/1_pc/1_phm/upper/armor.pac",
        "character/model/1_pc/1_phm/lower/trousers.pac",
        "character/model/1_pc/1_phm/hand/gloves.pac",
        "character/model/1_pc/1_phm/foot/boots.pac",
        "character/model/object/chair.pac",
        "",
    )

    assert all(archive_model_initial_view_state(path)["pitch"] == -89.0 for path in overhead_paths)
    assert all(archive_model_initial_view_state(path)["pitch"] == 0.0 for path in front_paths)


def test_archive_model_pending_view_state_clears_only_after_restore() -> None:
    restored_states: list[dict[str, object]] = []

    class _Host:
        restore_succeeds = False

        def restore_view_state(self, state: object) -> bool:
            restored_states.append(dict(state))
            return self.restore_succeeds

    host = _Host()
    runtime = SimpleNamespace(
        archive_d3d11_pending_view_state=archive_model_initial_view_state(),
        archive_d3d11_preview_host=host,
    )

    assert not ArchivePreviewD3D11RuntimeMixin._restore_archive_d3d11_pending_view_state(runtime)
    assert runtime.archive_d3d11_pending_view_state == archive_model_initial_view_state()

    host.restore_succeeds = True
    assert ArchivePreviewD3D11RuntimeMixin._restore_archive_d3d11_pending_view_state(runtime)
    assert restored_states == [archive_model_initial_view_state(), archive_model_initial_view_state()]
    assert runtime.archive_d3d11_pending_view_state == {}
