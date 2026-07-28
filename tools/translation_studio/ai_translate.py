"""Turning a filtered set of lines into a translation, without breaking the markup.

The risky part of machine-translating a game is not the prose, it is the tokens inside
it. `<br/>` appears 23,751 times in the English table, `{Key:Key_Skill_1}` 824 times,
`{Money:Money_Copper:1}` 246 -- and a model that helpfully renders `{Key:Key_Roll}` as
`{Taste:Taste_Rollen}` produces a line that reads fine in the editor and shows a literal
brace-string in the game. So every request carries the tokens' inviolability in its
instructions *and* every reply is checked against the source before it is accepted: same
tokens, same number of each, or the line is reported rather than applied.

The rest is shaped by cost. Lines go up in batches because one request per line would
re-send the instructions 187,521 times; batches carry a numeric id per line so a reply
can arrive incomplete or out of order and still land on the right rows; and requests run
a few at a time, with backoff on 429, because every provider meters something.

Nothing here imports Qt or touches a widget: `ai_panel.py` drives it, and the tests drive
it through a fake transport instead of the network.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

from .ai_provider import ANTHROPIC, GEMINI, ProviderConfig

#: Markup that must survive translation byte for byte. Angle tags (`<br/>`), brace tokens
#: (`{Key:...}`, `{Money:...}`, `{emoji:...}`, `{Param0}`), printf-style slots, and the
#: `[EMPTY]` sentinel -- which is a marker, unlike `[Effect]`, which is prose.
_TOKEN = re.compile(r"<[^<>]{0,120}>|\{[^{}]{0,120}\}|%\d{1,3}|%[sdif]|\[EMPTY\]")

#: Characters of source text per request, whatever the line count says. A batch of 20
#: quest paragraphs is a different animal from a batch of 20 item names.
_MAX_BATCH_CHARS = 6000


def tokens(text: str) -> Tuple[str, ...]:
    return tuple(sorted(_TOKEN.findall(str(text or ""))))


def token_mismatch(source: str, translated: str) -> Tuple[str, ...]:
    """Tokens whose count differs between the two, empty when the markup survived."""

    before, after = list(tokens(source)), list(tokens(translated))
    if before == after:
        return ()
    changed = set()
    for token in set(before) | set(after):
        if before.count(token) != after.count(token):
            changed.add(token)
    return tuple(sorted(changed))


# ------------------------------------------------------------------- batching


@dataclass(frozen=True)
class Line:
    """One line on its way to the model."""

    index: int
    text: str
    context: str = ""


def build_batches(
    lines: Sequence[Line], *, batch_size: int, max_chars: int = _MAX_BATCH_CHARS
) -> Tuple[Tuple[Line, ...], ...]:
    """Group lines into requests, capped by count and by characters."""

    size = max(1, int(batch_size))
    out: List[Tuple[Line, ...]] = []
    current: List[Line] = []
    used = 0
    for line in lines:
        cost = len(line.text) + 32
        if current and (len(current) >= size or used + cost > max_chars):
            out.append(tuple(current))
            current, used = [], 0
        current.append(line)
        used += cost
    if current:
        out.append(tuple(current))
    return tuple(out)


# --------------------------------------------------------------------- prompt


@dataclass(frozen=True)
class TranslationBrief:
    """What the user asked for, in the words the model gets."""

    target_language: str
    source_language: str = ""
    instructions: str = ""

    def system_prompt(self) -> str:
        source = self.source_language.strip() or "the source language"
        return (
            f"You are translating in-game text for the video game Crimson Desert, from "
            f"{source} into {self.target_language.strip()}.\n"
            "\n"
            "Rules:\n"
            "- Translate the meaning, not the words. These are quest lines, item names, "
            "dialogue and UI strings; keep the register and tone of the original.\n"
            "- Preserve every markup token exactly, character for character, and keep the "
            "same number of each: angle tags such as <br/>, brace tokens such as "
            "{Key:Key_Roll}, {Money:Money_Copper:1}, {emoji:cd_icon_x} and {Param0}, "
            "printf slots such as %1, and the literal [EMPTY]. Never translate, reorder, "
            "reformat or drop what is inside them.\n"
            "- Keep the translation close to the original in length. It has to fit the "
            "same interface.\n"
            "- A line that is empty, numeric, or nothing but markup comes back unchanged.\n"
            "- Return the translation only: no notes, no commentary, no explanations, and "
            "no internal or system XML tags.\n"
            + (f"- {self.instructions.strip()}\n" if self.instructions.strip() else "")
            + "\n"
            "Answer with a JSON array and nothing else, one object per input line, using "
            'the id you were given: [{"i": 0, "t": "..."}, {"i": 1, "t": "..."}]'
        )

    def user_prompt(self, batch: Sequence[Line]) -> str:
        payload = []
        for line in batch:
            item: Dict[str, object] = {"i": line.index, "s": line.text}
            if line.context:
                item["c"] = line.context
            payload.append(item)
        return (
            f"Translate these {len(batch)} lines into {self.target_language.strip()}. "
            'Reply with the JSON array only.\n\n'
            + json.dumps(payload, ensure_ascii=False)
        )


# -------------------------------------------------------------------- requests


@dataclass(frozen=True)
class HttpRequest:
    url: str
    headers: Mapping[str, str]
    body: bytes


class ProviderError(RuntimeError):
    """A request failed. `retryable` says whether trying again could help."""

    def __init__(self, message: str, *, retryable: bool = False, retry_after: float = 0.0):
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after


def build_request(config: ProviderConfig, system: str, user: str) -> HttpRequest:
    """The one place the three request shapes differ."""

    base = config.resolved_base_url()
    model = str(config.model or "").strip()
    key = str(config.api_key or "").strip()
    api = config.api

    if api == ANTHROPIC:
        body: Dict[str, object] = {
            "model": model,
            "max_tokens": int(config.max_tokens),
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if config.disable_thinking:
            # Claude 4.6+ thinks by default. A translation pass pays for that and rarely
            # needs it; on an older model the provider rejects the field and says so.
            body["thinking"] = {"type": "disabled"}
        headers = {
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if key:
            headers["x-api-key"] = key
        return HttpRequest(f"{base}/v1/messages", headers, _encode(body))

    if api == GEMINI:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "maxOutputTokens": int(config.max_tokens),
                "responseMimeType": "application/json",
            },
        }
        headers = {"content-type": "application/json"}
        if key:
            # The header form, not `?key=`, so the secret never lands in a URL.
            headers["x-goog-api-key"] = key
        return HttpRequest(
            f"{base}/v1beta/models/{model}:generateContent", headers, _encode(body)
        )

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    headers = {"content-type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return HttpRequest(f"{base}/v1/chat/completions", headers, _encode(body))


def _encode(body: Mapping[str, object]) -> bytes:
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def extract_text(api: str, payload: Mapping[str, object]) -> str:
    """The assistant's text, wherever this provider keeps it."""

    if api == ANTHROPIC:
        parts = [
            str(block.get("text") or "")
            for block in payload.get("content") or []
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "".join(parts)
    if api == GEMINI:
        candidates = payload.get("candidates") or []
        if not candidates or not isinstance(candidates[0], dict):
            return ""
        content = candidates[0].get("content") or {}
        parts = content.get("parts") or [] if isinstance(content, dict) else []
        return "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict))
    choices = payload.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content") if isinstance(message, dict) else ""
    if isinstance(content, list):
        return "".join(
            str(part.get("text") or "") for part in content if isinstance(part, dict)
        )
    return str(content or "")


def describe_error(status: int, body: bytes) -> str:
    """A provider's own words when it has them, the status line when it does not."""

    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except ValueError:
        payload = None
    message = ""
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or error.get("type") or "")
        elif isinstance(error, str):
            message = error
        if not message:
            message = str(payload.get("message") or "")
    if not message:
        message = body.decode("utf-8", errors="replace")[:200].strip()
    return f"HTTP {status}: {message}" if message else f"HTTP {status}"


# -------------------------------------------------------------------- parsing


def parse_translations(text: str) -> Dict[int, str]:
    """`{id: translation}` from whatever the model actually said.

    Models fence JSON, preface it, or answer with an object instead of an array. All of
    that is recoverable; only a reply with no JSON in it at all is a failure.
    """

    raw = str(text or "").strip()
    if not raw:
        return {}
    parsed = _first_json(raw)
    if parsed is None:
        raise ProviderError("the reply contained no JSON")
    out: Dict[int, str] = {}
    if isinstance(parsed, dict):
        entries: Iterable = parsed.get("translations") or parsed.get("lines") or []
        if not entries:
            for key, value in parsed.items():
                try:
                    out[int(key)] = str(value)
                except (TypeError, ValueError):
                    continue
            return out
    else:
        entries = parsed
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        identifier = entry.get("i", entry.get("id", entry.get("index")))
        value = entry.get("t", entry.get("text", entry.get("translation")))
        if identifier is None or value is None:
            continue
        try:
            out[int(identifier)] = str(value)
        except (TypeError, ValueError):
            continue
    return out


def _first_json(raw: str):
    if raw.startswith("```"):
        raw = raw.split("```")[1] if "```" in raw[3:] else raw.lstrip("`")
        raw = raw.split("\n", 1)[-1] if raw[:20].strip().lower().startswith("json") else raw
    for opener, closer in (("[", "]"), ("{", "}")):
        start = raw.find(opener)
        end = raw.rfind(closer)
        if start < 0 or end <= start:
            continue
        try:
            return json.loads(raw[start:end + 1])
        except ValueError:
            continue
    return None


__all__ = [
    "HttpRequest",
    "Line",
    "ProviderError",
    "TranslationBrief",
    "build_batches",
    "build_request",
    "describe_error",
    "extract_text",
    "parse_translations",
    "token_mismatch",
    "tokens",
]
