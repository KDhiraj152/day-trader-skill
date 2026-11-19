#!/usr/bin/env python3
"""Time Machine for trader-timemachine. Standard library only.

Replays a planned day trade before you risk a dollar: 10,000 simulated runs of
the rest of the session from your entry, plus the same rule on every past
session in the data.

    python3 timemachine.py run                          # trader/plan.json, 10,000 replays, seed 19
    python3 timemachine.py run --write                  # also save trader/timemachine.json
    python3 timemachine.py run --until 15:55            # stop each replay at your flat-by time
    python3 timemachine.py run --seed 7 --replays 20000 --json
    python3 timemachine.py run --symbol TSLA --date 2026-10-19 --entry 364.18 \
        --stop 358.32 --target 370.04 --entry-time "10:15 AM"
    python3 timemachine.py chart                        # ASCII fan chart of the replays
    python3 timemachine.py chart --from trader/timemachine.json

NEW: Memory Layer Integration (auto-detects GBrain or local JSON)
    --memory/--no-memory       Enable/disable memory layer (default: auto)
    --recall-similar           Retrieve similar setups from memory and show historical outcomes
    --store-outcome            Store the plan + simulation result to memory after run

How the replays work (the reel's sim.py, same algorithm, same random draws):
  1. Fetch 60 days of 5-minute bars (Yahoo v8 chart, range=60d interval=5m;
     one request). Keep only FULL sessions before the plan's date: 78 bars,
     9:30 to 4:00 New York time. Half days, gaps and today are left out.
  2. The pool: for every bar slot 1..77 of the day, each past session's bar as
     ratios to the previous bar's close: (open, high, low, close) / prev close.
  3. One replay starts at the entry price and walks the rest of the session.
     For each bar i it picks a slot j = i + randint(-window, window), kept in
     1..77, then one past bar from pool[j] (random.choice), and scales it to
     the current price. The stop is checked before the target in every bar,
     so a bar that touches both counts as the stop (the conservative call).
  4. Outcomes: "target" or "stop" (whichever was touched first), or "neither"
     when the trade is still open at --until (default 16:00, the close, or
     13:00 on an NYSE early-close day).
     "green" = target first, or above the entry at --until (below for a sell).
     R = the target's R at the target, -1 at the stop, otherwise
     (price at --until - entry) / risk. A gap through the stop still counts
     -1R here; a real fill can be worse.
  5. The price at --until: median and the 5th to 95th percentile of all
     replays (pct(a, q) = sorted a at index int(q * n)). The fan chart uses a
     second run of 2,000 paths with the same seed. The histogram has 24 bins
     between the 1st and 99th percentile.
  6. History: the plan's own rule (an opening range breakout with the same
     opening range, stop rule and target R) re-run on every one of those past
     sessions, first close beyond the range = entry, same stop-first rule.

The verdict line looks at the replays that hit one side (target or stop) and
compares the target's share of them, target / (target + stop), with the share
that breaks even at the plan's target R: 1 / (1 + R), so 50 % at 1R and 33 % at
2R. The gap, in percentage points:
  less than 5 points    "Close to a coin flip" (1R) / "Close to break-even" (other R)
  5 to 15 points        "Leans toward the target" / "Leans toward the stop"
  15 points or more     "Strongly toward the target" / "Strongly toward the stop"
Below it: a note when more than 40 % of the replays hit neither (the price at
--until decides those), and the average R when its sign goes against the lean.

5-minute bars only: Yahoo keeps 60 days of 5-min bars but only about 7 days of
1-min bars, too few sessions for a fair pool. The run refuses with a plain
message when there are fewer than 20 full sessions or the entry bar is not in
the data. Same plan, same data and same --seed give the same numbers on any
machine. A simulation built from the stock's own recent bars is not a
prediction: earnings, news and halts can do what the last 60 days never did.

Data: https://query2.finance.yahoo.com/v8/finance/chart/<T>?range=60d&interval=5m
(unofficial and free, can lag; falls back to query1 on 429 or 5xx).
--offline FILE reads a saved chart JSON (.json or .json.gz) instead.
Times are New York (ET) wall-clock; --now "2026-10-19 10:15" pins the clock.
"""

import argparse
import datetime
import gzip
import json
import math
import os
import random
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; trader-skill/2.1; +https://github.com/KDhiraj152/trader-skill)"
PAUSE = 0.5          # seconds between requests: be polite to free endpoints
BACKOFF = 5.0        # seconds to wait once after a 429
HOSTS = ("query2", "query1")
INTERVAL = 300       # 5-minute bars, in seconds
SESSION_BARS = 78    # 9:30 to 16:00 in 5-minute bars
OPEN_MIN = 9 * 60 + 30
CLOSE_MIN = 16 * 60
MIN_SESSIONS = 20
SAMPLE_PATHS = 160
BAND_PATHS = 2000
BAND_Q = (0.05, 0.25, 0.5, 0.75, 0.95)
HIST_BINS = 24
COIN_FLIP = 0.05     # verdict thresholds, see the docstring
STRONG = 0.15
MANY_NEITHER = 0.40
EPOCH = datetime.datetime(1970, 1, 1)
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
NYSE_EARLY_CLOSE = {  # 1:00 p.m. ET, from https://www.nyse.com/markets/hours-calendars (read 2026-10-13)
    "2026-11-27": "day after Thanksgiving",
    "2026-12-24": "Christmas Eve",
    "2027-11-26": "day after Thanksgiving",
}
EARLY_MIN = 13 * 60


class TMError(Exception):
    pass


# ---------------------------------------------------------------- time (copied from trader-alerts)

def _nth_sunday(year, month, n):
    d = datetime.date(year, month, 1)
    d += datetime.timedelta(days=(6 - d.weekday()) % 7)
    return d + datetime.timedelta(weeks=n - 1)


def eastern_offset(utc):
    """Hours from UTC for New York: -4 in daylight time, -5 otherwise.
    DST runs from 2:00 a.m. on the second Sunday of March to 2:00 a.m. on the
    first Sunday of November (US rule since 2007)."""
    y = utc.year
    start = datetime.datetime.combine(_nth_sunday(y, 3, 2), datetime.time(7, 0))   # 2:00 EST
    end = datetime.datetime.combine(_nth_sunday(y, 11, 1), datetime.time(6, 0))    # 2:00 EDT
    naive = utc.replace(tzinfo=None)
    return -4 if start <= naive < end else -5


def to_eastern(utc):
    """Aware or naive UTC -> naive New York wall-clock time."""
    if utc.tzinfo is not None:
        utc = utc.astimezone(datetime.timezone.utc)
    return utc.replace(tzinfo=None) + datetime.timedelta(hours=eastern_offset(utc))


def eastern_to_utc(local):
    for off in (-4, -5):
        utc = local - datetime.timedelta(hours=off)
        if eastern_offset(utc) == off:
            return utc
    return local + datetime.timedelta(hours=5)


def parse_now(text):
    """ISO time -> naive UTC. A time without an offset is taken as New York time."""
    if not text:
        return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None)
    t = text.strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        raise TMError("--now wants a time like \"2026-10-19 10:15\" (New York) or ...Z (UTC)")
    if dt.tzinfo is None:
        dt = eastern_to_utc(dt)
    else:
        dt = dt.astimezone(datetime.timezone.utc)
    return dt.replace(tzinfo=None, microsecond=0)


def clock12(mins):
    hh = mins // 60
    mm = mins % 60
    return "%d:%02d %s" % (hh % 12 or 12, mm, "AM" if hh < 12 else "PM")


def is_early_close(date):
    return date in NYSE_EARLY_CLOSE


# ---------------------------------------------------------------- fetch

def fetch_chart(symbol):
    """Download 60d 5m chart from Yahoo. Returns raw JSON text."""
    for host in HOSTS:
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range=60d&interval=5m"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(BACKOFF)
                continue
            raise
        except urllib.error.URLError:
            continue
    raise TMError("all Yahoo endpoints failed")


def read_offline(path, symbol):
    if path.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return f.read()
    with open(path, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------- bars

def parse_chart(text):
    """Yahoo JSON -> (meta, list of bars with keys date, slot, start, o, h, l, c, v)."""
    data = json.loads(text)
    result = data["chart"]["result"][0]
    meta = result["meta"]
    timestamps = result["timestamp"]
    quotes = result["indicators"]["quote"][0]
    o, h, l, c, v = quotes["open"], quotes["high"], quotes["low"], quotes["close"], quotes["volume"]
    as_of = datetime.datetime.fromtimestamp(timestamps[-1], tz=datetime.timezone.utc)
    as_of = to_eastern(as_of)
    bars = {}
    dropped = {"outside_hours": 0, "not_complete": 0}
    for i, ts in enumerate(timestamps):
        if o[i] is None or h[i] is None or l[i] is None or c[i] is None:
            continue
        local = to_eastern(datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc))
        mins = local.hour * 60 + local.minute
        if not (OPEN_MIN <= mins < CLOSE_MIN):
            dropped["outside_hours"] += 1
            continue
        if mins % 5 != 0:
            continue
        start = mins
        if start + INTERVAL > as_of.hour * 60 + as_of.minute:
            dropped["not_complete"] += 1
            continue
        bars[ts] = {"date": local.date().isoformat(), "slot": mins // 5, "start": local.strftime("%H:%M"),
                    "o": o[i], "h": h[i], "l": l[i], "c": c[i], "v": v[i] or 0}
    return meta, [bars[t] for t in sorted(bars)], dropped


def split_sessions(bars):
    """{date: {slot: bar}}."""
    days = {}
    for b in bars:
        days.setdefault(b["date"], {})[b["slot"]] = b
    return days


def full_sessions(days, before):
    """Full sessions (all 78 bars) strictly before the plan's date, oldest first,
    and the short ones that were left out (half days, gaps)."""
    full, short = [], []
    for d in sorted(days):
        if d >= before:
            continue
        s = days[d]
        if len(s) == SESSION_BARS:
            full.append((d, [s[i] for i in range(SESSION_BARS)]))
        else:
            short.append({"date": d, "bars": len(s)})
    return full, short


# ---------------------------------------------------------------- the simulation (sim.py)

def build_pool(sessions):
    """pool[i] = every past session's bar i as (o, h, l, c) / bar i-1's close, in date order."""
    pool = [[] for _ in range(SESSION_BARS)]
    for _, D in sessions:
        for i in range(1, SESSION_BARS):
            pc = D[i - 1]["c"]
            pool[i].append((D[i]["o"] / pc, D[i]["h"] / pc, D[i]["l"] / pc, D[i]["c"] / pc))
    return pool


def pct(a, q):
    return a[min(len(a) - 1, int(q * len(a)))]


def simulate(pool, entry, stop, target, k, last, replays=10000, seed=19, window=2, side="buy", prior_bias=None):
    """
    Monte Carlo replays of bars k+1..last. Same draws and order as the reel's sim.py.
    
    prior_bias: optional dict from memory layer with keys:
        - "historical_target_rate": float 0-1
        - "historical_stop_rate": float 0-1
        - "historical_avg_r": float
        - "similar_count": int
    """
    long = side == "buy"
    risk = (entry - stop) if long else (stop - entry)
    r_target = round(((target - entry) if long else (entry - target)) / risk, 4)

    def slot(rng, i):
        return i if window == 0 else min(SESSION_BARS - 1, max(1, i + rng.randint(-window, window)))

    rng = random.Random(seed)
    choice = rng.choice
    outcomes, closes, paths = [], [], []
    for n in range(replays):
        p = entry
        outcome = None
        keep = n < SAMPLE_PATHS
        path = [entry]
        for i in range(k + 1, last + 1):
            o, h, l, c = choice(pool[slot(rng, i)])
            hi, lo, cl = p * h, p * l, p * c
            if outcome is None:
                if long:
                    if lo <= stop:
                        outcome = "stop"        # both inside one bar: count the loss (conservative)
                    elif hi >= target:
                        outcome = "target"
                else:
                    if hi >= stop:
                        outcome = "stop"
                    elif lo <= target:
                        outcome = "target"
            p = cl
            if keep:
                path.append(round(p, 2))
        outcomes.append(outcome or "close")
        closes.append(p)
        if keep:
            paths.append(path)
    cnt = {x: outcomes.count(x) for x in ("target", "stop", "close")}
    green = sum(1 for o, p in zip(outcomes, closes)
                if o == "target" or (o == "close" and (p > entry if long else p < entry)))
    Rs = [r_target if o == "target" else -1.0 if o == "stop" else ((p - entry) if long else (entry - p)) / risk
          for o, p in zip(outcomes, closes)]
    srt = sorted(closes)
    # percentile bands per bar for the fan chart: a second run of 2,000 paths, same seed
    rng = random.Random(seed)
    choice = rng.choice
    allp = []
    for n in range(BAND_PATHS):
        p = entry
        path = [entry]
        for i in range(k + 1, last + 1):
            o, h, l, c = choice(pool[slot(rng, i)])
            p = p * c
            path.append(p)
        allp.append(path)
    bands = []
    for j in range(last - k + 1):
        col = sorted(pp[j] for pp in allp)
        bands.append([round(pct(col, q), 2) for q in BAND_Q])
    lo_, hi_ = pct(srt, 0.01), pct(srt, 0.99)
    W = (hi_ - lo_) / HIST_BINS
    bins = [0] * HIST_BINS
    for c in srt:
        b = int((c - lo_) / W) if W > 0 else 0
        if 0 <= b < HIST_BINS:
            bins[b] += 1
    return {
        "replays": replays, "seed": seed, "window": window, "bars_left": last - k,
        "p_target": round(cnt["target"] / replays, 4), "p_stop": round(cnt["stop"] / replays, 4),
        "p_neither": round(cnt["close"] / replays, 4), "p_green": round(green / replays, 4),
        "median_close": round(pct(srt, 0.5), 2), "p5_close": round(pct(srt, 0.05), 2),
        "p95_close": round(pct(srt, 0.95), 2), "avg_R": round(statistics.mean(Rs), 3),
        "r_at_target": r_target, "band_paths": BAND_PATHS, "bands": bands, "sample_paths": paths,
        "hist": {"lo": round(lo_, 2), "hi": round(hi_, 2), "bins": bins},
        "prior_bias": prior_bias,
    }


# ---------------------------------------------------------------- stop rules and the history replay

def cents_away(x, long):
    """Round a stop to the cent, away from the entry: down for a buy, up for a sell."""
    c = round(x * 100, 4)
    return (math.floor(c) if long else math.ceil(c)) / 100.0


def opening_range(D, n):
    """(high, low) of the first n bars of a session given as {slot: bar} or a list."""
    rows = [D[i] for i in range(n)]
    return max(b["h"] for b in rows), min(b["l"] for b in rows)


def rule_stop(rule, oh, ol, entry, long):
    r = rule["stop_rule"]
    if r == "or_mid":
        return cents_away((oh + ol) / 2, long)
    if r in ("or_low", "or_high"):
        return cents_away(ol if long else oh, long)
    frac = rule["stop_pct"] / 100.0
    return cents_away(entry * (1 - frac) if long else entry * (1 + frac), long)


def history_replay(sessions, rule, last, side="buy"):
    """The plan's rule on every past full session: entry = the first bar after the
    opening range to close beyond it (up to the --until bar), then stop first, then
    target, bar by bar, else the close at --until."""
    long = side == "buy"
    n = rule["or_minutes"] // 5
    trades = []
    for d, D in sessions:
        oh, ol = opening_range(D, n)
        kk = next((i for i in range(n, last + 1) if (D[i]["c"] > oh if long else D[i]["c"] < ol)), None)
        if kk is None:
            continue
        e = round(D[kk]["c"], 2)
        s = rule_stop(rule, oh, ol, e, long)
        risk = (e - s) if long else (s - e)
        if risk <= 0:
            continue
        t = round(e + rule["target_r"] * risk, 2) if long else round(e - rule["target_r"] * risk, 2)
        oc = None
        for b in D[kk + 1:last + 1]:
            if (b["l"] <= s) if long else (b["h"] >= s):
                oc = "stop"
                break
            if (b["h"] >= t) if long else (b["l"] <= t):
                oc = "target"
                break
        cl = D[last]["c"]
        R = ((t - e) if long else (e - t)) / risk if oc == "target" else -1.0 if oc == "stop" else \
            ((cl - e) if long else (e - cl)) / risk
        trades.append({"date": d, "time": clock12(OPEN_MIN + 5 * (kk + 1)), "entry": e, "stop": s, "target": t,
                       "outcome": oc or "close", "R": round(R, 2)})
    return {
        "sessions": len(sessions), "triggered": len(trades),
        "target": sum(1 for x in trades if x["outcome"] == "target"),
        "stop": sum(1 for x in trades if x["outcome"] == "stop"),
        "close": sum(1 for x in trades if x["outcome"] == "close"),
        "green": sum(1 for x in trades if x["R"] > 0),
        "avg_R": round(statistics.mean(x["R"] for x in trades), 3) if trades else None,
        "rule": rule, "trades": trades,
    }


# ---------------------------------------------------------------- the plan

def _num(v, what):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise TMError("the plan needs a number for %s, got %r" % (what, v))
    if math.isnan(x) or math.isinf(x):
        raise TMError("%s must be finite, got %s" % (what, v))
    return x


def normalize_plan(raw: dict, now=None) -> dict:
    """Normalize a raw plan dict (from trader-exit JSON) into a complete plan.
    
    Computes: entry_bar from entry_time, last_bar from date/until, target_r, risk.
    """
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    
    # Required fields from trader-exit output
    required = ["symbol", "date", "entry", "entry_time", "stop", "target"]
    for r in required:
        if r not in raw:
            raise TMError("plan missing %s" % r)
    
    # Parse entry time
    entry_time = raw["entry_time"]
    try:
        et = datetime.datetime.strptime(entry_time.strip(), "%I:%M %p")
        entry_min = et.hour * 60 + et.minute
    except ValueError:
        raise TMError("entry_time wants format like \"10:15 AM\"")
    k = (entry_min - OPEN_MIN) // 5
    if not (0 <= k < SESSION_BARS):
        raise TMError("entry bar %d out of session range (0..77)" % k)
    
    entry = _num(raw["entry"], "entry")
    stop = _num(raw["stop"], "stop")
    target = _num(raw["target"], "target")
    
    # Determine side from stop/target relationship
    side = raw.get("side", "buy")
    if side == "buy":
        if stop >= entry:
            raise TMError("stop must be below entry for a buy")
        if target <= entry:
            raise TMError("target must be above entry for a buy")
    else:
        if stop <= entry:
            raise TMError("stop must be above entry for a sell")
        if target >= entry:
            raise TMError("target must be below entry for a sell")
    
    risk = abs(entry - stop)
    target_r = round(abs(target - entry) / risk, 2)
    
    # Compute last_bar
    date = raw["date"]
    last = SESSION_BARS - 1
    if "flat_by" in raw:
        try:
            ut = datetime.datetime.strptime(raw["flat_by"].strip(), "%H:%M")
            last = min(last, (ut.hour * 60 + ut.minute - OPEN_MIN) // 5)
        except ValueError:
            pass
    elif "until" in raw:
        try:
            ut = datetime.datetime.strptime(raw["until"].strip(), "%H:%M")
            last = min(last, (ut.hour * 60 + ut.minute - OPEN_MIN) // 5)
        except ValueError:
            pass
    if is_early_close(date):
        last = min(last, (EARLY_MIN - OPEN_MIN) // 5)
    if k >= last:
        raise TMError("entry bar must be before flat_by / close")
    
    return {
        "symbol": raw["symbol"].upper(),
        "date": date,
        "side": side,
        "entry": entry,
        "entry_time": entry_time,
        "entry_bar": k,
        "stop": stop,
        "target": target,
        "risk": round(risk, 2),
        "target_r": target_r,
        "or_minutes": raw.get("or_minutes", 15),
        "stop_rule": raw.get("stop_rule", "auto"),
        "last_bar": last,
    }


def load_plan(args, now):
    """Load plan from trader/plan.json or command-line flags."""
    if args.symbol:
        # Build plan from flags
        date = args.date or to_eastern(now).date().isoformat()
        entry_time = args.entry_time or "10:15 AM"
        # Parse entry time
        try:
            et = datetime.datetime.strptime(entry_time.strip(), "%I:%M %p")
            entry_min = et.hour * 60 + et.minute
        except ValueError:
            raise TMError("--entry-time wants format like \"10:15 AM\"")
        k = (entry_min - OPEN_MIN) // 5
        if not (0 <= k < SESSION_BARS):
            raise TMError("entry bar %d out of session range (0..77)" % k)
        entry = _num(args.entry, "entry")
        stop = _num(args.stop, "stop")
        target = _num(args.target, "target")
        if args.side == "buy":
            if stop >= entry:
                raise TMError("stop must be below entry for a buy")
            if target <= entry:
                raise TMError("target must be above entry for a buy")
        else:
            if stop <= entry:
                raise TMError("stop must be above entry for a sell")
            if target >= entry:
                raise TMError("target must be below entry for a sell")
        risk = abs(entry - stop)
        target_r = round(abs(target - entry) / risk, 2)
        last = SESSION_BARS - 1
        if args.until:
            try:
                ut = datetime.datetime.strptime(args.until.strip(), "%H:%M")
                last = min(last, (ut.hour * 60 + ut.minute - OPEN_MIN) // 5)
            except ValueError:
                raise TMError("--until wants HH:MM (24h)")
        if is_early_close(date):
            last = min(last, (EARLY_MIN - OPEN_MIN) // 5)
        if k >= last:
            raise TMError("entry bar must be before --until / close")
        return {
            "symbol": args.symbol.upper(), "date": date, "side": args.side,
            "entry": entry, "entry_time": entry_time, "entry_bar": k,
            "stop": stop, "target": target, "risk": round(risk, 2),
            "target_r": target_r, "or_minutes": args.or_minutes,
            "stop_rule": args.stop_rule, "last_bar": last,
        }
    else:
        # Load from file
        plan_path = args.plan
        if not os.path.exists(plan_path):
            raise TMError("no plan file at %s (run trader-exit first, or use --symbol)" % plan_path)
        with open(plan_path, encoding="utf-8") as f:
            p = json.load(f)
        # Validate required fields
        required = ["symbol", "date", "entry", "entry_time", "entry_bar", "stop", "target", "last_bar"]
        for r in required:
            if r not in p:
                raise TMError("plan.json missing %s" % r)
        return p


# ---------------------------------------------------------------- Memory Integration

def build_memory_features(plan, meta, sessions):
    """Extract features from plan + market data for memory similarity search."""
    # Get volume stats from sessions
    volumes = []
    for _, D in sessions:
        if D:
            v = sum(b["v"] for b in D)
            volumes.append(v)
    avg_vol = statistics.mean(volumes) if volumes else 0
    
    # Price action features
    first_bars = sessions[0][1] if sessions else []
    last_bars = sessions[-1][1] if sessions else []
    first_close = first_bars[0]["c"] if first_bars else 0
    last_close = last_bars[-1]["c"] if last_bars else 0
    pct_change = ((last_close - first_close) / first_close * 100) if first_close else 0
    
    # Opening range features
    n = plan.get("or_minutes", 15) // 5
    oh, ol = opening_range(first_bars, n)
    or_range_pct = ((oh - ol) / ol * 100) if ol else 0
    
    return {
        "or_range_pct": round(or_range_pct, 2),
        "volume_ratio": round(volumes[0] / avg_vol, 2) if volumes and avg_vol else 1.0,
        "pre_trend_pct": round(pct_change, 2),
        "setup_type": plan.get("stop_rule", "orb"),
        "side": plan.get("side", "buy"),
    }


def recall_similar_setups(memory, setup_type: str, features: dict, k: int = 5):
    """Retrieve similar setups from memory and return summary stats."""
    if not memory:
        return None
    try:
        records = memory.get_similar(setup_type, features, k=k)
        if not records:
            return None
        
        # Aggregate stats
        outcomes = [r.outcome for r in records]
        target_count = sum(1 for o in outcomes if o == "target_first")
        stop_count = sum(1 for o in outcomes if o == "stop_first")
        neither_count = sum(1 for o in outcomes if o in ("neither", "close", "open"))
        total = len(records)
        
        r_values = [r.r_multiple for r in records]
        avg_r = statistics.mean(r_values) if r_values else 0
        
        return {
            "similar_count": total,
            "historical_target_rate": round(target_count / total, 3),
            "historical_stop_rate": round(stop_count / total, 3),
            "historical_neither_rate": round(neither_count / total, 3),
            "historical_avg_r": round(avg_r, 3),
            "records": [{"symbol": r.symbol, "date": datetime.datetime.fromtimestamp(r.timestamp).strftime("%Y-%m-%d"),
                         "outcome": r.outcome, "r": r.r_multiple, "exit": r.exit_reason} for r in records]
        }
    except Exception as e:
        print(f"[Memory] Recall failed: {e}", file=sys.stderr)
        return None


def store_setup_outcome(memory, plan, mc_result, history_result, features):
    """Store the plan + simulation outcome to memory."""
    if not memory:
        return False
    try:
        # Determine outcome label from simulation
        p_target = mc_result.get("p_target", 0)
        p_stop = mc_result.get("p_stop", 0)
        if p_target > p_stop:
            sim_outcome = "target_first"
        elif p_stop > p_target:
            sim_outcome = "stop_first"
        else:
            sim_outcome = "neither"
        
        # Get actual R from simulation
        sim_r = mc_result.get("avg_R", 0)
        
        memory.store_setup(
            symbol=plan["symbol"],
            setup_type=plan.get("stop_rule", "orb"),
            features=features,
            outcome=sim_outcome,
            r_multiple=sim_r,
            duration_bars=mc_result.get("bars_left", 0),
            exit_reason="simulation",  # Will be updated when trade actually happens
            entry_price=plan["entry"],
            stop_price=plan["stop"],
            target_price=plan["target"],
            position_size=0,  # Unknown at simulation time
            max_loss_usd=0,
            tags=["simulation", plan.get("side", "buy")]
        )
        return True
    except Exception as e:
        print(f"[Memory] Store failed: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------- time machine core

def time_machine(text, plan, now, replays=10000, seed=19, window=2, until=None, source="yahoo"):
    """The main simulation entry point. Returns the result dict."""
    meta, bars, dropped = parse_chart(text)
    days = split_sessions(bars)
    plan_date = plan["date"]
    sessions, short = full_sessions(days, plan_date)
    if len(sessions) < MIN_SESSIONS:
        raise TMError("need at least %d full sessions before %s, got %d" % (MIN_SESSIONS, plan_date, len(sessions)))
    
    k = plan["entry_bar"]
    last = plan["last_bar"]
    if k >= last:
        raise TMError("entry bar %d must be before last bar %d" % (k, last))
    
    # Build features for memory
    features = build_memory_features(plan, meta, sessions)
    
    # Initialize memory if available (lazy import - trader_memory is in repo root)
    memory = None
    try:
        import sys as _sys
        _repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if _repo_root not in _sys.path:
            _sys.path.insert(0, _repo_root)
        from trader_memory import get_memory
        memory = get_memory()
        health = memory.health_check()
        print(f"[Memory] Backend: {health['backend']} - {health['details']}", file=sys.stderr)
    except Exception as e:
        print(f"[Memory] Init failed: {e}", file=sys.stderr)
        memory = None
    
    # Recall similar setups
    prior_bias = None
    if memory:
        similar = recall_similar_setups(memory, plan.get("stop_rule", "orb"), features, k=5)
        if similar:
            prior_bias = {
                "historical_target_rate": similar["historical_target_rate"],
                "historical_stop_rate": similar["historical_stop_rate"],
                "historical_avg_r": similar["historical_avg_r"],
                "similar_count": similar["similar_count"],
            }
            print(f"[Memory] Found {similar['similar_count']} similar setups: "
                  f"target={similar['historical_target_rate']:.1%}, "
                  f"stop={similar['historical_stop_rate']:.1%}, "
                  f"avgR={similar['historical_avg_r']:.2f}", file=sys.stderr)
    
    # Run Monte Carlo simulation
    pool = build_pool(sessions)
    mc = simulate(pool, plan["entry"], plan["stop"], plan["target"], k, last,
                  replays, seed, window, plan.get("side", "buy"), prior_bias)
    
    # Run history replay
    rule = {
        "or_minutes": plan.get("or_minutes", 15),
        "stop_rule": plan.get("stop_rule", "auto"),
        "stop_pct": plan.get("stop_pct", 0),
        "target_r": plan["target_r"],
    }
    hist = history_replay(sessions, rule, last, plan.get("side", "buy"))
    
    # Verdict
    hit = mc["p_target"] + mc["p_stop"]
    if hit == 0:
        verdict = "No side hit in any replay - plan never triggers?"
        target_share = 0
    else:
        target_share = mc["p_target"] / hit
    breakeven = 1 / (1 + mc["r_at_target"])
    gap = round((target_share - breakeven) * 100, 1)
    
    if gap >= STRONG * 100:
        lean = "Strongly toward the target"
    elif gap >= COIN_FLIP * 100:
        lean = "Leans toward the target"
    elif gap <= -STRONG * 100:
        lean = "Strongly toward the stop"
    elif gap <= -COIN_FLIP * 100:
        lean = "Leans toward the stop"
    else:
        lean = "Close to a coin flip" if mc["r_at_target"] == 1.0 else "Close to break-even"
    
    verdict = f"Target first {mc['p_target']:.1%} | Stop first {mc['p_stop']:.1%} | Neither {mc['p_neither']:.1%} | {lean} (gap {gap:+.1f}pp vs break-even {breakeven:.0%})"
    
    verdict_notes = []
    if mc["p_neither"] > MANY_NEITHER:
        verdict_notes.append(f"Note: {mc['p_neither']:.0%} of replays hit neither side - the price at --until decides those.")
    if mc["avg_R"] is not None and (mc["avg_R"] > 0) != (gap > 0):
        verdict_notes.append(f"Note: average R is {mc['avg_R']:+.2f}, opposite sign to the lean.")
    
    result = {
        "plan": plan,
        "mc": mc,
        "history": hist,
        "verdict": verdict,
        "verdict_notes": verdict_notes,
        "source": source,
        "dropped": dropped,
        "sessions_used": len(sessions),
        "memory": {
            "backend": memory.backend_name if memory else "none",
            "similar_found": prior_bias["similar_count"] if prior_bias else 0,
            "prior_bias": prior_bias,
        } if memory else None,
    }
    
    # Store to memory if enabled
    if memory:
        store_setup_outcome(memory, plan, mc, hist, features)
    
    return result


# ---------------------------------------------------------------- report rendering

def report(doc):
    p = doc["plan"]
    mc = doc["mc"]
    hist = doc["history"]
    mem = doc.get("memory")
    
    out = []
    out.append(f"Time Machine - {p['symbol']} {p['side'].upper()} on {p['date']}")
    out.append("=" * 60)
    out.append(f"Entry: ${p['entry']:.2f} at {p['entry_time']} (bar {p['entry_bar']})")
    out.append(f"Stop:  ${p['stop']:.2f} (rule: {p.get('stop_rule', 'auto')})")
    out.append(f"Target: ${p['target']:.2f} ({mc['r_at_target']:.2f}R)")
    out.append(f"Risk/share: ${mc['r_at_target']:.2f}R = ${abs(p['entry'] - p['stop']):.2f}")
    out.append(f"Last bar: {p['last_bar']} (until {clock12(OPEN_MIN + 5 * p['last_bar'])})")
    out.append(f"Sessions: {doc['sessions_used']} full sessions used")
    out.append("")
    out.append("MONTE CARLO (10,000 replays, seed 19)")
    out.append("-" * 60)
    out.append(f"Target first:  {mc['p_target']:.1%}")
    out.append(f"Stop first:    {mc['p_stop']:.1%}")
    out.append(f"Neither:       {mc['p_neither']:.1%}")
    out.append(f"Green (>=entry): {mc['p_green']:.1%}")
    out.append(f"Median close: ${mc['median_close']:.2f}  (5th–95th: ${mc['p5_close']:.2f}–${mc['p95_close']:.2f})")
    out.append(f"Average R: {mc['avg_R']:+.2f}")
    out.append("")
    
    if mem and mem.get("similar_found", 0) > 0:
        out.append("MEMORY RECALL")
        out.append("-" * 60)
        out.append(f"Backend: {mem['backend']}")
        out.append(f"Similar setups found: {mem['similar_found']}")
        pb = mem.get("prior_bias", {})
        out.append(f"Historical target rate: {pb.get('historical_target_rate', 0):.1%}")
        out.append(f"Historical stop rate:   {pb.get('historical_stop_rate', 0):.1%}")
        out.append(f"Historical avg R:       {pb.get('historical_avg_r', 0):+.2f}")
        out.append("")
    
    out.append("HISTORY REPLAY (same rule on every past session)")
    out.append("-" * 60)
    out.append(f"Sessions: {hist['sessions']} | Triggered: {hist['triggered']}")
    out.append(f"Target: {hist['target']} | Stop: {hist['stop']} | Close: {hist['close']}")
    out.append(f"Green: {hist['green']} | Avg R: {hist['avg_R']}")
    out.append("")
    out.append("VERDICT")
    out.append("-" * 60)
    out.append(doc["verdict"])
    for note in doc.get("verdict_notes", []):
        out.append(note)
    
    return out


def render_chart(doc):
    mc = doc["mc"]
    bands = mc["bands"]
    plan = doc["plan"]
    entry = plan["entry"]
    stop = plan["stop"]
    target = plan["target"]
    
    out = []
    out.append(f"Fan Chart - {plan['symbol']} {plan['side'].upper()} {plan['date']}")
    out.append(f"Entry {entry:.2f} | Stop {stop:.2f} | Target {target:.2f}")
    out.append("")
    
    # Find price range
    all_vals = [entry, stop, target]
    for b in bands:
        all_vals.extend(b)
    lo, hi = min(all_vals), max(all_vals)
    pad = (hi - lo) * 0.05
    lo -= pad
    hi += pad
    
    width = 80
    height = 20
    
    def y_to_row(y):
        return int((hi - y) / (hi - lo) * (height - 1))
    
    # Draw
    canvas = [[" " for _ in range(width)] for _ in range(height)]
    
    # Price labels
    for i in range(height):
        price = hi - (hi - lo) * i / (height - 1)
        label = f"{price:7.2f}"
        for j, ch in enumerate(label):
            if j < width:
                canvas[i][j] = ch
    
    # Bands
    for i, b in enumerate(bands):
        col = min(width - 1, 8 + i)
        p5, p25, p50, p75, p95 = b
        r5 = y_to_row(p5)
        r25 = y_to_row(p25)
        r50 = y_to_row(p50)
        r75 = y_to_row(p75)
        r95 = y_to_row(p95)
        # 5-95 range
        for r in range(r5, r95 + 1):
            if 0 <= r < height:
                canvas[r][col] = "·"
        # 25-75 range
        for r in range(r25, r75 + 1):
            if 0 <= r < height:
                canvas[r][col] = "░"
        # Median
        if 0 <= r50 < height:
            canvas[r50][col] = "█"
    
    # Entry/Stop/Target lines
    for price, ch, label in [(entry, "━", "ENTRY"), (stop, "─", "STOP"), (target, "━", "TARGET")]:
        r = y_to_row(price)
        if 0 <= r < height:
            for c in range(8, width):
                canvas[r][c] = ch
            if width > 8 + len(label) + 2:
                for j, lch in enumerate(label):
                    canvas[r][8 + j] = lch
    
    for row in canvas:
        out.append("".join(row).rstrip())
    
    out.append("")
    out.append("· = 5th–95th percentile band  ░ = 25th–75th  █ = median")
    return out


# ---------------------------------------------------------------- commands

def _write(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
        fh.write("\n")


def compute(args, now):
    plan = load_plan(args, now)
    if args.offline:
        text, source = read_offline(args.offline, plan["symbol"]), "offline"
    else:
        text, source = fetch_chart(plan["symbol"]), "yahoo"
    return time_machine(text, plan, now, args.replays, args.seed, args.window, args.until, source)


def cmd_run(args):
    now = parse_now(args.now)
    doc = compute(args, now)
    if args.write:
        _write(args.write, doc)
    if args.json:
        slim = dict(doc, mc={k: v for k, v in doc["mc"].items() if k != "sample_paths"})
        print(json.dumps(slim, indent=2))
    else:
        print("\n".join(report(doc)))
        if args.write:
            print("Wrote %s." % args.write)
        print("Next: /trader-budget sizes it to your budget and your max loss per trade.")
    return 0


def cmd_chart(args):
    if args.from_file:
        if not os.path.exists(args.from_file):
            raise TMError("no %s: run timemachine.py run --write first" % args.from_file)
        try:
            with open(args.from_file, encoding="utf-8") as fh:
                doc = json.load(fh)
            doc["mc"]["bands"]
        except (ValueError, KeyError, TypeError):
            raise TMError("%s is not a time machine result" % args.from_file)
    else:
        now = parse_now(args.now)
        doc = compute(args, now)
    print("\n".join(render_chart(doc)))
    print("\n".join([doc.get("verdict", "")] + list(doc.get("verdict_notes") or [])))
    return 0


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description="Time Machine: replay a planned day trade (trader-timemachine).")
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--plan", default="trader/plan.json", help="the plan from trader-exit")
        p.add_argument("--symbol", help="or give the plan as flags: ticker")
        p.add_argument("--side", default="buy", choices=["buy", "sell"])
        p.add_argument("--date", help="the plan's day, YYYY-MM-DD (default today, New York)")
        p.add_argument("--entry", type=float)
        p.add_argument("--stop", type=float)
        p.add_argument("--target", type=float)
        p.add_argument("--entry-time", help='the entry bar\'s close, e.g. "10:15 AM"')
        p.add_argument("--setup", default="orb")
        p.add_argument("--or-minutes", type=int, default=15)
        p.add_argument("--stop-rule", default="auto", choices=["auto", "or_mid", "or_low", "or_high", "pct"])
        p.add_argument("--replays", type=int, default=10000)
        p.add_argument("--seed", type=int, default=19)
        p.add_argument("--window", type=int, default=2, help="draw from the same time of day +- this many bars")
        p.add_argument("--until", help="end each replay at this time (default 16:00, the close)")
        p.add_argument("--offline", metavar="FILE", help="a saved Yahoo chart JSON (.json or .json.gz), no network")
        p.add_argument("--now", help='pretend it is this time ("2026-10-19 10:15" New York, or ISO with Z)')
        # Memory options
        mem_group = p.add_mutually_exclusive_group()
        mem_group.add_argument("--memory", action="store_true", default=None, help="force enable memory layer")
        mem_group.add_argument("--no-memory", action="store_true", help="force disable memory layer")
        p.add_argument("--recall-similar", action="store_true", default=None, help="recall similar setups from memory")
        p.add_argument("--store-outcome", action="store_true", default=None, help="store plan+result to memory")

    p = sub.add_parser("run", help="replay the plan: 10,000 simulated sessions plus the history")
    common(p)
    p.add_argument("--json", action="store_true")
    p.add_argument("--write", nargs="?", const="trader/timemachine.json", metavar="PATH",
                   help="save the result (default trader/timemachine.json)")
    p = sub.add_parser("chart", help="ASCII fan chart of the replays")
    common(p)
    p.add_argument("--from", dest="from_file", nargs="?", const="trader/timemachine.json", metavar="PATH",
                   help="draw a saved result instead of running again")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 1
    try:
        return {"run": cmd_run, "chart": cmd_chart}[a.cmd](a)
    except TMError as e:
        print("timemachine.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())