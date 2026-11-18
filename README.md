# The Trader skill

[![tests](https://github.com/KDhiraj152/trader-skill/actions/workflows/ci.yml/badge.svg)](https://github.com/KDhiraj152/trader-skill/actions/workflows/ci.yml)

12 skills for day trading: scan thousands of charts, track breaking news, time every entry and exit, replay every outcome before you risk a dollar, and dig into any stock: options, shorts, dark-pool flow, insider trades and the macro numbers.

Free, MIT, no signup, no API key. The tools are plain Python that read free
public data: Yahoo Finance charts, Nasdaq Trader's symbol lists, SEC EDGAR
and the House Clerk. One optional piece goes further: run a local OpenBB
server (free, no key) and the Research Desk reads options chains with the
greeks, short interest, dark-pool volume, insider trades and macro series
through it.

One scans thousands of charts for setups. Another tracks breaking news on
every stock you watch. One watches a setup bar by bar and tells you the moment
to get in, and another sets your stop and your target before you do. And the
craziest one is the Time Machine: before you risk a dollar, it replays the
rest of the session 10,000 times from the stock's own recent bars, plus every
past day the same setup fired, and tells you the honest odds.

And no trade goes through until you say yes. Nothing in this pack can place
an order on its own. Paper trading is the default.


## Install

Any agent that loads `SKILL.md` folders can run this. Pick the way that fits
yours:

**Copy the skill folders.** Clone the repo and copy the `trader-*` folders
into your agent's skill directory (each agent documents where that is; it is
often a `skills/` folder in your home directory or at the project root):

```bash
git clone https://github.com/KDhiraj152/trader-skill.git
cp -r trader-skill/trader-* <your agent's skill folder>/
```

**As a plugin.** The repo root has `plugin.json` and `marketplace.json` in
the neutral agent-plugins.org shape. Agents that read that manifest can
install the whole pack straight from this repo.

**No skill loader at all?** Paste any single `SKILL.md` at the top of a chat
and it runs as a mode. You lose the Python tools, but the method works.

The tools need Python 3.8 or newer. Nothing to pip install. The SEC tools
(news filings, the analyst) ask you to identify yourself: put your name and
email in `trader/config.json` (`"sec_user_agent": "Your Name you@example.com"`)
or in the `SEC_USER_AGENT` environment variable.

The Research Desk needs a running OpenBB server: install OpenBB, run
`openbb-api` from its environment, and the desk works. Without it, that
skill says so and the other eleven run as before.

## The twelve

| command | job | what it does |
| --- | --- | --- |
| `/trader-scanner` | Chart Scanner | Scans thousands of charts for setups: opening-range breakouts, flags, oversold bounces. |
| `/trader-news` | News Monitor | Tracks breaking news on every stock you watch and flags what moves it. |
| `/trader-entry` | Entry Timer | Watches a setup bar by bar and tells you the moment to get in. |
| `/trader-exit` | Exit Planner | Sets your stop and your target before you enter, so you know when to get out. |
| `/trader-timemachine` | Time Machine | Replays every possible outcome of a trade before you risk a dollar: 10,000 simulated sessions plus every past time the setup fired. |
| `/trader-risk` | Risk Manager | Checks every trade against your limits and stops anything over them. |
| `/trader-budget` | Budget Manager | Sizes every position to your budget and your max loss per trade. |
| `/trader-broker` | Order Executor | Sends approved orders to your broker, paper trading by default, never without your yes. |
| `/trader-alerts` | Price Alerts | Rings when a price, a stop or the opening bell hits. |
| `/trader-analyst` | Earnings Analyst | Reads earnings reports and sums up what changed. |
| `/trader-pelosi` | Pelosi Tracker | Reads Congress's stock-trade disclosures the minute they are filed. |
| `/trader-research` | Research Desk | Options chains with the greeks, short interest, dark-pool volume, insider trades, filings, the earnings calendar and macro series, from a local OpenBB server. |

## How to use it

Everything lands in a `trader/` folder in your project, and each skill reads
what the last one wrote:

```
scanner -> news -> entry -> exit -> timemachine -> budget -> risk -> broker   (one trade)
alerts: stop, target, flat by the close                                       (while it is open)
news / analyst / pelosi                                                        (on a schedule)
research: shorts, options, insiders, macro                                      (before and after)
```

An example, the trade in the reel: Tesla, Monday October 19 2026, real data.

1. **`/trader-scanner`** at 10:15 AM ET: of the 231 charts in the reel's
   scan, 42 had closed above their 15-minute opening range. TSLA is one: range 354.47 to 362.18,
   the 10:10 candle closed at 364.18, 0.55% over the top.
2. **`/trader-news`**: the morning's TSLA headlines, in New York time
   ("Tesla-SpaceX Merger Mania Strikes Wall Street Ahead of Earnings", 8:04,
   tagged earnings and deal). Tesla reports this week: a day trade is out
   before the close, so it is not exposed to the report.
3. **`/trader-entry`** watched TSLA bar by bar. At 10:12 it said waiting (the
   10:10 bar was still forming). At 10:15 it said triggered: the first
   5-minute close above the range, 364.18.
4. **`/trader-exit`** set the plan before the entry: stop at the range's
   midpoint, 358.32, so 5.86 a share at risk; target one times that risk,
   370.04; flat by 3:55 PM either way.
5. **`/trader-timemachine`** replayed the rest of the day 10,000 times, each
   5-minute candle drawn from TSLA's own candles at that time of day over the
   previous 59 sessions (seed 19, so anyone can repeat it): target first
   29.4%, stop first 25.5%, still open at the close 45.1%. It also re-ran
   the same rule on those 59 real sessions: it fired 33 times, 13 hit the
   target, 15 the stop, 5 neither. Its verdict: close to a coin flip. Which is
   exactly why you replay it first.
6. **`/trader-budget`** with a $5,000 account and a $50 max loss per trade:
   50 / 5.86 = 8 shares ($2,913.44). If the stop fills at 358.32, the loss is
   $46.88. It writes one bracket order: buy 8 TSLA, stop-loss 358.32,
   take-profit 370.04.
7. **`/trader-risk`** checks it against your limits: the max loss, the daily
   loss limit, trades per day, reward to risk, the entry window, position
   size and cash. PASS or BLOCK, with the reason.
8. **`/trader-broker`** shows you the ticket in plain words. You type yes for
   that exact order. Your agent calls your brokerage connector (Alpaca's MCP
   server, paper account by default), and its "Allow once / Deny" approval
   asks you one more time.
9. **`/trader-alerts`** rings on the stop, the target and at 3:55 PM to
   flatten whatever is still open.

## The tools

All standard-library Python. The data tools read public endpoints and are
polite about it.

```bash
python3 trader-scanner/scan.py universe                                # ~5,900 US stocks, Nasdaq Trader
python3 trader-scanner/scan.py daily                                   # pre-market setups, whole universe
python3 trader-scanner/scan.py orb --at 10:15                          # opening-range breakouts so far
python3 trader-news/news.py --tickers TSLA --hours 12                  # headlines, 8-Ks, today's move
python3 trader-entry/entry.py check TSLA --setup orb                   # waiting / triggered / expired
python3 trader-entry/entry.py watch TSLA --every 30                    # bar by bar until it triggers
python3 trader-exit/exit.py plan --stop or-mid --target 1R --write     # -> trader/plan.json
python3 trader-timemachine/timemachine.py run --write                  # 10,000 replays + the history
python3 trader-budget/size.py --write                                  # -> trader/orders.json
python3 trader-risk/check.py                                           # PASS / BLOCK per order
python3 trader-broker/ticket.py show                                   # the tickets, READY or not
python3 trader-alerts/alerts.py add --from-plan                        # stop, target, flat by close
python3 trader-alerts/alerts.py check                                  # rings what hit, once
python3 trader-analyst/facts.py TSLA                                   # quarters, growth, EPS
python3 trader-research/research.py shorts TSLA                        # short interest, days to cover
python3 trader-research/research.py chains TSLA --expiration 2026-11-20
python3 trader-research/research.py insider TSLA                       # Form 4 trades
python3 trader-research/research.py calendar --days 7                  # who reports this week
python3 trader-research/research.py macro FEDFUNDS                     # a macro series
python3 trader-pelosi/ptr.py index --member pelosi                     # her PTRs this year
```

```bash
python3 -m unittest discover -s tests -v
```

The tests run offline, on fixtures cut from real data: TSLA's 5-minute bars
for the 60 days to October 19 2026, the 10:15 AM opening-range scan, Yahoo's
TSLA headlines that morning, the House Clerk's 2026 index, real PTR text and
real XBRL facts. They reproduce every number in the example above.

## Fine print

**Not financial advice.** This is software that reads public data and does
arithmetic. It does not know your situation and it cannot see the future.
Most people who day trade lose money. You can lose money. Decide for
yourself, and talk to a licensed professional if you need advice.

**No trade goes through until you say yes.** Only `/trader-broker` can lead to
an order, and only after `/trader-risk` passes that exact order and you type
yes for it in the chat. Set your brokerage tool to "Needs approval" in your
agent's connector settings, never "Always allow", so its "Allow once / Deny"
prompt is a second check. No options, margin, short selling or leverage
unless you turn them on.

**Paper first.** `"paper": true` is the default in `config.example.json`, and
Alpaca's MCP server defaults to its paper account. Keys live in environment
variables, never in the chat.

**The Time Machine is a simulation, not a prediction.** It is built from the
stock's own last 60 days of 5-minute bars. The future can do things those 60
days never did: an earnings report, a halt, a headline. Treat its odds as a
reality check, never as a promise.

**A stop is a plan, not a guarantee.** In a fast market or across a gap, a
stop order can fill well past its price. The max loss shown is the loss at
the stop price.

**The data is free and unofficial.** Yahoo Finance's chart endpoint is not an
official API: it can lag, change or rate-limit you. The scanner and the entry
timer read 1-minute or 5-minute bars, not every tick. Check anything that
matters against your broker before you act on it.

**The research data is delayed, deliberately.** The Research Desk reads a
local OpenBB server, and its sources are not live feeds: CBOE quotes and
option chains are 15 minutes or more behind, FINRA short interest comes
twice a month, dark-pool volume weekly, and fails to deliver about a month
behind. None of it is a signal by itself; it is positioning context to read
next to the filings and the tape.

**Day-trading rules.** FINRA removed the $25,000 pattern-day-trader minimum
on June 4, 2026 (Regulatory Notice 26-10), and brokers may phase the change
in until October 20, 2027, so yours may still apply the old rule. If it does,
set `"pdt_guard": true` and `/trader-risk` counts your day trades.

**Congress's trades are public, not inside information.** Members must disclose
trades over $1,000 within 45 days (the STOCK Act). The Pelosi skill reads those
public filings the minute they post.

**Taxes.** Day-trading gains are short-term gains, and frequent trading makes
wash sales likely. Nothing here is tax advice.

## When something goes wrong

Most problems here are one of five things.

**A data source stopped answering.** Yahoo's chart endpoint is not an official
API: it can rate-limit you (empty or missing bars), change its JSON shape, or
just lag. If a scan comes back with no usable charts, wait a few minutes and
try again before assuming every stock died. The Nasdaq Trader lists, SEC
EDGAR and the House Clerk are more reliable, but they all publish on their
own schedule: the universe is rebuilt when you run `universe`, PTRs appear
when the Clerk posts them.

**SEC tools return nothing and say why.** EDGAR asks every automated user to
identify itself. Put your real name and email in `trader/config.json`
(`"sec_user_agent": "Your Name you@example.com"`) or set the `SEC_USER_AGENT`
environment variable. Without it the news tool still shows headlines and
just skips the filings.

**A guard refused your command and it looks like an error.** It is the tool
checking the data. The common ones:
a price quote older than 15 minutes is not used ("Sized at the plan's
entry"); a plan written on an earlier day is refused (make a new one with
`/trader-exit`); a risk check from an earlier day makes the ticket "NOT
READY" (run `check.py` again); an order without a stop is blocked while
`"require_stop"` is on, which is the default. Read the reason: it names the
file that is stale or the limit that was hit.

**The broker never receives anything.** That is the design. `/trader-broker`
only prints the ticket and the exact tool-call JSON; your agent's brokerage
connector is what actually places it, after you type yes for that one
order. If nothing happens after you say yes, check that the connector is
set up (`mcp_servers.example.json` shows the shape), that its
tool permission is "Needs approval" rather than "Always allow", and that
`"paper": true` is pointing at the paper account you expect.

**A PTR PDF will not parse.** `/trader-pelosi` falls back to printing the
PDF path so you can open it yourself. For automatic text extraction it
needs poppler: `brew install poppler` (macOS) or your package manager's
equivalent, then `ptr.py fetch` again.

**The research desk refuses to run.** It talks to a local OpenBB server and
there is none up: start it with `openbb-api --port 6900` from your OpenBB
environment, or point the desk elsewhere with `openbb_base_url` in
`trader/config.json`. The error names both. Agents that speak MCP can
connect `openbb-mcp` instead; the shape is in
`trader-research/mcp_servers.example.json`.

## Files

```
plugin.json          the neutral agent-plugins.org manifest (whole pack installs as one plugin)
marketplace.json     same, for agents that read a marketplace list
trader-scanner/     SKILL.md, scan.py
trader-news/        SKILL.md, news.py
trader-entry/       SKILL.md, entry.py
trader-exit/        SKILL.md, exit.py
trader-timemachine/ SKILL.md, timemachine.py
trader-risk/        SKILL.md, check.py
trader-budget/      SKILL.md, size.py, config.example.json, targets.example.json
trader-broker/      SKILL.md, ticket.py, mcp_servers.example.json
trader-alerts/      SKILL.md, alerts.py, alerts.example.json
trader-analyst/     SKILL.md, facts.py, metrics.example.json
trader-pelosi/      SKILL.md, ptr.py
trader-research/    SKILL.md, research.py, mcp_servers.example.json
portfolio/          the v1 basket: copycat, screener, tax, rebalance, plus the same pack as above
tests/              unittest suite + offline fixtures, for both the pack and the basket
```

MIT. Made by [K Dhiraj](https://github.com/KDhiraj152).
