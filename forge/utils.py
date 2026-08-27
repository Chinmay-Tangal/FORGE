"""
forge/utils.py — Shared utility helpers.

Contains lightweight helpers shared across multiple forge modules.
Keep this module free of forge-internal imports to avoid circular dependencies.
"""
from __future__ import annotations


def count_tokens(text: str) -> int:
    """
    Rough token estimate without a tokenizer dependency.

    Uses a 1.3 word-per-token multiplier — accurate enough for
    triggering context eviction on local hardware.
    """
    return int(len(text.split()) * 1.3)
