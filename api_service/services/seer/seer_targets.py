"""Lightweight Seer target identifiers (no heavy service imports)."""

from typing import Any

VALID_TARGETS = frozenset({"primary", "secondary"})


def normalize_seer_target(value: Any) -> str:
    """
    Normalize a user-supplied Seer target identifier.

    Args:
        value: Raw target value from config or API input.

    Returns:
        ``primary`` or ``secondary``.
    """
    target = str(value or "primary").strip().lower()
    return target if target in VALID_TARGETS else "primary"
