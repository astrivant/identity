"""
Expose credential-safe storage failures at the package boundary.
"""

from __future__ import annotations

__all__ = ["StorageError"]


class StorageError(RuntimeError):
    """
    Report an invalid backend or database failure without exposing connection credentials.
    """
