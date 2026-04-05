# PowerTrader AI — Complete Project Summary
## Version 1.3 | April 5, 2026

---

## Project Overview

**Bot:** PowerTrader AI — autonomous cryptocurrency trading bot  
**Exchange:** Robinhood (crypto API)  
**Language:** Python 3  
**Platform:** Windows (primary deployment)  
**Account Size:** ~$510 (live, funded, actively trading)  
**Status:** Fully operational — making buys, DCA trades, and profitable sells

---

## Files in Project

| File | Role |
|---|---|
| `pt_trader.py` | Core trading engine — order execution, DCA logic, position management, tax export |
| `pt_hub.py` | GUI dashboard — tkinter interface, charts, account display, controls, tax export button |
| `pt_thinker.py` | Neural network runner — generates buy/sell signal levels |
| `pt_trainer.py` | Neural network trainer — trains models on market data |
| `gui_settings.json` | User-configurable settings — coins, allocations, account mode |

**Runtime data files (auto-generated):**
- `hub_data/trader_status.json` — live position data written by trader, read by hub
- `hub_data/trade_history.jsonl` — one JSON line per completed trade
- `hub_data/pnl_ledger.json` — cumulative P&L tracking
- `hub_data/account_value_history.jsonl` — account value snapshots over time
- `hub_data/form_8949_trades_YYYY.csv` — IRS Form 8949 tax export (generated on demand)

---

## Session 1: Small Account Optimization (Primary Build)

### Problem Statement

The bot was originally designed for large accounts ($10,000+). Running it on a $250 account produced four critical issues:

**Issue 1 — Position sizing too small**
- `start_allocation_pct` was 0.005%, meaning $250 × 0.005% = $0.0125 → floored to $0.50
- 99% of capital sat idle; only $0.50 positions were opened

**Issue 2 — Exponential DCA destroyed small accounts**
- DCA multiplier of 2.0 caused: $0.50 → $1 → $3 → $9 → $27 → $81 → $243
- By stage 4 (−30%), one position required $81 — a third of the entire account

**Issue 3 — No position limits**
- Bot tried to open positions in all qualifying coins simultaneously
- 8 coins × exponential DCA = impossible capital requirements on $250

**Issue 4 — Inverted risk/reward**
- Take profits: +2.5% to +5%
- Accept losses: up to −50% (no hard stop)
- Result: needed 2,430 winning trades to recover one full loser

### Solution: Account Tier System

A three-mode detection system was added to `pt_trader.py`:

```
account_mode = "auto"         → Detects account size, applies appropriate settings
account_mode = "small"        → Forces small account mode regardless of size
account_mode = "force_existing" → Uses original large-account settings (100% backward compatible)
```

**Threshold:** `small_account_threshold: 2500` — accounts below $2,500 use small account settings

### Small Account Settings Applied

| Setting | Original | Small Account | Reason |
|---|---|---|---|
| `start_allocation_pct` | 0.005% | 10.0% | $25 positions vs $0.50 |
| `dca_multiplier` | 2.0 (exponential) | 1.0 (linear) | Equal size DCA buys |
| `dca_levels` | 7 levels (−2.5% to −50%) | 3 levels (−7.5%, −15%, −25%) | Fewer, wider triggers |
| `max_dca_buys_per_24h` | 2 | 1 | Prevents panic averaging |
| `pm_start_pct_no_dca` | 5.0% | 8.0% | Higher profit target |
| `pm_start_pct_with_dca` | 2.5% | 5.0% | Higher profit after DCA |
| `trailing_gap_pct` | 0.5% | 1.5% | Wider trail, less noise exits |
| `max_positions` | unlimited | 3 | Prevents correlation overload |
| `reserve_minimum_pct` | 0% | 20% | Always keep $50 liquid |
| `hard_stop_enabled` | false | true | Force-exit at −35% |
| `hard_stop_pct` | N/A | −35.0% | Capital preservation floor |
| `require_neural_dca_confirmation` | false | true | Quality DCA entries only |

---

## Session 2: Account Value Calculation Fix

`get_account_value()` was updated to return `buying_power + cost_of_held_positions` rather than just `buying_power`. This ensures accurate account value display and proper tier detection even when most capital is deployed.

---

## Session 3: Tiered Profit Taking System

A tiered profit taking mode was added to replace the all-or-nothing exit strategy:

- **Tier 1:** When position reaches +7% gain → sell 33% of holdings
- **Tier 2:** When remaining position reaches +15% gain → sell 50% of what remains
- **Trail:** Remainder is trailed with trailing gap until stopped out

---

## Session 4: Account Box Metrics Enhancement (pt_hub.py)

Four new metrics added to the GUI account box:
1. **Win Rate %** — calculated from `trade_history.jsonl`
2. **Average Win / Average Loss** — separate averages for winning and losing trades
3. **Best / Worst Performing Coin** — groups closed trades by symbol, sums realized P&L
4. **Hard Stops Triggered Count** — counts trades tagged as "HARD_STOP"

---

## Session 5: Manual Buy & Manual Sell Panels (pt_hub.py)

**Manual Buy Panel** — place one-off market buys from the Hub GUI with auto coin-add, folder scaffolding, and optional auto-train after purchase.

**Manual Sell Panel** — select a held coin from a dropdown and sell 100% from the GUI.

---

## Session 6: Trailing Profit Manager Bug Fix

Diagnosed and fixed two compounding bugs in `pt_trader.py` that caused the `was_above` flag to reset on every startup, preventing sell triggers from arming. Introduced `_small_account_active` boolean guard to prevent hot-reload from overwriting small account PM values.

---

## Session 7: Trainer Crash Bug Fix

Fixed a nested exception in `pt_trainer.py` where an exception in the fallback memory-save block propagated up to a `break` statement, killing the candle processing loop prematurely. Wrapped fallback/cleanup code in its own `try/except: pass`.

---

## Session 8: Paginated Orders, Decimal Precision & Tax Export (April 5, 2026)

### Problem Statement

Three issues identified during a comprehensive comparison with the upstream PowerTrader AI repository:

1. **Single-page order fetching** — `get_orders()` only read the first page of Robinhood's paginated API response. If a coin accumulated enough orders, older bot buys could fall off page 1, breaking cost basis reconstruction.

2. **Float-precision P&L accumulation** — All fill extraction and fee handling used Python `float` math. Over hundreds of trades, small rounding errors compound and create discrepancies between the bot's P&L records and Robinhood's actual accounting.

3. **No tax reporting capability** — With the bot potentially executing hundreds of trades per year, manually entering each one on IRS Form 8949 was impractical. The bot already tracked every trade in `trade_history.jsonl` but had no way to export it in a tax-ready format.

### Changes Made

**1. Paginated Order Fetching** *(pt_trader.py)*

`get_orders()` now follows Robinhood's pagination links up to 25 pages per coin (approximately 500 orders per coin). This prevents cost basis corruption when many orders accumulate. Adapted from the upstream PowerTrader AI implementation.

**2. Decimal Precision for P&L** *(pt_trader.py)*

New method `_extract_amounts_and_fees_from_order()` uses Python's `Decimal` type with `ROUND_HALF_UP` for cent-accurate P&L tracking. It prefers Robinhood's order-level filled fields (their own accounting) and falls back to execution-level sums. This method now replaces the float-math extraction in `place_buy_order()`, `place_sell_order()`, and `_reconcile_pending_orders()`. The original `_extract_fill_from_order()` is preserved untouched as a fallback.

New imports added: `from decimal import Decimal, ROUND_HALF_UP` and `import csv` — both Python standard library, no new pip dependencies.

**3. IRS Form 8949 CSV Export** *(pt_trader.py + pt_hub.py)*

New `export_8949_csv()` method in `pt_trader.py` reads `trade_history.jsonl` and produces a CSV with the exact columns required by IRS Form 8949:

| CSV Column | Form 8949 Column |
|---|---|
| Description of property | (a) |
| Date acquired | (b) |
| Date sold | (c) |
| Proceeds (sales price) | (d) |
| Cost or other basis | (e) |
| Code | (f) |
| Adjustment | (g) |
| Gain or (loss) | (h) |

Additional columns included for record-keeping: Hold Period (Short/Long), Symbol, Trade Tag, Order ID.

The export uses Decimal math throughout, tracks buy accumulation per coin, allocates cost basis pro-rata on partial sells, and correctly identifies short-term vs long-term holding periods. A totals row is appended at the bottom.

New GUI panel "Tax Export (Form 8949)" added to `pt_hub.py` in the Controls / Health tab, below the Manual Sell panel:

```
[ Tax Year: [2026] ] [ Export 8949 CSV ]
Status: Ready
```

When clicked, the export runs in a background thread, writes the CSV to `hub_data/form_8949_trades_YYYY.csv`, and opens the containing folder automatically.

### What Was NOT Changed

- `pt_thinker.py` — no changes
- `pt_trainer.py` — no changes
- `requirements.txt` — no changes (csv and decimal are Python standard library)
- All existing trading logic, small account mode, hard stop, tiered profits, trailing PM, DCA logic — all identical
- Zero deleted methods, zero modified method signatures

---

## Current Live Configuration (gui_settings.json)

```json
{
  "main_neural_dir": "c:\\PowerTraderAI",
  "coins": ["BTC", "ETH", "SOL", "DOGE", "XRP", "ETC", "PAXG", "AVAX"],
  "trade_start_level": 3,
  "start_allocation_pct": 2.0,
  "dca_multiplier": 2.0,
  "dca_levels": [-2.5, -5.0, -10.0, -20.0, -30.0, -40.0, -50.0],
  "max_dca_buys_per_24h": 2,
  "pm_start_pct_no_dca": 5.0,
  "pm_start_pct_with_dca": 2.5,
  "trailing_gap_pct": 0.6,
  "account_mode": "auto",
  "small_account_threshold": 2500,
  "small_account_settings": {
    "start_allocation_pct": 10.0,
    "dca_multiplier": 1.0,
    "dca_levels": [-7.5, -15.0, -25.0],
    "max_dca_buys_per_24h": 1,
    "pm_start_pct_no_dca": 8.0,
    "pm_start_pct_with_dca": 5.0,
    "trailing_gap_pct": 1.5,
    "trade_start_level": 4,
    "hard_stop_enabled": true,
    "hard_stop_pct": -35.0,
    "max_positions": 3,
    "reserve_minimum_pct": 20.0,
    "require_neural_dca_confirmation": true,
    "profit_mode": "tiered",
    "tiered_profit_t1_pct": 7.0,
    "tiered_profit_t1_sell_pct": 33,
    "tiered_profit_t2_pct": 15.0,
    "tiered_profit_t2_sell_pct": 50
  }
}
```

---

## Risk Mitigation & Compatibility

All changes were implemented additively:
- New methods added, zero existing methods modified or deleted
- All new settings use `.get()` with safe defaults so missing keys never crash the bot
- `account_mode: "force_existing"` provides instant rollback to pre-project behavior
- Error handling wraps all new methods; failure falls through to standard settings
- No new pip dependencies — all new imports are Python standard library

---

## Documented Future Improvements (Not Yet Implemented)

1. **Structured logging** — Replace `print()` statements with Python `logging` module + rotating file handlers
2. **GUI settings panel** — Allow editing `gui_settings.json` values from inside the hub
3. **Backtesting framework** — Replay historical price data against current strategy logic
4. **Correlation-aware position limits** — Skip new entries when existing positions are highly correlated
5. **Alert system** — Configurable notifications for hard stop triggers, tier exits, daily P&L summaries
6. **Multi-exchange support** — Abstract the Robinhood API behind an exchange interface
7. **Mobile companion app** — Read-only monitoring via React Native or Flutter
8. **Training ETA timer** — Display per-coin estimated completion time in the trainer GUI panel
9. **Manual buy cost basis refresh** — Trigger cost basis recalculation immediately after a successful manual buy

---

*End of Project Summary v1.3 — April 5, 2026*
