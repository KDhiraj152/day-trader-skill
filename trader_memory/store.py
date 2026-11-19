"""
Core MemoryStore - unified interface for GBrain and local backends.
"""

from __future__ import annotations
import json
import os
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Optional

# Optional imports - handle gracefully
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    np = None


@dataclass
class SetupRecord:
    """A recorded trading setup with features and outcome."""
    # Identity
    record_id: str
    timestamp: float                    # Unix epoch
    symbol: str
    setup_type: str                     # "orb", "bull_flag", "reclaim_ma20", "oversold_bounce", etc.
    
    # Features (for similarity search)
    features: dict                      # e.g., {"or_range_pct": 2.1, "volume_ratio": 1.3, "rsi": 28, "regime": "trending"}
    
    # Outcome
    outcome: str                        # "target_first", "stop_first", "neither", "open"
    r_multiple: float                   # Actual R achieved (negative if stop hit)
    duration_bars: int                  # Bars from entry to exit
    exit_reason: str                    # "target", "stop", "flat_by", "manual"
    
    # Context
    entry_price: float
    stop_price: float
    target_price: float
    position_size: int
    max_loss_usd: float
    
    # Metadata
    skill_version: str = "1.0"
    tags: list[str] = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []
        if self.record_id is None:
            self.record_id = str(uuid.uuid4())[:8]
        if self.timestamp is None:
            self.timestamp = time.time()
    
    def to_embedding_text(self) -> str:
        """Text representation for embedding - includes all searchable features."""
        parts = [
            f"symbol:{self.symbol}",
            f"setup:{self.setup_type}",
            f"outcome:{self.outcome}",
        ]
        for k, v in self.features.items():
            if isinstance(v, (int, float)):
                parts.append(f"{k}:{v:.3f}")
            else:
                parts.append(f"{k}:{v}")
        return " | ".join(parts)
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, d: dict) -> SetupRecord:
        return cls(**d)


class MemoryBackend(ABC):
    """Abstract backend for memory storage and retrieval."""
    
    @abstractmethod
    def initialize(self, config: dict) -> bool:
        """Returns True if backend is ready."""
        pass
    
    @abstractmethod
    def store_setup(self, record: SetupRecord) -> bool:
        pass
    
    @abstractmethod
    def get_similar(self, setup_type: str, features: dict, k: int = 5) -> list[SetupRecord]:
        """Retrieve k most similar setup records."""
        pass
    
    @abstractmethod
    def get_recent(self, symbol: str, setup_type: str, limit: int = 20) -> list[SetupRecord]:
        pass
    
    @abstractmethod
    def put(self, key: str, value: Any, namespace: str = "trader") -> bool:
        pass
    
    @abstractmethod
    def get(self, key: str, namespace: str = "trader") -> Any:
        pass
    
    @abstractmethod
    def health_check(self) -> dict:
        """Returns {'healthy': bool, 'backend': str, 'details': str}"""
        pass


class MemoryStore:
    """
    Unified memory interface. Automatically selects backend.
    
    Backend priority (when config.backend == "auto"):
    1. GBrain (if available and configured)
    2. Local JSON files (always available)
    """
    
    def __init__(self, config_path: str = None):
        self.config = self._load_config(config_path)
        self.backend: MemoryBackend = None
        self._init_backend()
    
    def _load_config(self, config_path: str) -> dict:
        default = {
            "memory": {
                "backend": "auto",
                "gbrain_namespace": "default",
                "local_path": "trader/memory",
                "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
                "similarity_threshold": 0.7,
                "max_records_per_symbol": 1000
            }
        }
        if config_path and Path(config_path).exists():
            with open(config_path) as f:
                user = json.load(f)
                default["memory"].update(user.get("memory", {}))
        return default["memory"]
    
    def _init_backend(self):
        backend_name = self.config["backend"]
        
        if backend_name in ("auto", "gbrain"):
            # Try GBrain first
            gbrain = GBrainAdapter(self.config)
            if gbrain.initialize(self.config):
                self.backend = gbrain
                return
        
        # Fallback to local
        if backend_name in ("auto", "local"):
            self.backend = LocalAdapter(self.config)
            self.backend.initialize(self.config)
            return
        
        raise ValueError(f"Unknown memory backend: {backend_name}")
    
    # --- Public API ---
    
    def store_setup(self, 
                    symbol: str,
                    setup_type: str,
                    features: dict,
                    outcome: str,
                    r_multiple: float,
                    duration_bars: int,
                    exit_reason: str,
                    entry_price: float,
                    stop_price: float,
                    target_price: float,
                    position_size: int,
                    max_loss_usd: float,
                    tags: list[str] = None) -> bool:
        """Record a completed setup outcome."""
        record = SetupRecord(
            record_id=str(uuid.uuid4())[:8],
            timestamp=time.time(),
            symbol=symbol.upper(),
            setup_type=setup_type,
            features=features,
            outcome=outcome,
            r_multiple=r_multiple,
            duration_bars=duration_bars,
            exit_reason=exit_reason,
            entry_price=entry_price,
            stop_price=stop_price,
            target_price=target_price,
            position_size=position_size,
            max_loss_usd=max_loss_usd,
            tags=tags or []
        )
        return self.backend.store_setup(record)
    
    def get_similar(self, setup_type: str, features: dict, k: int = 5) -> list[SetupRecord]:
        """Find k most similar historical setups."""
        return self.backend.get_similar(setup_type, features, k)
    
    def get_recent(self, symbol: str, setup_type: str, limit: int = 20) -> list[SetupRecord]:
        return self.backend.get_recent(symbol, setup_type, limit)
    
    def put(self, key: str, value: Any, namespace: str = "trader") -> bool:
        return self.backend.put(key, value, namespace)
    
    def get(self, key: str, namespace: str = "trader") -> Any:
        return self.backend.get(key, namespace)
    
    def health_check(self) -> dict:
        return self.backend.health_check()
    
    @property
    def backend_name(self) -> str:
        return self.backend.__class__.__name__


# --- GBrain Adapter ---
class GBrainAdapter(MemoryBackend):
    """GBrain backend using MCP tools."""
    
    def __init__(self, config: dict):
        self.config = config
        self.namespace = config.get("gbrain_namespace", "default")
        self._client = None
        self._available = False
    
    def initialize(self, config: dict) -> bool:
        """Try to connect to GBrain via MCP."""
        try:
            # Check if we're in an environment with GBrain MCP
            # This works when running inside OpenCode/Hermes with GBrain connected
            import subprocess
            result = subprocess.run(
                ["opencode", "mcp", "list"],
                capture_output=True, text=True, timeout=5
            )
            if "gbrain" not in result.stdout.lower():
                return False
            
            # Test a simple query
            test_result = subprocess.run(
                ["opencode", "mcp", "call", "gbrain", "get_brain_health"],
                capture_output=True, text=True, timeout=10
            )
            if test_result.returncode == 0:
                self._available = True
                return True
        except Exception:
            pass
        return False
    
    def _call_gbrain(self, tool: str, args: dict) -> Any:
        """Call GBrain MCP tool via opencode CLI."""
        import subprocess
        import json
        cmd = ["opencode", "mcp", "call", "gbrain", tool, json.dumps(args)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"GBrain {tool} failed: {result.stderr}")
        return json.loads(result.stdout)
    
    def store_setup(self, record: SetupRecord) -> bool:
        if not self._available:
            return False
        try:
            # Store as a page in GBrain
            slug = f"trader/setups/{record.symbol}/{record.setup_type}/{record.record_id}"
            content = f"""---
type: trader_setup
symbol: {record.symbol}
setup_type: {record.setup_type}
outcome: {record.outcome}
r_multiple: {record.r_multiple}
duration_bars: {record.duration_bars}
exit_reason: {record.exit_reason}
entry_price: {record.entry_price}
stop_price: {record.stop_price}
target_price: {record.target_price}
position_size: {record.position_size}
max_loss_usd: {record.max_loss_usd}
timestamp: {record.timestamp}
tags: {record.tags}
---

# Setup Record: {record.record_id}

**Symbol:** {record.symbol}  
**Setup:** {record.setup_type}  
**Outcome:** {record.outcome} ({record.r_multiple:.2f}R)  
**Duration:** {record.duration_bars} bars  
**Exit:** {record.exit_reason}

## Features
```json
{json.dumps(record.features, indent=2)}
```

## Embedding Text
```
{record.to_embedding_text()}
```
"""
            self._call_gbrain("put_page", {
                "slug": slug,
                "content": content,
                "source_id": self.namespace
            })
            return True
        except Exception as e:
            print(f"[GBrain] Store failed: {e}")
            return False
    
    def get_similar(self, setup_type: str, features: dict, k: int = 5) -> list[SetupRecord]:
        if not self._available:
            return []
        try:
            # Build query text from features
            query_parts = [f"setup:{setup_type}"]
            for fk, fv in features.items():
                if isinstance(fv, (int, float)):
                    query_parts.append(f"{fk}:{fv:.3f}")
                else:
                    query_parts.append(f"{fk}:{fv}")
            query = " | ".join(query_parts)
            
            result = self._call_gbrain("search", {
                "query": query,
                "limit": k * 3,  # Get more, filter by type
                "source_ids": [self.namespace]
            })
            
            records = []
            for item in result.get("items", []):
                if item.get("type") == "trader_setup":
                    # Fetch full page
                    page = self._call_gbrain("get_page", {
                        "slug": item["slug"],
                        "include_content": True,
                        "source_id": self.namespace
                    })
                    # Parse content back to record (simplified)
                    rec = self._parse_page(page)
                    if rec:
                        records.append(rec)
            
            # Sort by similarity (GBrain returns ranked)
            return records[:k]
        except Exception as e:
            print(f"[GBrain] Search failed: {e}")
            return []
    
    def _parse_page(self, page: dict) -> SetupRecord | None:
        """Parse GBrain page content back to SetupRecord."""
        try:
            content = page.get("content", "")
            # Extract frontmatter
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    import yaml
                    frontmatter = yaml.safe_load(parts[1])
                    return SetupRecord(
                        record_id=frontmatter.get("record_id", page.get("slug", "").split("/")[-1]),
                        timestamp=frontmatter.get("timestamp", 0),
                        symbol=frontmatter.get("symbol", ""),
                        setup_type=frontmatter.get("setup_type", ""),
                        features={},  # Would need to parse from content
                        outcome=frontmatter.get("outcome", ""),
                        r_multiple=frontmatter.get("r_multiple", 0),
                        duration_bars=frontmatter.get("duration_bars", 0),
                        exit_reason=frontmatter.get("exit_reason", ""),
                        entry_price=frontmatter.get("entry_price", 0),
                        stop_price=frontmatter.get("stop_price", 0),
                        target_price=frontmatter.get("target_price", 0),
                        position_size=frontmatter.get("position_size", 0),
                        max_loss_usd=frontmatter.get("max_loss_usd", 0),
                        tags=frontmatter.get("tags", [])
                    )
        except Exception:
            pass
        return None
    
    def get_recent(self, symbol: str, setup_type: str, limit: int = 20) -> list[SetupRecord]:
        # Use search with symbol + setup filter
        return self.get_similar(setup_type, {"symbol": symbol}, limit)
    
    def put(self, key: str, value: Any, namespace: str = "trader") -> bool:
        if not self._available:
            return False
        try:
            slug = f"trader/kv/{namespace}/{key}"
            content = f"""---
type: trader_kv
key: {key}
namespace: {namespace}
---

```json
{json.dumps(value, indent=2)}
```"""
            self._call_gbrain("put_page", {
                "slug": slug,
                "content": content,
                "source_id": self.namespace
            })
            return True
        except Exception:
            return False
    
    def get(self, key: str, namespace: str = "trader") -> Any:
        if not self._available:
            return None
        try:
            slug = f"trader/kv/{namespace}/{key}"
            page = self._call_gbrain("get_page", {
                "slug": slug,
                "include_content": True,
                "source_id": self.namespace
            })
            content = page.get("content", "")
            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0]
                return json.loads(json_str)
        except Exception:
            pass
        return None
    
    def health_check(self) -> dict:
        return {
            "healthy": self._available,
            "backend": "GBrain",
            "details": "Connected via MCP" if self._available else "Not available"
        }


# --- Local JSON Adapter ---
class LocalAdapter(MemoryBackend):
    """Local file-based backend using JSON + optional FAISS for similarity."""
    
    def __init__(self, config: dict):
        self.config = config
        self.base_path = Path(config.get("local_path", "trader/memory"))
        self.setups_path = self.base_path / "setups"
        self.kv_path = self.base_path / "kv"
        self._faiss_index = None
        self._embedding_model = None
        self._record_cache = []
    
    def initialize(self, config: dict) -> bool:
        self.setups_path.mkdir(parents=True, exist_ok=True)
        self.kv_path.mkdir(parents=True, exist_ok=True)
        
        # Try to load FAISS for similarity search
        try:
            import faiss
            from sentence_transformers import SentenceTransformer
            model_name = config.get("embedding_model", "sentence-transformers/all-MiniLM-L6-v2")
            self._embedding_model = SentenceTransformer(model_name)
            self._faiss_index = faiss.IndexFlatIP(384)  # MiniLM-L6-v2 = 384 dim
            self._load_existing_records()
            print(f"[LocalMemory] FAISS initialized with {len(self._record_cache)} records")
        except ImportError:
            print("[LocalMemory] FAISS/sentence-transformers not installed; using keyword fallback")
        except Exception as e:
            print(f"[LocalMemory] FAISS init failed: {e}; using keyword fallback")
        
        return True
    
    def _load_existing_records(self):
        """Load all existing records into FAISS index."""
        self._record_cache = []
        for f in self.setups_path.glob("*/*.json"):
            try:
                with open(f) as fp:
                    data = json.load(fp)
                rec = SetupRecord.from_dict(data)
                self._record_cache.append(rec)
                if self._faiss_index and self._embedding_model and NUMPY_AVAILABLE:
                    emb = self._embedding_model.encode([rec.to_embedding_text()], normalize_embeddings=True)
                    self._faiss_index.add(emb.astype(np.float32))
            except Exception:
                pass
    
    def _get_symbol_dir(self, symbol: str) -> Path:
        d = self.setups_path / symbol.upper()
        d.mkdir(exist_ok=True)
        return d
    
    def store_setup(self, record: SetupRecord) -> bool:
        try:
            symbol_dir = self._get_symbol_dir(record.symbol)
            filepath = symbol_dir / f"{record.setup_type}_{record.record_id}.json"
            with open(filepath, "w") as f:
                json.dump(record.to_dict(), f, indent=2)
            
            # Update FAISS
            if self._faiss_index and self._embedding_model and NUMPY_AVAILABLE:
                emb = self._embedding_model.encode([record.to_embedding_text()], normalize_embeddings=True)
                self._faiss_index.add(emb.astype(np.float32))
            self._record_cache.append(record)
            return True
        except Exception as e:
            print(f"[LocalMemory] Store failed: {e}")
            return False
    
    def get_similar(self, setup_type: str, features: dict, k: int = 5) -> list[SetupRecord]:
        if not self._record_cache:
            return []
        
        query_text = SetupRecord(
            record_id="", timestamp=0, symbol="", setup_type=setup_type,
            features=features, outcome="", r_multiple=0, duration_bars=0,
            exit_reason="", entry_price=0, stop_price=0, target_price=0,
            position_size=0, max_loss_usd=0
        ).to_embedding_text()
        
        if self._faiss_index and self._embedding_model and NUMPY_AVAILABLE:
            # Vector similarity
            q_emb = self._embedding_model.encode([query_text], normalize_embeddings=True).astype(np.float32)
            scores, indices = self._faiss_index.search(q_emb, min(k * 2, len(self._record_cache)))
            
            results = []
            for idx, score in zip(indices[0], scores[0]):
                if idx < len(self._record_cache):
                    rec = self._record_cache[idx]
                    if rec.setup_type == setup_type and score >= self.config.get("similarity_threshold", 0.7):
                        results.append((rec, float(score)))
            
            results.sort(key=lambda x: x[1], reverse=True)
            return [r for r, _ in results[:k]]
        else:
            # Keyword fallback: match setup_type + feature overlap
            scored = []
            for rec in self._record_cache:
                if rec.setup_type != setup_type:
                    continue
                # Simple feature overlap score
                overlap = sum(1 for fk in features if fk in rec.features)
                total = len(features) + len(rec.features)
                score = overlap / max(total, 1)
                if score > 0:
                    scored.append((rec, score))
            
            scored.sort(key=lambda x: x[1], reverse=True)
            return [r for r, _ in scored[:k]]
    
    def get_recent(self, symbol: str, setup_type: str, limit: int = 20) -> list[SetupRecord]:
        symbol_dir = self.setups_path / symbol.upper()
        if not symbol_dir.exists():
            return []
        
        records = []
        for f in sorted(symbol_dir.glob(f"{setup_type}_*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                with open(f) as fp:
                    data = json.load(fp)
                records.append(SetupRecord.from_dict(data))
                if len(records) >= limit:
                    break
            except Exception:
                pass
        return records
    
    def put(self, key: str, value: Any, namespace: str = "trader") -> bool:
        try:
            ns_dir = self.kv_path / namespace
            ns_dir.mkdir(exist_ok=True)
            filepath = ns_dir / f"{key}.json"
            with open(filepath, "w") as f:
                json.dump({"key": key, "value": value, "updated": time.time()}, f, indent=2)
            return True
        except Exception:
            return False
    
    def get(self, key: str, namespace: str = "trader") -> Any:
        try:
            filepath = self.kv_path / namespace / f"{key}.json"
            if filepath.exists():
                with open(filepath) as f:
                    return json.load(f).get("value")
        except Exception:
            pass
        return None
    
    def health_check(self) -> dict:
        return {
            "healthy": True,
            "backend": "Local",
            "details": f"Path: {self.base_path}, Records: {len(self._record_cache)}, FAISS: {'yes' if self._faiss_index else 'no'}"
        }


# --- Convenience function for skills ---
def get_memory(config_path: str = None) -> MemoryStore:
    """Get configured MemoryStore instance."""
    return MemoryStore(config_path)