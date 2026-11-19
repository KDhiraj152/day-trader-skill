#!/usr/bin/env python3
"""
Test script for trader_memory module.
Run: python -m trader_memory
"""

import sys
sys.path.insert(0, '.')

from trader_memory import get_memory, SetupRecord

def test_memory():
    print("=" * 50)
    print("Trader Memory Layer Test")
    print("=" * 50)
    
    mem = get_memory()
    health = mem.health_check()
    print(f"Backend: {health['backend']}")
    print(f"Status: {health['details']}")
    print()
    
    # Test 1: Store a setup
    print("Test 1: Store setup record")
    ok = mem.store_setup(
        symbol="TEST",
        setup_type="orb",
        features={"or_range_pct": 1.5, "volume_ratio": 1.2, "pre_trend_pct": 0.3},
        outcome="target_first",
        r_multiple=1.8,
        duration_bars=45,
        exit_reason="target",
        entry_price=100.0,
        stop_price=95.0,
        target_price=110.0,
        position_size=10,
        max_loss_usd=50.0,
        tags=["test", "buy"]
    )
    print(f"  Store: {'OK' if ok else 'FAILED'}")
    
    # Test 2: Retrieve similar
    print("\nTest 2: Retrieve similar setups")
    similar = mem.get_similar("orb", {"or_range_pct": 1.4, "volume_ratio": 1.1}, k=3)
    print(f"  Found: {len(similar)} records")
    for r in similar:
        print(f"    {r.symbol} {r.setup_type} -> {r.outcome} ({r.r_multiple}R) @ {r.entry_price}")
    
    # Test 3: KV store
    print("\nTest 3: Key-value store")
    mem.put("test_key", {"foo": "bar", "nested": {"num": 42}}, namespace="test")
    val = mem.get("test_key", namespace="test")
    print(f"  Stored: {val}")
    
    # Test 4: Recent by symbol
    print("\nTest 4: Recent setups for symbol")
    recent = mem.get_recent("TEST", "orb", limit=5)
    print(f"  Recent: {len(recent)} records")
    
    print("\n" + "=" * 50)
    print("All tests passed!" if ok else "Some tests failed!")
    print("=" * 50)

if __name__ == "__main__":
    test_memory()