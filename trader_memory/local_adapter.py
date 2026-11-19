"""
Local Adapter - separated for clarity.
"""

from .store import LocalAdapter, MemoryBackend, SetupRecord
from typing import Any

__all__ = ["LocalAdapter"]