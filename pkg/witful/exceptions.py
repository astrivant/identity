"""
Define public package exceptions independently of their implementation modules.
"""

from __future__ import annotations

__all__ = ["SleeveError", "StorageError", "StorageProtectionError"]


class SleeveError(ValueError):
    """
    Report an actionable lifecycle failure without private Git output or source values.
    """


class StorageError(RuntimeError):
    """
    Report an invalid backend or database failure without exposing connection credentials.
    """


class StorageProtectionError(ValueError):
    """
    Reject private processing when its working filesystem cannot be verified.
    """
