"""
Define public package exceptions independently of their implementation modules.
"""

from __future__ import annotations

from typing import Literal

__all__ = ["CollectionConfigurationError", "NativeError", "SetupError", "SleeveError", "StorageError", "StorageProtectionError"]


class SetupError(ValueError):
    """
    Report an operator setup failure using fixed diagnostics without provider output or credentials.
    """


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


class CollectionConfigurationError(ValueError):
    """
    Reject invalid collection input without reflecting raw schema-validation diagnostics.
    """


NativeCode = Literal["invalid", "denied", "conflict", "diverged", "unknown", "unavailable", "incomplete", "unsupported"]


class NativeError(StorageError):
    """
    Report a closed native-operation category without reflecting record, key or connection details.

    """

    def __init__(self, code: NativeCode) -> None:
        """
        Keep diagnostic text independent of rejected input and provider diagnostics.

        Args:
            code (NativeCode): Fixed outcome category.
        """
        self.code = code
        super().__init__(f"Native operation {code}")
