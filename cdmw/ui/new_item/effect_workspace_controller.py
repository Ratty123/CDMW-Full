"""Controller-side catalogue, staging, preflight and preview support for Step 5."""

from __future__ import annotations

from dataclasses import replace
from typing import Optional, Tuple

from cdmw.domain.cancellation import RunCancelled
from cdmw.services.effect_catalogue import (
    EffectCatalogue,
    EffectFacts,
    catalogue_signature,
    load_effect_catalogue,
)
from cdmw.ui.new_item.state import EffectWorkspaceState, effect_reference


class NewItemEffectWorkspaceControllerMixin:
    """Keep effect-specific controller behavior out of the general workflow owner."""

    def effect_stems(self, text: str = "", *, limit: Optional[int] = 300) -> Tuple[str, ...]:
        """Every shipped stem matching all search terms, optionally limited."""

        if self.snapshot is None:
            return ()
        if self.effect_catalogue is not None and len(self.effect_catalogue):
            return tuple(item.stem for item in self.effect_catalogue.search(text, limit=limit))
        needle = str(text or "").strip().casefold()
        stems = [stem for stem in self.snapshot.effect_stems if not needle or needle in stem.casefold()]
        ordered = sorted(stems)
        return tuple(ordered if limit is None else ordered[: max(0, int(limit))])

    def effect_facts(self, stem: str) -> Optional[EffectFacts]:
        if self.effect_catalogue is None:
            return None
        return self.effect_catalogue.get(stem)

    def commit_effect_workspace(self, state: EffectWorkspaceState) -> bool:
        """Publish one staged effect state to the draft and invalidate exactly once."""

        if not str(state.stem or "").strip():
            state = EffectWorkspaceState.defaults()
        before = EffectWorkspaceState.from_draft(self.draft)
        if state == before:
            return False
        state.write_to(self.draft)
        self.invalidate_plan()
        self.effect_changed.emit(state)
        return True

    def effect_target_compatibility(self, stem: str):
        """Read-only structural preflight for a staged effect selection."""

        if self.snapshot is None or self.draft.template_key is None:
            return None
        try:
            spec = replace(self.current_spec(), effect=effect_reference(stem))
        except ValueError:
            return None
        return self.service.inspect_effect_targets(spec, self.snapshot)

    def effect_preview_for_placement(self, stem: str = "", state: Optional[EffectWorkspaceState] = None):
        """Return a frozen staged-preview builder and its archive texture reader.

        The placement package lane invokes the builder with its cancellation probe; effect
        binary, emitter, preset and spawn-mesh decoding must never run in this UI caller.
        """

        from cdmw.domain.new_item.spec import EffectLook
        from cdmw.services.effect_preview_model import preview_effect_from_snapshot

        snapshot = self.snapshot
        chosen = str(stem or self.draft.effect_stem or "")
        if snapshot is None or not chosen:
            return None, None
        look_source = state or EffectWorkspaceState.from_draft(self.draft)
        look = EffectLook(
            color=tuple(float(value) for value in look_source.color) if look_source.color is not None else None,
            intensity=float(look_source.intensity),
            size=float(look_source.size),
            rate=float(look_source.rate),
            lifetime=float(look_source.lifetime),
        )
        def build_preview(cancelled):
            try:
                return preview_effect_from_snapshot(snapshot, chosen, look, cancelled=cancelled)
            except RunCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - numeric placement remains usable
                self.log_message.emit(f"The effect {chosen} gave no particle description: {exc}")
                return None

        def read_texture(path: str) -> Optional[bytes]:
            try:
                return snapshot.payload(path) if snapshot.has_entry(path) else None
            except Exception:  # noqa: BLE001 - one missing sprite does not remove placement
                return None

        return build_preview, read_texture

    def effect_box(self, stem: str = "") -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
        facts = self.effect_facts(stem or self.draft.effect_stem)
        if facts is None or all(abs(value) < 1e-9 for value in (*facts.box_min, *facts.box_max)):
            return (-0.5, -0.5, -0.5), (0.5, 0.5, 0.5)
        return facts.box_min, facts.box_max

    def load_effect_catalogue(self) -> bool:
        if self.snapshot is None or self.effect_cache_path is None:
            return False
        catalogue = load_effect_catalogue(
            self.effect_cache_path,
            signature=catalogue_signature(self.snapshot),
        )
        if catalogue is None:
            return False
        self.effect_catalogue = catalogue
        self.effect_catalogue_ready.emit()
        return True

    def start_effect_index(self) -> bool:
        if self.snapshot is None:
            self.status_message.emit("Read the archives first.", True)
            return False
        return self._effect_lane.start(self.snapshot, cache_path=self.effect_cache_path)

    def _publish_effect_catalogue(self, snapshot: object, catalogue: object) -> None:
        if self._shutdown_requested or snapshot is not self.snapshot or not isinstance(catalogue, EffectCatalogue):
            return
        self.effect_catalogue = catalogue
        self.effect_catalogue_ready.emit()


__all__ = ["NewItemEffectWorkspaceControllerMixin"]
