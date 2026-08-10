from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from cdmw.domain.localization import plural_rule_for_code
from cdmw.ui.mesh_editor.process_io import DOTNET_PROTOCOL_LINE_LIMIT


class DotNetPreviewSessionLocalizationMixin:
    @staticmethod
    def _localization_manifest_hash(keys: Sequence[str]) -> str:
        encoded = "\n".join(sorted(str(key) for key in keys)).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _localization_payload_values(
        self,
    ) -> tuple[str, str, int, dict[str, object], str]:
        keys = self._localization_keys
        localizer = self._ui_localizer
        snapshot_method = getattr(localizer, "translation_snapshot", None)
        if callable(snapshot_method):
            language_code = str(
                getattr(localizer, "language_code", "en") or "en"
            )
            try:
                revision = max(0, int(getattr(localizer, "revision", 0) or 0))
            except (TypeError, ValueError, OverflowError):
                revision = 0
            snapshot = dict(
                snapshot_method(
                    keys,
                    max_keys=10_000,
                    max_bytes=DOTNET_PROTOCOL_LINE_LIMIT - (16 * 1024),
                )
            )
        else:
            from cdmw.ui.localization_catalogs_v2 import builtin_translation_entries

            language_code = "en"
            revision = 0
            english = builtin_translation_entries("en")
            snapshot = {
                source: (
                    str(english[source])
                    if isinstance(english.get(source), str)
                    else dict(english[source])  # type: ignore[arg-type]
                )
                for source in keys
                if source in english
            }
        if set(snapshot) != set(keys):
            missing = sorted(set(keys) - set(snapshot))
            raise ValueError(
                "Helper localization keys are absent from the host catalog: "
                + ", ".join(missing[:3])
            )
        from cdmw.ui.localization_catalogs_v2 import translation_catalog_hash

        catalog_hash = translation_catalog_hash(
            language_code,
            snapshot,  # type: ignore[arg-type]
            keys=keys,
        )
        return (
            language_code,
            plural_rule_for_code(language_code),
            revision,
            snapshot,
            catalog_hash,
        )

    def _send_ui_localization_state(self) -> bool:
        if not self._protocol_ready or not self._localization_keys:
            return False
        try:
            (
                language_code,
                plural_rule,
                revision,
                translations,
                catalog_hash,
            ) = self._localization_payload_values()
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            self._fail_current_process(
                f".NET/Vortice localization payload was rejected by the host: {exc}",
                static_failure=True,
            )
            return False
        self._localization_request_id += 1
        request_id = self._localization_request_id
        correlation: dict[str, object] = {
            "language_code": language_code,
            "plural_rule": plural_rule,
            "catalog_hash": catalog_hash,
            "key_manifest_hash": self._localization_key_manifest_hash,
            "session_id": self._session_id,
            "process_generation": self._process_generation,
            "request_id": request_id,
            "localization_revision": revision,
        }
        message = {
            "event": "ui_localization_state",
            **correlation,
            "translations": translations,
        }
        encoded = (
            json.dumps(message, ensure_ascii=False, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        if len(encoded) > DOTNET_PROTOCOL_LINE_LIMIT:
            self._fail_current_process(
                ".NET/Vortice localization payload exceeded the protocol line limit.",
                static_failure=True,
            )
            return False
        if not self._send_json(message):
            return False
        self._pending_localization = correlation
        return True

    @staticmethod
    def _localization_ack_matches(
        payload: Mapping[str, object],
        expected: Mapping[str, object],
    ) -> bool:
        for field in (
            "language_code",
            "plural_rule",
            "catalog_hash",
            "key_manifest_hash",
            "session_id",
        ):
            if str(payload.get(field, "") or "") != str(expected.get(field, "") or ""):
                return False
        for field in (
            "process_generation",
            "request_id",
            "localization_revision",
        ):
            try:
                actual_number = int(payload.get(field, -1))
                expected_number = int(expected.get(field, -1))
            except (TypeError, ValueError, OverflowError):
                return False
            if actual_number != expected_number:
                return False
        return True

    def _handle_ui_localization_ack(
        self,
        payload: Mapping[str, object],
    ) -> None:
        expected = self._pending_localization
        if expected is None or not self._localization_ack_matches(payload, expected):
            return
        status = str(payload.get("status", "") or "").strip().lower()
        if status != "applied":
            detail = str(payload.get("reason", "") or status or "rejected")
            self._fail_current_process(
                f".NET/Vortice localization acknowledgement was rejected: {detail}",
                static_failure=True,
            )
            return
        self._pending_localization = None
        self._localization_initial_established = True
        self._localization_applied_revision = int(
            expected["localization_revision"]
        )
        self.localization_applied.emit(
            str(expected["language_code"]),
            self._localization_applied_revision,
        )
        self._announce_renderer_ready()
        self._maybe_finish_launch()


__all__ = ["DotNetPreviewSessionLocalizationMixin"]
