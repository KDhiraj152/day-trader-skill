"""
GBrain Adapter - separated for clarity.
This is imported by store.py, but can be used directly if needed.
"""

from .store import GBrainAdapter, MemoryBackend, SetupRecord
from typing import Any

__all__ = ["GBrainAdapter"]