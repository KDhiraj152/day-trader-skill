# Memory Layer Integration Guide

## Quick Start

```bash
# Optional: Enable vector similarity search (local backend)
pip install faiss-cpu sentence-transformers

# GBrain backend works automatically if configured in OpenCode/Hermes
```

## Per-Skill Integration Pattern

### 1. Import (top of skill .py)
```python
try:
    from trader_memory import get_memory, MEMORY_AVAILABLE
except ImportError:
    MEMORY_AVAILABLE = False
    get_memory = lambda: None
```

### 2. Initialize (in main/compute function)
```python
def compute(args, now):
    # ... existing setup ...
    
    # Initialize memory (auto-detects GBrain or local)
    memory = None
    if MEMORY_AVAILABLE:
        try:
            memory = get_memory()
            print(f"[Memory] {memory.health_check()['backend']} ready", file=sys.stderr)
        except Exception as e:
            print(f"[Memory] Init failed: {e}", file=sys.stderr)
    
    # ... rest of compute ...
```

### 3. Recall Similar (before core logic)
```python
# Build features from current context
features = build_features_for_memory(context)  # Your skill-specific features

# Recall
if memory:
    similar = memory.get_similar(setup_type, features, k=5)
    if similar:
        print(f"[Memory] Found {len(similar)} similar: "
              f"target={sum(1 for r in similar if r.outcome=='target_first')/len(similar):.0%}", 
              file=sys.stderr)
```

### 4. Store Outcome (after core logic)
```python
# After generating result
if memory:
    memory.store_setup(
        symbol=symbol,
        setup_type=setup_type,
        features=features,
        outcome=outcome,           # "target_first", "stop_first", "neither", etc.
        r_multiple=actual_r,
        duration_bars=duration,
        exit_reason=exit_reason,
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        position_size=size,
        max_loss_usd=max_loss,
        tags=[side, "live" if is_live else "sim"]
    )
```

## Feature Extraction Guidelines

Each skill should extract features that make setups comparable:

| Skill | Key Features |
|-------|--------------|
| `trader-scanner` | setup_type, price, volume, rsi, regime, gap_pct |
| `trader-entry` | symbol, or_range_pct, volume_ratio, bar_of_day, atr |
| `trader-exit` | stop_rule, target_r, risk_pct, atr_multiple |
| `trader-timemachine` | or_range_pct, volume_ratio, pre_trend_pct, setup_type, side |
| `trader-risk` | risk_checks_failed, daily_loss_pct, pos_size_pct, r_multiple |
| `trader-budget` | cash_pct, pos_cap_pct, max_order_pct, shares |
| `trader-broker` | order_type, side, size, price, venue |

## Configuration (trader/config.json)

```json
{
  "memory": {
    "backend": "auto",                    // "gbrain" | "local" | "auto"
    "gbrain_namespace": "default",        // GBrain source namespace
    "local_path": "trader/memory",        // Local file path
    "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
    "similarity_threshold": 0.7,          // Min cosine similarity for recall
    "max_records_per_symbol": 1000
  }
}
```

## Backend Behavior

| Backend | Storage | Search | Persistence | Cross-Session |
|---------|---------|--------|-------------|---------------|
| **GBrain** | Pages + KV | Hybrid (keyword + vector) | Permanent | Yes |
| **Local + FAISS** | JSON + FAISS index | Vector (cosine) | File-based | Yes |
| **Local (fallback)** | JSON only | Keyword overlap | File-based | Yes |

## Testing

```python
# Test memory layer standalone
from trader_memory import get_memory
mem = get_memory()
print(mem.health_check())

# Store
mem.store_setup(symbol="TEST", setup_type="orb", features={"x":1}, outcome="target_first",
                r_multiple=2.0, duration_bars=10, exit_reason="target",
                entry_price=100, stop_price=95, target_price=110, position_size=10, max_loss_usd=50)

# Recall
similar = mem.get_similar("orb", {"x":1}, k=3)
print(f"Found {len(similar)} similar")

# KV
mem.put("key", {"data": 123}, namespace="test")
print(mem.get("key", namespace="test"))
```

## Adding to Other Skills

### trader-scanner
- Store: each scan hit with setup features
- Recall: similar market conditions → adjust scan thresholds

### trader-entry
- Store: entry trigger + context
- Recall: similar ORB setups → show historical win rate

### trader-exit
- Store: stop/target rule + outcome
- Recall: same stop rule → optimize rule selection

### trader-risk
- Store: risk verdict + trade outcome
- Recall: similar risk profile → calibrate checks

### trader-budget
- Store: sizing decision + actual fill
- Recall: similar budget state → optimize allocation

### trader-broker
- Store: order + fill quality
- Recall: similar orders → venue selection

## Migration Notes

1. **No breaking changes** — memory is optional, skills work without it
2. **Auto-detection** — GBrain preferred if available, else local JSON
3. **Vector search** — requires `pip install faiss-cpu sentence-transformers`
4. **GBrain setup** — ensure `opencode mcp list` shows gbrain connected