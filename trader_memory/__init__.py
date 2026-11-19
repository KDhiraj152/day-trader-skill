"""
Unified Memory Layer for Trader Skills
=======================================
Detects GBrain availability and uses it as primary memory layer.
Falls back to local JSON files (trader/memory/) if GBrain unavailable.

Usage in any skill:
    from trader_memory import MemoryStore, get_memory
    mem = get_memory()  # or MemoryStore()
    
    # Store a setup outcome
    mem.store_setup(symbol, setup_type, features, outcome)
    
    # Retrieve similar setups
    similar = mem.get_similar(setup_type, features, k=5)
    
    # Store/retrieve any key-value
    mem.put(key, value, namespace="trader")
    val = mem.get(key, namespace="trader")

Configuration (trader/config.json):
    {
        "memory": {
            "backend": "auto",        # "gbrain" | "local" | "auto"
            "gbrain_namespace": "default",
            "local_path": "trader/memory",
            "embedding_model": "sentence-transformers/all-MiniLM-L6-v2"
        }
    }
"""

from .store import MemoryStore, SetupRecord, MemoryBackend, get_memory
from .gbrain_adapter import GBrainAdapter
from .local_adapter import LocalAdapter

__all__ = ["MemoryStore", "SetupRecord", "MemoryBackend", "GBrainAdapter", "LocalAdapter", "get_memory"]