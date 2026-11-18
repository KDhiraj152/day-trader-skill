#!/usr/bin/env python3
"""Research desk for trader-research. Standard library only.

Reads the data a plain day-trading pack does not carry: options chains with
the greeks, short interest and days to cover, dark-pool volume, fails to
deliver, insider trades, the filings list, headline news, the earnings
calendar and macro series. The source is a local OpenBB server you run
(free, no key); this tool talks to it over plain HTTP, so it stays
standard-library Python and works from any agent.

    python3 research.py quote TSLA            # delayed quote, iv30, year range
    python3 research.py shorts TSLA           # short interest, days to cover
    python3 research.py darkpool TSLA         # weekly dark-pool volume
    python3 research.py ftd TSLA              # fails to deliver
    python3 research.py insider TSLA          # recent Form 4 trades
    python3 research.py filings TSLA          # the company's filings list
    python3 research.py chains TSLA           # expirations and contract counts
    python3 research.py chains TSLA --expiration 2026-11-20
    python3 research.py news TSLA             # headlines
    python3 research.py calendar --days 7     # who reports this week
    python3 research.py macro FEDFUNDS        # a macro series, latest values
    python3 research.py --json quote TSLA     # everything machine-readable

The server: install OpenBB (free), then from its environment run
`openbb-api`. The desk calls http://127.0.0.1:6900/api/v1/... (change it with
`openbb_base_url` in trader/config.json or the OPENBB_BASE_URL variable).
Agents that speak MCP can point at `openbb-mcp` instead: the shape is in
mcp_servers.example.json in this folder. When the server is down the desk
says so and how to start it; nothing else in the pack needs it.

Offline: --offline DIR reads quote-<SYMBOL>.json, shorts-<SYMBOL>.json,
darkpool-<SYMBOL>.json, ftd-<SYMBOL>.json, insider-<SYMBOL>.json,
filings-<SYMBOL>.json, chains-<SYMBOL>.json, news-<SYMBOL>.json,
calendar.json and macro-<SERIES>.json from DIR. The tests use it.

Every quote here is delayed (15 minutes or more, often a day for the
regulatory data). Nothing here places an order, and nothing here is advice.
"""

import argparse
import datetime as _dt
import io
import json
import os
import sys
import urllib.parse
import urllib.request

DEFAULT_BASE = "http://127.0.0.1:6900"
API = "/api/v1"
TIMEOUT = 90


class ResearchError(Exception):
    """A condition worth reading, not a stack trace."""


def _get(path, params, base=None, offline_dir=None, offline_name=None):
    """One call to the server (or one fixture file offline) -> list of rows."""
    if offline_dir:
        path_file = os.path.join(offline_dir, offline_name)
        if not os.path.exists(path_file):
            raise ResearchError("offline file %s is not there" % offline_name)
        with open(path_file, encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("results") or []
    root = base or read_base()
    url = root.rstrip("/") + API + path + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as res:
            data = json.load(res)
    except (OSError, ValueError) as err:  # URLError subclasses OSError
        reason = getattr(err, "reason", None) or err
        raise ResearchError(
            "the OpenBB server is not answering (%s). Start it from your OpenBB "
            "environment: openbb-api --port 6900. Point the desk somewhere else "
            "with openbb_base_url in trader/config.json or OPENBB_BASE_URL."
            % reason)
    if not isinstance(data, dict) or data.get("results") is None:
        raise ResearchError("the server returned something this desk cannot read")
    warnings = data.get("warnings")
    if warnings:
        print("note: %s" % "; ".join(str(w.get("message") or w) for w in warnings),
              file=sys.stderr)
    return data["results"]


def read_base():
    """The server address: --base, OPENBB_BASE_URL, then trader/config.json."""
    env = os.environ.get("OPENBB_BASE_URL")
    if env:
        return env
    for candidate in (os.path.join("trader", "config.json"),):
        if os.path.exists(candidate):
            try:
                with open(candidate, encoding="utf-8") as fh:
                    cfg = json.load(fh)
                if cfg.get("openbb_base_url"):
                    return cfg["openbb_base_url"]
            except (OSError, ValueError):
                pass
    return DEFAULT_BASE


def _num(value, dash=True):
    """A readable number: 12,345.6 or a dash."""
    if value is None:
        return "-" if dash else ""
    if isinstance(value, float) and abs(value) >= 1000:
        return "{:,.0f}".format(value)
    if isinstance(value, float):
        return "{:,.2f}".format(value)
    return "{:,}".format(value)


def _as_pct(value):
    """0.0123 -> 1.23%."""
    if value is None:
        return "-"
    return "%.2f%%" % (float(value) * 100.0)


def _head(title, cols, widths):
    """One shared table header so every section prints the same way."""
    print(title)
    print("  ".join(str(c).ljust(w) for c, w in zip(cols, widths)))


def _row(cols, widths):
    print("  ".join(str(c).ljust(w) for c, w in zip(cols, widths)))


def show_quote(args):
    rows = _get("/cboe/equity/quote", {"symbol": args.symbol}, args.base,
                args.offline, "quote-%s.json" % args.symbol)
    if not rows:
        raise ResearchError("no quote for %s" % args.symbol)
    q = rows[0]
    _head("%s %s  (delayed)" % (q.get("symbol"), q.get("name") or ""),
          [], [])
    print("  last %s  bid %s x %s  ask %s x %s  tick %s at %s"
          % (_num(q.get("last_price")), _num(q.get("bid")), _num(q.get("bid_size")),
             _num(q.get("ask")), _num(q.get("ask_size")), q.get("last_tick"),
             q.get("last_timestamp")))
    print("  open %s  high %s  low %s  prev close %s  volume %s"
          % (_num(q.get("open")), _num(q.get("high")), _num(q.get("low")),
             _num(q.get("prev_close")), _num(q.get("volume"))))
    print("  52w %s to %s  change %s (%s)"
          % (_num(q.get("year_low")), _num(q.get("year_high")),
             _num(q.get("change")), _as_pct(q.get("change_percent"))))
    print("  iv30 %s  (30-day implied vol; yearly range %s to %s)"
          % (_as_pct(q.get("iv30")), _as_pct(q.get("iv30_annual_low")),
             _as_pct(q.get("iv30_annual_high"))))
    return rows


def cmd_shorts(args):
    rows = _get("/finra/equity/shorts/short_interest", {"symbol": args.symbol},
                args.base, args.offline, "shorts-%s.json" % args.symbol)
    if not rows:
        raise ResearchError("no short interest for %s" % args.symbol)
    rows = sorted(rows, key=lambda r: str(r.get("settlement_date")), reverse=True)
    _head("Short interest, %s, %d settlements" % (args.symbol, len(rows)),
          ["settle", "short pos", "days cover", "vs prev", ""],
          [12, 14, 10, 10, 8])
    for r in rows[:args.limit]:
        change = r.get("change_pct")
        _row([str(r.get("settlement_date")), _num(r.get("current_short_position")),
              _num(r.get("days_to_cover")),
              "-" if change is None else "%.2f%%" % float(change),
              str(r.get("market_class") or "")[:8]], [12, 14, 10, 10, 8])
    return rows


def cmd_darkpool(args):
    rows = _get("/finra/equity/darkpool/otc", {"symbol": args.symbol},
                args.base, args.offline, "darkpool-%s.json" % args.symbol)
    if not rows:
        raise ResearchError("no dark-pool rows for %s" % args.symbol)
    rows = sorted(rows, key=lambda r: str(r.get("update_date")), reverse=True)
    _head("Dark-pool (ATS) volume, %s, by week" % args.symbol,
          ["week start", "dark shares", "trades", "avg trade size"],
          [12, 14, 12, 15])
    for r in rows[:args.limit]:
        shares = r.get("share_quantity") or 0
        trades = r.get("trade_quantity") or 0
        size = (shares / trades) if trades else None
        _row([str(r.get("week_start_date")), _num(shares), _num(trades),
              _num(size)], [12, 14, 12, 15])
    print("  weekly FINRA data: shares executed in dark pools and how big each trade was;")
    return rows


def cmd_ftd(args):
    rows = _get("/sec/equity_ftd", {"symbol": args.symbol}, args.base,
                args.offline, "ftd-%s.json" % args.symbol)
    if not rows:
        raise ResearchError("no fails-to-deliver for %s" % args.symbol)
    rows = sorted(rows, key=lambda r: str(r.get("settlement_date")), reverse=True)
    _head("Fails to deliver, %s, %d recent days" % (args.symbol, len(rows)),
          ["settle", "shares", "price"], [12, 12, 10])
    for r in rows[:args.limit]:
        _row([str(r.get("settlement_date")), _num(r.get("quantity")),
              _num(r.get("price"))], [12, 12, 10])
    return rows


def cmd_insider(args):
    rows = _get("/sec/insider_trading", {"symbol": args.symbol},
                args.base, args.offline, "insider-%s.json" % args.symbol)
    if not rows:
        raise ResearchError("no insider trades for %s" % args.symbol)
    rows = sorted(rows, key=lambda r: str(r.get("filing_date")), reverse=True)
    _head("Insider trades, %s" % args.symbol,
          ["filed", "who", "role", "what", "shares", "price"],
          [11, 18, 22, 34, 9, 9])
    for r in rows[:args.limit]:
        what = str(r.get("transaction_type") or "")
        _row([str(r.get("filing_date")),
              str(r.get("owner_name") or "")[:18],
              str(r.get("owner_title") or "")[:22],
              what[:34], _num(r.get("securities_transacted")),
              _num(r.get("transaction_price"))],
             [11, 18, 22, 34, 9, 9])
    return rows


def cmd_filings(args):
    rows = _get("/sec/company_filings", {"symbol": args.symbol}, args.base,
                args.offline, "filings-%s.json" % args.symbol)
    if not rows:
        raise ResearchError("no filings for %s" % args.symbol)
    rows = sorted(rows, key=lambda r: str(r.get("filing_date")), reverse=True)
    _head("Filings, %s, %d in the window" % (args.symbol, len(rows)),
          ["filed", "form", "what", "link"], [11, 10, 26, 10])
    for r in rows[:args.limit]:
        _row([str(r.get("filing_date")), str(r.get("report_type") or ""),
              str(r.get("primary_doc_description") or "")[:26],
              str(r.get("filing_detail_url") or "")], [11, 10, 26, 10])
    return rows


def cmd_chains(args):
    rows = _get("/nasdaq/options/chains", {"symbol": args.symbol}, args.base,
                args.offline, "chains-%s.json" % args.symbol)
    if not rows:
        raise ResearchError("no option chains for %s" % args.symbol)
    exps = {}
    for r in rows:
        exps[str(r.get("expiration"))] = exps.get(str(r.get("expiration")), 0) + 1
    if not args.expiration:
        _head("Options, %s, spot %s" % (args.symbol,
               _num(rows[0].get("underlying_price"))),
              ["expiration", "contracts"], [12, 10])
        for exp in sorted(exps):
            _row([exp, str(exps[exp])], [12, 10])
        print("  pick one: --expiration YYYY-MM-DD (dates are Nasdaq's, greeks included)")
        return rows
    picked = [r for r in rows if str(r.get("expiration")) == args.expiration]
    if not picked:
        raise ResearchError("no contracts at %s; the expirations are listed above" % args.expiration)
    spot = picked[0].get("underlying_price")
    picked.sort(key=lambda r: (r.get("option_type") or "", abs((r.get("strike") or 0) - (spot or 0))))
    _head("%s %s, spot %s (delayed)" % (args.symbol, args.expiration, _num(spot)),
          ["type", "strike", "last", "bid x ask", "oi", "iv", "delta", "theta"],
          [5, 8, 9, 14, 7, 7, 7, 7])
    for r in picked[:args.limit * 2]:
        _row([r.get("option_type"), _num(r.get("strike")), _num(r.get("last_trade_price")),
              "%s x %s" % (_num(r.get("bid")), _num(r.get("ask"))),
              _num(r.get("open_interest")), _num(r.get("implied_volatility")),
              _num(r.get("delta")), _num(r.get("theta"))],
             [5, 8, 9, 14, 7, 7, 7, 7])
    return picked


def cmd_news(args):
    rows = _get("/nasdaq/news/company", {"symbol": args.symbol, "limit": args.limit},
                args.base, args.offline, "news-%s.json" % args.symbol)
    if not rows:
        raise ResearchError("no headlines for %s" % args.symbol)
    print("Headlines, %s" % args.symbol)
    for r in rows:
        print("  %s  %s  %s" % (str(r.get("date") or "")[:16],
                                str(r.get("publisher") or "")[:14],
                                r.get("title")))
        if args.urls:
            print("      %s" % r.get("url"))
    return rows


def cmd_calendar(args):
    start = _dt.date.today()
    end = start + _dt.timedelta(days=args.days)
    rows = _get("/nasdaq/equity/calendar/earnings",
                {"start_date": start.isoformat(), "end_date": end.isoformat()},
                args.base, args.offline, "calendar.json")
    if not rows:
        raise ResearchError("no earnings on the calendar for the next %d days" % args.days)
    rows = sorted(rows, key=lambda r: str(r.get("report_date")))
    _head("Earnings, %s to %s, %d companies" % (start, end, len(rows)),
          ["date", "symbol", "eps est", "when"], [11, 8, 9, 8])
    for r in rows[:args.limit]:
        _row([str(r.get("report_date")), str(r.get("symbol")),
              _num(r.get("eps_consensus")),
              str(r.get("time_of_day") or r.get("report_time") or "")[:8]],
             [11, 8, 9, 8])
    return rows


def cmd_macro(args):
    rows = _get("/fred/economy/fred_series", {"symbol": args.series, "limit": args.points},
                args.base, args.offline, "macro-%s.json" % args.series)
    if not rows:
        raise ResearchError("no series data for %s" % args.series)
    key = None
    for k, v in rows[-1].items():
        if k != "date" and isinstance(v, (int, float)):
            key = k
            break
    print("Macro, %s (%s)" % (args.series, key or "value"))
    for r in rows:
        print("  %s  %s" % (r.get("date"), _num(r.get(key))))
    return rows


COMMANDS = {
    "quote": (show_quote, "symbol", "delayed quote, iv30, year range"),
    "shorts": (cmd_shorts, "symbol", "short interest, days to cover"),
    "darkpool": (cmd_darkpool, "symbol", "weekly dark-pool volume"),
    "ftd": (cmd_ftd, "symbol", "fails to deliver"),
    "insider": (cmd_insider, "symbol", "recent Form 4 trades"),
    "filings": (cmd_filings, "symbol", "the filings list"),
    "chains": (cmd_chains, "symbol", "options chains with the greeks"),
    "news": (cmd_news, "symbol", "headlines"),
    "calendar": (cmd_calendar, None, "who reports, the week ahead"),
    "macro": (cmd_macro, "series", "a FRED macro series"),
}


def _add_subcommands(sub):
    """The per-command flags, so main stays small enough to read."""
    for name, (fn, argname, help_text) in sorted(COMMANDS.items()):
        sp = sub.add_parser(name, help=help_text)
        if argname:
            sp.add_argument(argname, help="%s to read" % argname)
        if name == "chains":
            sp.add_argument("--expiration", default=None, help="YYYY-MM-DD; without it, list expirations")
        if name in ("shorts", "darkpool", "ftd", "insider", "filings", "chains", "news", "calendar"):
            sp.add_argument("--limit", type=int, default=10, help="rows to show")
        if name == "news":
            sp.add_argument("--urls", action="store_true", help="print each link")
        if name == "calendar":
            sp.add_argument("--days", type=int, default=7, help="days ahead, default 7")
        if name == "macro":
            sp.add_argument("--points", type=int, default=6, help="values to show")
        sp.set_defaults(fn=fn)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default=None, help="OpenBB server root, default %s" % DEFAULT_BASE)
    ap.add_argument("--offline", default=None, metavar="DIR",
                    help="read fixtures from DIR instead of the server (tests)")
    ap.add_argument("--json", action="store_true", help="print the raw rows as JSON")
    _add_subcommands(ap.add_subparsers(dest="command"))
    args = ap.parse_args()
    if not args.command:
        ap.print_help()
        return 0
    try:
        sink = io.StringIO() if args.json else None
        old = sys.stdout
        if sink is not None:
            sys.stdout = sink
        try:
            rows = args.fn(args)
        finally:
            sys.stdout = old
    except ResearchError as err:
        print("ResearchError: %s" % err, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(rows, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
