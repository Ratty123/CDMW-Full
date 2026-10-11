"""Reversible body-control layers over the resident morph evaluator.

Manual settings remain authoritative inputs. The native core receives one
complete evaluated value set, through the existing reversible authoring path.
"""

from __future__ import annotations

from dataclasses import replace
import math

from cdmw.domain.mesh.morph_layers import (
    compose_mesh_morph_values,
    mesh_morph_macros,
    mesh_morph_profile_definition_fingerprint,
    mesh_morph_side_pairs,
    mesh_morph_side_pair_limits,
    update_mesh_morph_side_values,
    validate_mesh_morph_layers,
)
from cdmw.services.mesh_service_body_controls import MeshBodyControlsMixin


def capture_morph_layers(data):
    return (
        None if data.manual_values is None else tuple(sorted(data.manual_values.items())),
        tuple(sorted(data.macro_values.items())),
        bool(data.symmetry_enabled),
    )


def restore_morph_layers(data, layers):
    manual, macros, symmetry = layers
    data.manual_values = None if manual is None else dict(manual)
    data.macro_values = dict(macros)
    data.symmetry_enabled = bool(symmetry)


def clear_morph_layers(data):
    data.manual_values = None
    data.macro_values = {}
    data.symmetry_enabled = False


class MeshMorphLayerMixin(MeshBodyControlsMixin):
    def _morph_layer_state_fields_locked(self, session, data, profile, values):
        if profile is None:
            clear_morph_layers(data)
            return {}
        manual = dict(values) if data.manual_values is None else dict(data.manual_values)
        # Defaults cover only native profiles that have not published values yet.
        manual = {
            item.definition_id: manual.get(item.definition_id, item.default_percent)
            for item in profile.definitions
        }
        evaluated = compose_mesh_morph_values(
            profile, manual, data.macro_values, symmetry_enabled=data.symmetry_enabled,
        )
        if data.manual_values is not None and (
            set(values) != set(evaluated)
            or any(not math.isclose(values[key], value, rel_tol=1e-8, abs_tol=1e-7)
                   for key, value in evaluated.items())
        ):
            raise RuntimeError("The body control layers do not match the resident slider values.")
        return {
            "manual_values": tuple(sorted(manual.items())),
            "macro_values": tuple(sorted(data.macro_values.items())),
            "macro_definitions": mesh_morph_macros(profile),
            "symmetry_enabled": data.symmetry_enabled,
            "side_pairs": tuple(
                replace(pair, both_min_percent=limits[0], both_max_percent=limits[1])
                for pair in mesh_morph_side_pairs(profile)
                for limits in (mesh_morph_side_pair_limits(profile, manual, pair.pair_id),)
            ),
        }

    def _morph_layer_preset_fields_locked(self, session):
        data = self._required_morph_data(session)
        if data.manual_values is None:
            return {}
        return {
            "manual_values": tuple(sorted(data.manual_values.items())),
            "macro_values": tuple(sorted(data.macro_values.items())),
            "symmetry_enabled": data.symmetry_enabled,
            "profile_definition_fingerprint": mesh_morph_profile_definition_fingerprint(data.profile),
        }

    def _install_morph_preset_layers_locked(self, session, preset):
        data = self._required_morph_data(session)
        validate_mesh_morph_layers(data.profile, preset)
        data.manual_values = None if preset.manual_values is None else dict(preset.manual_values)
        data.macro_values = dict(preset.macro_values)
        data.symmetry_enabled = preset.symmetry_enabled

    def _retained_manual_values_locked(self, session):
        data = self._required_morph_data(session)
        state = self._refresh_cached_morph_metadata_locked(session)
        return dict(state.values) if data.manual_values is None else dict(data.manual_values)

    def _set_morph_layers_locked(self, session, manual, macros, symmetry, *, action, label):
        data = self._required_morph_data(session)
        values = compose_mesh_morph_values(
            data.profile, manual, macros, symmetry_enabled=symmetry,
        )
        manual, macros = dict(manual), {key: value for key, value in dict(macros).items() if value != 0.0}

        def apply():
            report = self._run_morph_command_locked(
                session, "morph_apply_preset", {"preset_id": "", "values": values},
                history_label=label, record_history=False,
            )
            current = self._required_morph_data(session)
            current.manual_values = manual
            current.macro_values = macros
            current.symmetry_enabled = symmetry
            current.preset_id = ""
            return self._morph_result_and_state_locked(session, action, report)[0]

        return self._morph_authoring_transaction_locked(session, action, label, apply)

    def set_morph_macro(self, session_id, macro_id, value, *, phase="end"):
        session = self._session(session_id)
        with session.export_lock:
            self._require_no_pending_morph_authoring(session, include_baseline=True)
            if str(phase or "end").lower() != "end":
                raise ValueError("Body controls accept completed slider changes only.")
            data = self._required_morph_data(session)
            key = str(macro_id or "")
            definition = next((item for item in mesh_morph_macros(data.profile) if item.macro_id == key), None)
            if definition is None:
                raise ValueError(f"Body control is unavailable for this profile: {key}")
            if isinstance(value, bool):
                raise ValueError("Body control values must be finite numbers.")
            try:
                requested = float(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("Body control values must be finite numbers.") from exc
            if not math.isfinite(requested) or not definition.min_percent <= requested <= definition.max_percent:
                raise ValueError("Body control value is outside its supported range.")
            manual = self._retained_manual_values_locked(session)
            if data.macro_values.get(key, 0.0) == requested:
                return self._result(session, "morph_set_macro", status="noop"), data.state
            macros = dict(data.macro_values)
            macros[key] = requested
            return self._set_morph_layers_locked(
                session, manual, macros, data.symmetry_enabled,
                action="morph_set_macro", label=f"Body Control {definition.label}",
            )

    def reset_morph_macros(self, session_id):
        session = self._session(session_id)
        with session.export_lock:
            self._require_no_pending_morph_authoring(session, include_baseline=True)
            data = self._required_morph_data(session)
            manual = self._retained_manual_values_locked(session)
            if not any(data.macro_values.values()):
                return self._result(session, "morph_reset_macros", status="noop"), data.state
            return self._set_morph_layers_locked(
                session, manual, {}, data.symmetry_enabled,
                action="morph_reset_macros", label="Reset Body Controls",
            )

    def set_morph_symmetry(self, session_id, enabled):
        if not isinstance(enabled, bool):
            raise ValueError("Link sides must be a boolean.")
        session = self._session(session_id)
        with session.export_lock:
            self._require_no_pending_morph_authoring(session, include_baseline=True)
            data = self._required_morph_data(session)
            manual = self._retained_manual_values_locked(session)
            if not mesh_morph_side_pairs(data.profile):
                raise ValueError("This profile has no supported left/right body controls.")
            if data.symmetry_enabled == enabled:
                return self._result(session, "morph_set_symmetry", status="noop"), data.state
            return self._set_morph_layers_locked(
                session, manual, data.macro_values, enabled,
                action="morph_set_symmetry", label="Link Body Sides" if enabled else "Unlink Body Sides",
            )

    def set_morph_side_value(self, session_id, pair_id, value, *, side="both", phase="end"):
        session = self._session(session_id)
        with session.export_lock:
            self._require_no_pending_morph_authoring(session, include_baseline=True)
            if str(phase or "end").lower() != "end":
                raise ValueError("Side controls accept completed slider changes only.")
            data = self._required_morph_data(session)
            manual = self._retained_manual_values_locked(session)
            updated = update_mesh_morph_side_values(data.profile, manual, str(pair_id or ""), value, side=side)
            if updated == manual:
                return self._result(session, "morph_set_side_value", status="noop"), data.state
            pair = next(item for item in mesh_morph_side_pairs(data.profile) if item.pair_id == pair_id)
            return self._set_morph_layers_locked(
                session, updated, data.macro_values, data.symmetry_enabled,
                action="morph_set_side_value", label=f"{pair.label} {str(side).title()}",
            )

    def _set_layered_manual_value_locked(self, session, definition, value, *, phase):
        if str(phase or "end").lower() != "end":
            raise ValueError("Manual sliders with body control layers accept completed changes only.")
        from cdmw.domain.mesh import clamp_morph_value
        data = self._required_morph_data(session)
        manual = self._retained_manual_values_locked(session)
        manual[definition.definition_id] = clamp_morph_value(definition, value)
        return self._set_morph_layers_locked(
            session, manual, data.macro_values, data.symmetry_enabled,
            action="morph_change", label=f"Morph {definition.label}",
        )

    def _apply_layered_morph_preset_locked(self, session, preset, diagnostics=()):
        data = self._required_morph_data(session)
        validate_mesh_morph_layers(data.profile, preset)

        def apply():
            report = self._run_morph_command_locked(
                session, "morph_apply_preset",
                {"preset_id": preset.preset_id, "values": dict(preset.values)},
                history_label=f"Apply Morph Preset {preset.name}", record_history=False,
            )
            self._install_morph_preset_layers_locked(session, preset)
            current = self._required_morph_data(session)
            current.preset_id = preset.preset_id
            current.diagnostics = tuple(dict.fromkeys((*current.diagnostics, *diagnostics)))
            return self._morph_result_and_state_locked(session, "morph_apply_preset", report)[0]

        return self._morph_authoring_transaction_locked(
            session, "morph_apply_preset", f"Apply Morph Preset {preset.name}", apply,
        )

    def _simple_layered_morph_command(self, session_id, command, label):
        session = self._session(session_id)
        with session.export_lock:
            self._require_no_pending_morph_authoring(session, include_baseline=True)

            def apply():
                report = self._run_morph_command_locked(
                    session, command, {}, history_label=label, record_history=False,
                )
                clear_morph_layers(self._required_morph_data(session))
                return self._morph_result_and_state_locked(session, command, report)[0]

            return self._morph_authoring_transaction_locked(session, command, label, apply)
