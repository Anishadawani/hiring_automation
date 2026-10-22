"""Small helpers for building safe search queries."""


def escape_like(value: str) -> str:
    """Escape LIKE wildcards so user input like '%' or '_' is matched literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def contains_pattern(value: str) -> str:
    return f"%{escape_like(value.strip())}%"