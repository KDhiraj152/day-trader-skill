---
name: trader-broker
description: >-
  Order Executor. Places APPROVED orders through your brokerage connector, one
  at a time, and never without your explicit yes. Shows each order as a plain
  ticket plus the exact JSON for Alpaca's place_stock_order, records your yes
  word for word, then your agent's Allow once / Deny approval asks again. Covers
  setting up Alpaca's official MCP server (paper trading by
  default, keys in env vars, never in chat), the Interactive Brokers connector
  (orders go to your IBKR account for your approval), and setting order tools
  to "Needs approval". Use when the user says "place the orders", "buy it",
  "execute", "send it to my broker", "connect Alpaca", "connect Interactive
  Brokers", "set up paper trading", or after /trader-risk passes.
argument-hint: "[order number]"
---

# trader-broker

The Order Executor is the only skill in this pack that can lead to a real
order, so it is the strictest. An order reaches the market only after three
separate gates, every time, for every order:

1. **trader-risk passed this exact order today** (matched by fingerprint).
2. **The user typed an explicit yes for this one order** in the chat.
3. **The user approved the tool call** on your agent's permission prompt, which
   appears because the order tool is set to "Needs approval".

Two yeses from the user, one PASS from the rules. No yes, no order.

`${SKILL_DIR}` below is this skill's folder (where this SKILL.md lives). Your
agent sets it when it loads a skill; if it does not, substitute the folder's
path.

```bash
python3 "${SKILL_DIR}/ticket.py" show                     # every ticket, READY or not
python3 "${SKILL_DIR}/ticket.py" approve --index 1 --reply "yes"
python3 "${SKILL_DIR}/ticket.py" result --index 1 --status placed --broker-id ID
python3 "${SKILL_DIR}/ticket.py" fill --symbol AAPL --side buy --qty 3.6628 --price 341.27
python3 "${SKILL_DIR}/ticket.py" log
```

`ticket.py` never talks to a broker. It renders tickets, checks that a reply
is a real yes for that order, and keeps the log in `trader/state/broker.json`.

## Setup A: Alpaca (official MCP server, desktop app)

Alpaca's own server is github.com/alpacahq/alpaca-mcp-server (MIT). It runs on
the user's computer inside your agent's desktop app. It is not in most connector
directories. It trades on a **paper** account unless told otherwise.

1. The user makes an Alpaca account and creates **paper trading** API keys in
   the Alpaca dashboard. Paper keys are separate from live keys.
2. The user installs `uv` (it provides `uvx`), from docs.astral.sh/uv.
3. In your agent's desktop app, open the settings and find its MCP server
   config (most agents use the standard `mcpServers` shape shown in
   `mcp_servers.example.json` here; where the file lives differs per app).
   The user adds this block and types their own keys into the file:

```json
{
  "mcpServers": {
    "alpaca": {
      "command": "uvx",
      "args": ["alpaca-mcp-server"],
      "env": {
        "ALPACA_API_KEY": "paste your paper key here, in this file only",
        "ALPACA_SECRET_KEY": "paste your paper secret here, in this file only",
        "ALPACA_PAPER_TRADE": "true",
        "ALPACA_TOOLSETS": "account,trading,stock-data"
      }
    }
  }
}
```

   The `env` block hands the keys to the server as environment variables.
   **Keys never go in the chat.** Never ask for them, never read this file
   back into the conversation, and if the user pastes a key anyway, tell them
   to delete that message and make new keys in the Alpaca dashboard.
   `ALPACA_PAPER_TRADE` is already true by default; writing it makes it
   visible. `ALPACA_TOOLSETS` is optional and hides the tools they do not need.
4. Restart the app.
5. **Set the tool permissions.** In the app's connector or MCP tool settings,
   open alpaca, and for each tool pick Always allow, Needs
   approval or Blocked:
   - `place_stock_order`: **Needs approval**. Never Always allow.
   - every other tool that places, changes, cancels or closes anything
     (`cancel_order_by_id`, `close_position`, `update_account_config`): Needs approval.
   - `place_option_order`, `place_crypto_order`, `close_all_positions`,
     `cancel_all_orders`, `exercise_options_position`: **Blocked** unless the
     user has a reason and says so.
   - read-only tools (`get_account_info`, `get_all_positions`, `get_stock_snapshot`,
     `get_stock_latest_quote`): Always allow is fine.
6. Check it: ask your agent for the Alpaca account info (read only) and confirm
   in the Alpaca dashboard that it is the paper account.

If your agent runs headless instead of as a desktop app, keep the order tool
on ask in its permission settings (an "ask" list naming the place_stock_order
tool), and never put an order tool in its allow list.

## Setup B: Interactive Brokers (MCP endpoint)

Interactive Brokers publishes an MCP endpoint:
`https://api.ibkr.com/v1/api/mcp`. If your agent has a connector directory,
add it from there and sign in to IBKR there, not in the chat.
Its listing says the agent can draft trade instructions that are sent to the
user's IBKR account for their review and approval, and that nothing ever
submits orders directly to the market. So with IBKR the final yes happens in
IBKR as well. Set `"broker": "ibkr"` in `trader/config.json`, and size with
`--whole-shares` if IBKR wants share counts. Set its tools that draft orders
to Needs approval too.

## Steps, for each order

1. `ticket.py show`. Only READY tickets go to the user. A ticket that is NOT
   READY or BLOCKED goes back to `/trader-risk`.
2. Show ONE ticket and ask: "Place this order? Reply yes or no." One order
   per question. Never offer "yes to all".
3. Run `ticket.py approve --index N --reply "<the user's reply, word for word>"`.
   If it prints "Not recorded", the reply was not an explicit yes for this
   order (for example "sure", "yes to all", or a yes that names a different
   stock or amount). Ask again. Never turn a reply into a yes yourself.
4. Only after "Recorded your yes", call `place_stock_order` with exactly the
   JSON the ticket printed. Your agent's approval prompt appears: Allow once or Deny.
5. Record what happened: `ticket.py result --index N --status placed
   --broker-id <id from the response>`, or `--status denied` if they pressed
   Deny, or `--status failed` with `--note` for an error. A failed order is
   not retried without a new check and a new yes.
6. When the fill is known (the tool's response, or later from
   `get_all_positions`), `ticket.py fill` adds it to `trader/portfolio.json`
   as a tax lot for trader-tax. Then the next ticket.

## Example: the reel

```
ORDER 1 of 5, PAPER account, Alpaca
  BUY $1,250 of AAPL, market order, good for today
  READY: trader-risk PASS, waiting for your yes
  Your agent will call place_stock_order with exactly:
    {"symbol": "AAPL", "side": "buy", "notional": "1250",
     "type": "market", "time_in_force": "day"}
```

The user replies "yes". The agent records it, calls `place_stock_order`, and
the approval prompt shows that JSON with two buttons: Allow once, Deny. Allow once sends it to the paper account.

## What it never does

- Never places an order without all three gates, and never two orders on one yes.
- Never places orders from a scheduled or background task: nobody is there to say yes.
- Never asks for, reads, stores or repeats API keys or passwords.
- Never switches `ALPACA_PAPER_TRADE` or `"paper"` to live. The user does that themselves.
- Never calls `close_all_positions`, `cancel_all_orders`, option or crypto order tools on its own.

## Safety

- Education and tooling, not financial advice. No order here is a recommendation, and nothing promises returns.
- Paper trading by default (`"paper": true`, `ALPACA_PAPER_TRADE` true). Going live is the user's own decision.
- Nothing in this pack places an order except trader-broker, and only when all three hold: trader-risk
  passed that exact order today, the user typed an explicit yes for that one order in the chat, and the
  user clicked Allow once on your agent's approval card because the order tool is set to "Needs approval"
  (Customize > Connectors > tool permissions). Never set an order tool to "Always allow".
- No options, margin, short selling or leverage unless the config allows it and the user confirms.
- Broker keys live in environment variables or your agent's MCP config, never in the chat.
