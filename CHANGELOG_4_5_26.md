# CHANGELOG — April 5, 2026 (v1.01)

## Summary

Three changes to `pt_trader.py` and one to `pt_hub.py`. No changes to `pt_thinker.py`, `pt_trainer.py`, or `requirements.txt`. All changes are additive — zero deleted methods, zero modified method signatures.

---

## pt_trader.py (2632 → 2987 lines)

### New Imports
- `from decimal import Decimal, ROUND_HALF_UP` — Python standard library
- `import csv` — Python standard library
- `from typing import ... List` — added to existing typing import

### New Constant
- `FORM_8949_CSV_PATH` — default output path for tax export CSV

### Changed: `get_orders()` — Paginated Order Fetching
- **Before:** Single API call, returned only first page of results
- **After:** Follows Robinhood's `next` pagination links up to 25 pages per coin
- **Why:** Prevents cost basis corruption when many orders accumulate for a coin
- **Signature change:** Added optional `max_pages: int = 25` parameter (backward compatible)

### New Method: `_extract_amounts_and_fees_from_order()`
- Returns `(filled_qty, avg_price, notional_usd, fees_usd)` using Decimal math
- Prefers Robinhood's order-level filled fields, falls back to execution sums
- Extracts fees from both execution-level and order-level fields

### Changed: `place_buy_order()` — Uses Decimal Extraction
- **Before:** Called `_extract_fill_from_order()` (float math, no fees)
- **After:** Calls `_extract_amounts_and_fees_from_order()` (Decimal math, includes fees)

### Changed: `place_sell_order()` — Uses Decimal Extraction
- **Before:** Inline float-math extraction with local `_fee_to_float()` function
- **After:** Calls `_extract_amounts_and_fees_from_order()` (Decimal math)
- Removed inline `_fee_to_float()` definition (now inside the shared method)

### Changed: `_reconcile_pending_orders()` — Uses Decimal Extraction
- **Before:** Called `_extract_fill_from_order()`, passed `fees_usd=None`
- **After:** Calls `_extract_amounts_and_fees_from_order()`, passes actual fees

### New Method: `export_8949_csv()`
- Reads `trade_history.jsonl`, produces Form 8949-compatible CSV
- Decimal math throughout for cent-accurate calculations
- Tracks buy accumulation per coin, pro-rata cost allocation on partial sells
- Short-term vs long-term holding period detection
- Year filter parameter, totals row at bottom
- Returns output file path or None on error

### Preserved: `_extract_fill_from_order()`
- **Not modified** — remains as fallback for any code paths that don't need fee/notional data

---

## pt_hub.py (5964 → 6231 lines)

### New GUI Panel: "Tax Export (Form 8949)"
- Located in Controls / Health tab, below Manual Sell panel
- Contains: Tax Year entry field, "Export 8949 CSV" button, status label
- Defaults to current year

### New Method: `_on_tax_export_click()`
- Validates year input (2020–2099)
- Disables button during export, spawns background thread

### New Method: `_do_tax_export()`
- Background thread: reads trade_history.jsonl, builds 8949 CSV
- Uses Decimal math for accurate cost basis and gain/loss calculations
- Tracks buy accumulation per coin with FIFO-style acquisition dates
- Writes to `hub_data/form_8949_trades_YYYY.csv`
- Opens containing folder on completion (Windows/Mac/Linux)
- Updates status label on completion or error

---

## Files NOT Changed
- `pt_thinker.py` — no changes
- `pt_trainer.py` — no changes
- `requirements.txt` — no changes (csv and decimal are Python standard library)
