"""Where the translations come from: your own model, on your own key.

The studio could already rewrite any of the game's 187,521 lines by hand. What it could
not do was produce a translation, which is the actual job -- and no key of ours could
pay for 187,521 lines of it. So the provider is the user's: they paste a key, pick a
model, and the app is a client.

Three request shapes cover the field, and everything else is a base URL:

* **Anthropic** -- `POST /v1/messages`, `x-api-key`, response text in `content[]`.
* **OpenAI** -- `POST /v1/chat/completions`, bearer token, text in `choices[0].message`.
  OpenRouter, DeepSeek, Groq, Together, LM Studio and Ollama all speak this, so
  "OpenAI-compatible" is one preset with an editable base URL rather than eight.
* **Google Gemini** -- `POST /v1beta/models/<model>:generateContent`, key in the query,
  text in `candidates[0].content.parts[]`.

**Keys are not stored in the clear.** Windows will encrypt a blob against the logged-in
account for free through DPAPI, so the file in the workspace is useless to another
account and to anyone who copies it off the machine. Where DPAPI is unavailable the key
is written plainly and `is_encrypted` says so, because silently pretending otherwise
would be worse than the warning.

There is deliberately no OAuth here. A ChatGPT or Claude subscription login is not an API
credential -- neither provider issues API keys through a public OAuth flow -- so the only
honest options are a key you pasted or a local model that needs none.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional, Tuple

from .language_index import work_root

#: Request shapes. Every preset is one of these plus a base URL.
ANTHROPIC = "anthropic"
OPENAI = "openai"
GEMINI = "gemini"


@dataclass(frozen=True)
class ProviderPreset:
    """A provider the picker offers, and the defaults that go with it."""

    key: str
    label: str
    api: str
    base_url: str
    #: Suggestions only. The model id belongs to the provider, so the field stays editable
    #: and an empty default is more honest than a name that may have been retired.
    models: Tuple[str, ...] = ()
    model: str = ""
    model_hint: str = ""
    needs_key: bool = True
    note: str = ""


PRESETS: Tuple[ProviderPreset, ...] = (
    ProviderPreset(
        key="anthropic",
        label="Anthropic (Claude)",
        api=ANTHROPIC,
        base_url="https://api.anthropic.com",
        models=("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5", "claude-opus-4-8"),
        model="claude-sonnet-5",
        model_hint="e.g. claude-sonnet-5",
        note=(
            "Key from console.anthropic.com. Claude Opus 5 is the strongest and the "
            "dearest; Sonnet 5 is the balance most translation passes want, and Haiku "
            "4.5 is the cheapest."
        ),
    ),
    ProviderPreset(
        key="openai",
        label="OpenAI",
        api=OPENAI,
        base_url="https://api.openai.com",
        model_hint="the model id from your OpenAI dashboard",
        note=(
            "Key from platform.openai.com. Model ids change often enough that this field "
            "is left blank on purpose -- paste the one your account can reach."
        ),
    ),
    ProviderPreset(
        key="openai_compatible",
        label="OpenAI-compatible endpoint",
        api=OPENAI,
        base_url="",
        model_hint="the model id your endpoint serves",
        note=(
            "OpenRouter, DeepSeek, Groq, Together, Mistral, LM Studio and anything else "
            "that speaks /v1/chat/completions. Give the base URL without /v1."
        ),
    ),
    ProviderPreset(
        key="gemini",
        label="Google Gemini",
        api=GEMINI,
        base_url="https://generativelanguage.googleapis.com",
        model_hint="e.g. gemini-2.5-flash",
        note="Key from aistudio.google.com.",
    ),
    ProviderPreset(
        key="ollama",
        label="Ollama / LM Studio (local)",
        api=OPENAI,
        base_url="http://localhost:11434",
        model_hint="the model you have pulled, e.g. llama3.1",
        needs_key=False,
        note=(
            "A model running on this machine. No key and no network, but a local model "
            "translates the game's tone far less reliably than a hosted one."
        ),
    ),
)

PRESETS_BY_KEY = {preset.key: preset for preset in PRESETS}
DEFAULT_PRESET = PRESETS[0].key


def preset_for(key: str) -> ProviderPreset:
    return PRESETS_BY_KEY.get(str(key or ""), PRESETS[0])


# ------------------------------------------------------------------ key storage


def _dpapi(protect: bool, blob: bytes) -> Optional[bytes]:
    """CryptProtectData / CryptUnprotectData, or None where they are unavailable."""

    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:  # noqa: BLE001 - no ctypes is not an error worth raising here
        return None

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    source = _Blob(len(blob), ctypes.cast(ctypes.create_string_buffer(blob, len(blob)),
                                          ctypes.POINTER(ctypes.c_char)))
    result = _Blob()
    try:
        crypt32 = ctypes.windll.crypt32
        call = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
        ok = call(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result))
    except Exception:  # noqa: BLE001
        return None
    if not ok:
        return None
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        try:
            ctypes.windll.kernel32.LocalFree(result.pbData)
        except Exception:  # noqa: BLE001
            pass


def protect_secret(secret: str) -> Tuple[str, bool]:
    """`(stored form, was it encrypted)`. Never raises: a key is not worth a crash."""

    raw = str(secret or "").encode("utf-8")
    if not raw:
        return "", True
    sealed = _dpapi(True, raw)
    if sealed is not None:
        return "dpapi:" + base64.b64encode(sealed).decode("ascii"), True
    return "plain:" + base64.b64encode(raw).decode("ascii"), False


def unprotect_secret(stored: str) -> str:
    text = str(stored or "")
    if not text:
        return ""
    prefix, _, payload = text.partition(":")
    try:
        blob = base64.b64decode(payload.encode("ascii"), validate=True)
    except Exception:  # noqa: BLE001
        return ""
    if prefix == "plain":
        return blob.decode("utf-8", errors="replace")
    if prefix == "dpapi":
        opened = _dpapi(False, blob)
        return opened.decode("utf-8", errors="replace") if opened else ""
    return ""


# ------------------------------------------------------------------- the config


@dataclass
class ProviderConfig:
    """Everything a request needs, plus how hard to push the provider."""

    preset: str = DEFAULT_PRESET
    base_url: str = ""
    model: str = ""
    api_key: str = ""
    #: Lines per request. Small batches waste the prompt; huge ones lose lines.
    batch_size: int = 20
    #: Requests in flight. More is faster until the provider starts answering 429.
    parallel: int = 2
    timeout: int = 120
    max_tokens: int = 8192
    #: Claude 4.6+ thinks by default, which a translation pass pays for and rarely needs.
    disable_thinking: bool = True
    #: True when the key on disk is encrypted to this Windows account.
    key_is_encrypted: bool = True

    @property
    def api(self) -> str:
        return preset_for(self.preset).api

    @property
    def needs_key(self) -> bool:
        return preset_for(self.preset).needs_key

    def resolved_base_url(self) -> str:
        base = str(self.base_url or "").strip() or preset_for(self.preset).base_url
        return base.rstrip("/")

    def problems(self) -> Tuple[str, ...]:
        """What still stops this config from making a request."""

        out = []
        if not self.resolved_base_url():
            out.append("no base URL")
        if not str(self.model or "").strip():
            out.append("no model")
        if self.needs_key and not str(self.api_key or "").strip():
            out.append("no API key")
        return tuple(out)

    @property
    def is_ready(self) -> bool:
        return not self.problems()


def config_path() -> Path:
    return work_root() / "ai_provider.json"


def load_config() -> ProviderConfig:
    try:
        payload = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ProviderConfig()
    if not isinstance(payload, dict):
        return ProviderConfig()
    blank = ProviderConfig()

    def _int(name: str, fallback: int, low: int, high: int) -> int:
        try:
            return max(low, min(high, int(payload.get(name, fallback))))
        except (TypeError, ValueError):
            return fallback

    stored_key = str(payload.get("api_key") or "")
    return ProviderConfig(
        preset=str(payload.get("preset") or blank.preset),
        base_url=str(payload.get("base_url") or ""),
        model=str(payload.get("model") or ""),
        api_key=unprotect_secret(stored_key),
        batch_size=_int("batch_size", blank.batch_size, 1, 200),
        parallel=_int("parallel", blank.parallel, 1, 16),
        timeout=_int("timeout", blank.timeout, 10, 900),
        max_tokens=_int("max_tokens", blank.max_tokens, 256, 128_000),
        disable_thinking=bool(payload.get("disable_thinking", blank.disable_thinking)),
        key_is_encrypted=not stored_key.startswith("plain:"),
    )


def save_config(config: ProviderConfig) -> ProviderConfig:
    """Write the config and return it with `key_is_encrypted` telling the truth.

    A key that cannot be protected is not written at all. The fallback used to
    store `plain:<base64>`, which is encoding rather than encryption: anyone who
    could read the file could read the key, and the warning the panel showed did
    not change that. Everything else in the config still saves; the key stays in
    memory for the session and has to be entered again next time, which is the
    price of not leaving a credential readable on disk.
    """

    stored_key, encrypted = protect_secret(config.api_key)
    if not encrypted:
        stored_key = ""
    payload = {
        "preset": config.preset,
        "base_url": config.base_url,
        "model": config.model,
        "api_key": stored_key,
        "batch_size": int(config.batch_size),
        "parallel": int(config.parallel),
        "timeout": int(config.timeout),
        "max_tokens": int(config.max_tokens),
        "disable_thinking": bool(config.disable_thinking),
    }
    target = config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch = target.with_suffix(".json.tmp")
    scratch.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    scratch.replace(target)
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass
    return replace(config, key_is_encrypted=encrypted)


__all__ = [
    "ANTHROPIC",
    "DEFAULT_PRESET",
    "GEMINI",
    "OPENAI",
    "PRESETS",
    "ProviderConfig",
    "ProviderPreset",
    "config_path",
    "load_config",
    "preset_for",
    "protect_secret",
    "save_config",
    "unprotect_secret",
]
