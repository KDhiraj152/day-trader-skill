---
name: trader-research
description: >-
  The Research Desk. Reads what a day-trading pack does not carry, from a
  local OpenBB server you run: options chains with the greeks (delta, gamma,
  theta, vega, IV, open interest), short interest with days to cover, weekly
  dark-pool volume, fails to deliver, insider trades, the SEC filings list,
  headline news, the week's earnings calendar and macro series (rates,
  inflation, whatever FRED carries). Delayed data, free, no key. Use when
  the user says "check the option chain", "how shorted is this stock",
  "dark pool volume", "who reports this week", "what are the insiders
  doing", "show me the yield curve", "what is the IV on Tesla" or wants
  research for a swing or position trade, not just today's session.
argument-hint: "[command] [symbol]"
---

# trader-research

The rest of this pack answers "what is happening in this session". This skill
answers the questions you ask before and after one: how is this stock
positioned, what are the insiders and the shorts doing, when does the next
report land, and what are rates and inflation doing to everything. For a day
trade it is context; for a swing or position it is the desk.

It reads a local OpenBB server over plain HTTP. OpenBB is free and open
source; the server keeps working offline and needs no key. The tool in this
folder is standard-library Python, so it runs anywhere the rest of the pack
runs.

## One-time setup

Install OpenBB once (any supported Python; it is heavier than this pack, so
give it its own environment), then from that environment:

```bash
openbb-api --port 6900        # the REST server this desk reads
```

Leave it running when you want the desk. Without it, the desk says exactly
that and stops cleanly; nothing else in the pack needs it.

`${SKILL_DIR}` below is this skill's folder (where this SKILL.md lives). Your
agent sets it when it loads a skill; if it does not, substitute the folder's
path.

```bash
python3 "${SKILL_DIR}/research.py" --help
```

The address defaults to `http://127.0.0.1:6900`. Change it with
`"openbb_base_url"` in `trader/config.json` or the `OPENBB_BASE_URL`
environment variable.

## The commands

```bash
python3 "${SKILL_DIR}/research.py" quote TSLA          # delayed quote, iv30, year range
python3 "${SKILL_DIR}/research.py" shorts TSLA         # short interest, days to cover
python3 "${SKILL_DIR}/research.py" darkpool TSLA       # weekly dark-pool volume
python3 "${SKILL_DIR}/research.py" ftd TSLA            # fails to deliver
python3 "${SKILL_DIR}/research.py" insider TSLA        # recent Form 4 trades
python3 "${SKILL_DIR}/research.py" filings TSLA        # the filings list
python3 "${SKILL_DIR}/research.py" chains TSLA         # expirations, contract counts
python3 "${SKILL_DIR}/research.py" chains TSLA --expiration 2026-11-20
python3 "${SKILL_DIR}/research.py" news TSLA           # headlines
python3 "${SKILL_DIR}/research.py" calendar --days 7   # who reports this week
python3 "${SKILL_DIR}/research.py" macro FEDFUNDS      # a macro series
python3 "${SKILL_DIR}/research.py" --json quote TSLA   # the raw rows
```

`--limit` caps the rows on most commands; `--urls` on news prints the links.

## What each answer means

- **Shorts** (`finra`): position and days to cover, twice a month. Days to
  cover near or above 5 is a crowded short; a squeeze needs more than that,
  so never call one from this line alone.
- **Dark pool** (`finra`): weekly shares executed in dark pools and the
  average trade size. Big blocks hiding from the lit exchanges say nothing
  on their own about direction.
- **FTD** (`sec`): Reg SHO failures to deliver, two days or more after the
  trade. Occasional small ones are plumbing; persistent large ones are a
  fact worth reading.
- **Insider** (`sec`): Form 4 filings. Sales against a 10b5-1 plan and
  option exercises are routine; clustered open-market buys are the rare
  thing worth noticing.
- **Chains** (`nasdaq`): every expiration with contract counts; add
  `--expiration` for a near-the-money table with the greeks. IV next to the
  stock's own 30-day vol (in `quote`) tells you whether options are priced
  rich or cheap against what the stock actually does.
- **Calendar** (`nasdaq`): every report date in the window. Before any
  trade that holds over a report date, check here: a stop does not protect
  against a gap.
- **Macro** (`fred`): any series FRED carries. `FEDFUNDS`, `CPIAUCSL`,
  `DGS10`, `T10YIE` are the usual suspects.

## How it fits the pack

The desk reads; it never orders, sizes or blocks. Pair it:

- With `/trader-analyst`: the analyst reads the company's own filed numbers;
  the desk adds positioning, options and the calendar around them.
- With `/trader-exit` and `/trader-budget`: a plan that holds over a report
  date or an FOMC day (`calendar`, `macro`) is a different risk than one
  that does not; say so before the plan is written.
- With `/trader-news`: the news tool watches live headlines; the desk adds
  the slower filings and insider record.

## What it never does

- Never places, sizes or blocks an order. Only `/trader-broker` does, after
  `/trader-risk` passes and you type yes.
- Never calls a stock a buy or a sell. It reports what the data says and
  leaves the read to you.
- Never pretends the data is live. Quotes are delayed (CBOE quotes and all
  options data 15 minutes or more; FINRA weekly; SEC FTD about a month
  behind). It says so on the page and you should say so out loud.

## Safety

Education and tooling, not financial advice. This skill only reads data.
Nothing places an order except `/trader-broker`, after `/trader-risk` passes
and the user types an explicit yes for that order.
