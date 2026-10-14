"""
Retain the original storage exception import path for existing callers.
"""

from __future__ import annotations

from witful.exceptions import StorageError

__all__ = ["StorageError"]
