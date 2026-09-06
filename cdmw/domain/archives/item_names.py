"""Presentation of archive name sets; the full value remains searchable."""


def compact_item_name(value: str) -> str:
    names = tuple(dict.fromkeys(part.strip() for part in str(value or "").split(" / ") if part.strip()))
    return f"Shared asset ({len(names)} names)" if len(names) > 1 else str(value or "")
