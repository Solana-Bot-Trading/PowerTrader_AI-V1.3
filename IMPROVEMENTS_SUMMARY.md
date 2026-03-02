# PowerTrader AI V1.00 - Fork Improvements Summary

**Forked from:** [garagesteve1155/PowerTrader_AI](https://github.com/garagesteve1155/PowerTrader_AI)  
**Fork Maintainer:** Jim  
**Version:** 1.00 (as of March 1, 2026)  
**Primary Focus:** Small account optimization and enhanced risk management

---

## Overview

This fork transforms garagesteve's large-account focused PowerTrader AI into a comprehensive trading system optimized for accounts of all sizes, with particular emphasis on small account (<$2,500) profitability and capital preservation. All improvements maintain 100% backward compatibility with the original system.

---

## Major Feature Additions

### 1. **Three-Tier Account Mode System** *(pt_trader.py)*

**Original Behavior:**
- Single configuration optimized for large accounts ($10,000+)
- No account size detection or adaptive settings
- Fixed 0.005% position sizing (unsuitable for small accounts)

**Improvements:**
```python
account_mode options:
  - "auto": Automatic detection based on account value
  - "small": Force small account mode regardless of size
  - "force_existing": 100% original behavior (backward compatible)
```

**New Method:** `_apply_account_tier_settings()`
- Detects account size on startup
- Applies appropriate settings based on `small_account_threshold: 2500`
- Graceful fallback to standard settings on error

---

### 2. **Small Account Optimization Suite** *(pt_trader.py)*

Comprehensive parameter overrides specifically designed for accounts under $2,500:

| Parameter | Original | Small Account | Impact |
|-----------|----------|---------------|---------|
| **Position Sizing** | 0.005% ($0.50 on $250) | 10.0% ($25 on $250) | 5,000% increase in capital deployment |
| **DCA Strategy** | Exponential (2.0x multiplier) | Linear (1.0x multiplier) | Prevents account-destroying position growth |
| **DCA Levels** | 7 levels (-2.5% to -50%) | 3 levels (-7.5%, -15%, -25%) | Wider spacing, fewer aggressive entries |
| **DCA Frequency** | 2 per 24 hours | 1 per 24 hours | Prevents panic averaging |
| **Profit Targets** | +2.5% / +5.0% | +5.0% / +8.0% | Higher profit-to-loss ratio |
| **Trailing Gap** | 0.5% | 1.5% | Reduces noise exits, captures larger moves |
| **Position Limits** | Unlimited | Maximum 3 concurrent | Prevents correlation overload |
| **Reserve Cash** | 0% | 20% minimum | Ensures liquidity for opportunities |
| **Hard Stop Loss** | None | -35% with neural override | Capital preservation floor |
| **Neural DCA Confirmation** | Not required | Required | Quality-over-quantity DCA entries |

---

### 3. **Hard Stop Loss System** *(pt_trader.py)*

**Original Behavior:**
- No automatic loss protection
- Positions could drawdown to -50% or more
- Required manual intervention to exit losing trades

**New Feature:** `_check_hard_stop_loss()`
- Automatic market sell at -35% loss
- **Intelligent Override:** One-time neural L7 signal override allows recovery attempt before forced exit
- Clears all DCA state, trailing stop state, and override flags on trigger
- Prevents catastrophic losses on small accounts

**Configuration:**
```json
"hard_stop_enabled": true,
"hard_stop_pct": -35.0
```

---

### 4. **Tiered Profit Taking System** *(pt_trader.py)*

**Original Behavior:**
- Single trailing stop exit
- All-or-nothing position closure
- No partial profit securing

**New Three-Tier Exit Strategy:**
```
Tier 1: +7.0% gain → Sell 33% of position (secure profit)
Tier 2: +15.0% gain → Sell 50% of remainder (lock in bigger gains)
Tier 3: Trail remainder until stopped out (capture potential moonshots)
```

**Configuration:**
```json
"profit_mode": "tiered",
"tiered_profit_t1_pct": 7.0,
"tiered_profit_t1_sell_pct": 33,
"tiered_profit_t2_pct": 15.0,
"tiered_profit_t2_sell_pct": 50,
"trailing_gap_pct": 0.6
```

**Benefits:**
- Reduces risk of giving back all gains on reversals
- Captures larger moves while securing partial profits
- Optimizes risk/reward for small account compounding

---

### 5. **Reserve Capital Management** *(pt_trader.py)*

**Original Behavior:**
- No minimum cash reserve requirement
- Bot could deploy 100% of capital
- Left no buffer for DCA opportunities or volatility

**New Method:** `_check_position_limits()`
- Enforces `reserve_minimum_pct` before any buy or DCA order
- Formula: `(buying_power - order_cost) >= (total_account_value × reserve_minimum_pct)`
- Default: 20% reserve on small accounts ($50 kept liquid on $250 account)
- Prevents over-deployment and maintains dry powder

---

### 6. **Enhanced GUI Metrics Dashboard** *(pt_hub.py)*

**Original Display:**
- Total Account Value
- Holdings Value
- Buying Power
- % In Trade
- DCA Levels
- Total Realized P&L

**Four New Metrics Added:**

**1. Win Rate %**
```
Win Rate: 68.4% (13W / 6L of 19 closed)
```
- Calculated from `trade_history.jsonl`
- Shows percentage of profitable trades
- Provides transparency on strategy effectiveness

**2. Average Win / Average Loss**
```
Avg Win / Avg Loss: $4.23 / -$2.87
```
- Separate averages for winning and losing trades
- Critical metric for evaluating risk/reward ratio
- Helps identify if current settings are optimal

**3. Best / Worst Performing Coin**
```
Best / Worst Coin: BTC ($18.42) / ETH (-$4.12)
```
- Groups trades by symbol, sums realized P&L
- Identifies which assets work best with current strategy
- Helps with coin selection decisions

**4. Hard Stops Triggered Count**
```
Hard Stops Triggered: 2
```
- Counts trades tagged as "HARD_STOP" in history
- Monitors frequency of protective exits
- Early warning if market conditions or settings need adjustment

**Implementation:**
- All computed in existing `_refresh_pnl()` method
- Uses existing `trade_history.jsonl` and `pnl_ledger.json` files
- No new file dependencies or API calls required

---

### 7. **Corrected Account Value Calculation** *(pt_trader.py)*

**Original Behavior:**
- `get_account_value()` returned only buying power (available cash)
- Ignored value of currently held positions
- Resulted in incorrect account size detection and GUI display

**Fix:**
```python
def get_account_value(self) -> float:
    buying_power = self.get_buying_power()
    held_cost = self.get_cost_of_held_positions()
    return buying_power + held_cost
```

**Impact:**
- True account value displayed in GUI (e.g., $248.09 instead of $29.46)
- Accurate tier detection even when capital is deployed
- Correct reserve calculations in position limit checks

---

### 8. **Manual Buy Panel** *(pt_hub.py)*

**Original Behavior:**
- No way to place a one-off buy from the Hub UI
- Purchasing a new coin required manually using Robinhood before adding it to settings
- New coins had to be added to `gui_settings.json` by hand

**New Feature:** Manual Buy panel in the Controls / Health tab

**GUI Elements:**
```
[ Coin: _______  ] [ Amount $: ________ ] [ Buy Now ]
[ ] Auto-train after buy      Status: Ready
```

**How It Works:**

A dedicated `_RobinhoodDirectClient` class was added to `pt_hub.py`. This is a lightweight, self-contained Robinhood crypto API client that reads credentials from the same `r_key.txt` / `r_secret.txt` files used by `pt_trader.py`, allowing the Hub to place market buys independently — without requiring the trader subprocess to be running.

**Workflow on "Buy Now" click:**
1. Validates coin symbol (non-empty, uppercased automatically)
2. Validates dollar amount (numeric, greater than $0, strips `$` and `,` automatically)
3. Disables the Buy Now button and updates the status label to prevent duplicate orders
4. Spawns a background daemon thread so the UI stays responsive during the API call
5. Places a market buy order via the Robinhood crypto API
6. On success:
   - Adds the coin to `gui_settings.json` if not already present (atomic write via `.tmp` → `os.replace`)
   - Creates the coin's neural subfolder (e.g., `DOGE\`) if it does not exist
   - Copies `pt_trainer.py` into the new subfolder so the coin is ready to train
   - Refreshes the Hub's coin list and settings in-memory
   - If **Auto-train after buy** is checked, automatically triggers training for the new coin
7. Re-enables the Buy Now button and updates status with success or error message

**Input Validation:**
- Empty coin symbol → `"Error: Enter a coin symbol (e.g. DOGE)."`
- Non-numeric amount → `"Error: Amount must be a number (e.g. 25.00)."`
- Amount ≤ $0 → `"Error: Amount must be greater than $0."`
- Missing credentials → descriptive error directing user to API Setup Wizard
- API order failure → error message from Robinhood response displayed in status label

**Key Design Decisions:**
- `_RobinhoodDirectClient` is entirely self-contained in `pt_hub.py` — no modifications to `pt_trader.py` required
- Uses the same authentication and request-signing logic as `pt_trader.py` for consistency
- All UI updates are posted back to the main thread via `self.after()` — thread-safe
- Atomic settings file write prevents corruption if the process is interrupted mid-save
- Non-fatal: neural folder creation failure logs a warning but does not abort the buy

**Dependencies:**
- `requests` — HTTP calls to Robinhood API (already required by `pt_trader.py`)
- `pynacl` — request signing (already required by `pt_trader.py`)
- Both packages are in `requirements.txt` and installed during standard setup

---

## Critical Bug Fixes

### Bug #1: Unicode Emoji Crash (Windows)

**Problem:**
- Added emoji characters (💰🎯🛑) to console output
- Windows Command Prompt (cp1252 encoding) cannot render Unicode emojis
- Bot crashed immediately on startup

**Fix:**
- Replaced all emojis with ASCII bracket tags: `[SMALL ACCOUNT MODE]`, `[HARD STOP]`, `[ALLOCATION]`
- Ensures cross-platform compatibility

---

### Bug #2: NameError - `recent_dca` Undefined

**Problem:**
- During DCA logic reorganization, line `recent_dca = self._dca_window_count(symbol)` was accidentally removed
- Referenced before definition → instant crash on any DCA attempt

**Fix:**
- Re-added calculation in correct position before first reference
- Verified all DCA paths include proper variable initialization

---

### Bug #3: Instance Variable Not Set in Non-Small Modes

**Problem:**
- `_apply_account_tier_settings()` returned early in "force_existing" and "standard" modes
- Never set `self.start_allocation_pct` in those code paths
- Bot used hardcoded 0.005% instead of user's configured value

**Fix:**
- Set all instance variables in every code path, including early returns
- Ensures consistent behavior across all account modes

---

## Configuration File Enhancements

### Extended `gui_settings.json` Structure

**New Top-Level Settings:**
```json
{
  "account_mode": "auto",
  "small_account_threshold": 2500,
  "small_account_settings": { ... }
}
```

**New Small Account Settings Block:**
```json
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
```

---

## Code Quality Improvements

### Safe Configuration Loading

**Original:**
```python
setting = config['key']  # KeyError if missing
```

**Improved:**
```python
setting = config.get('key', safe_default_value)  # Never crashes
```

**Applied to:**
- All new settings in `_apply_account_tier_settings()`
- All tier-specific parameter loads
- All GUI metric calculations

---

### Error Handling

**Added comprehensive try-except blocks:**
- Around all new methods (`_apply_account_tier_settings`, `_check_hard_stop_loss`, `_check_position_limits`)
- Around GUI metric calculations in `pt_hub.py`
- Around Manual Buy background thread execution
- Graceful degradation - missing features don't crash the bot
- Falls back to safe defaults on any exception

---

## Architecture Principles Maintained

### Non-Breaking Changes
- **Zero deleted methods** - All original functions preserved
- **Zero modified signatures** - All original method parameters unchanged
- **Additive-only approach** - New features added alongside existing code
- **Backward compatibility** - `account_mode: "force_existing"` provides instant rollback

### Untouched Components
- `pt_thinker.py` - Neural network runner (0 modifications)
- `pt_trainer.py` - Neural network trainer (0 modifications)
- Robinhood API integration (0 modifications)
- All original trading logic preserved for large accounts

---

## Live Deployment Results

**Account:** $510.00 (as of February 27, 2026)  
**Status:** Actively trading, profitable, stable  
**Mode:** Small account optimization (auto-detected)  
**Verified Behaviors:**
- ✅ Correct $25 initial position sizing (10% of $250)
- ✅ Linear DCA buys (equal-size, not exponential)
- ✅ Neural confirmation required before DCA
- ✅ Hard stop triggers at -35% with L7 override working
- ✅ Tiered profit exits executing (33% at +7%, 50% at +15%, trail rest)
- ✅ Reserve minimum enforced (20% stays liquid)
- ✅ Maximum 3 concurrent positions enforced
- ✅ All new GUI metrics displaying correctly
- ✅ Manual Buy panel placing live orders successfully

---

## Testing & Validation

### Pre-Deployment Verification
1. **Dry-run testing** - Verified small account mode detection without live trades
2. **Windows compatibility** - Tested on Windows 10/11 with Command Prompt
3. **Configuration validation** - Tested all three account modes (auto/small/force_existing)
4. **Error handling** - Confirmed graceful degradation on missing config keys
5. **GUI rendering** - Verified all new metrics display without layout breaks

### Post-Deployment Monitoring
1. **Trade execution logs** - Confirmed correct position sizing and DCA behavior
2. **Hard stop testing** - Verified -35% auto-exit and neural override
3. **Tiered profit testing** - Confirmed staged exits at +7% and +15%
4. **Reserve enforcement** - Validated 20% minimum cash retention
5. **Account value tracking** - Confirmed accurate total value calculation
6. **Manual Buy testing** - Confirmed live order placement, settings update, and folder creation

---

## Known Limitations & Future Enhancements

### Not Yet Implemented
The following improvements were identified but not yet built (listed in suggested priority order):

1. **Structured Logging System**
   - Replace `print()` with Python `logging` module
   - Add rotating file handlers for historical logs
   - Enable searchable timestamped records for debugging

2. **GUI Settings Panel**
   - In-app configuration editor (no JSON file editing required)
   - Real-time validation of setting changes
   - One-click presets for different risk profiles

3. **Backtesting Framework**
   - Replay historical price data against current strategy
   - Validate parameter choices before live deployment
   - Generate performance metrics across different market conditions

4. **Correlation-Aware Position Limits**
   - Skip new entries when existing positions are highly correlated
   - Example: Don't open both BTC and ETH during simultaneous drawdowns
   - Reduces portfolio concentration risk

5. **Trade Database Export**
   - CSV or SQLite export of all trades
   - Persistent per-trade log with buy/sell prices, hold time, DCA count, P&L
   - Enables offline analysis and tax reporting

6. **Alert System**
   - Configurable notifications (email, desktop popup, webhook)
   - Triggers: hard stops, tier exits, daily P&L summaries
   - Optional integration with Discord/Telegram

7. **Multi-Exchange Support**
   - Abstract Robinhood API behind exchange interface
   - Add adapters for Coinbase, Kraken, Binance.US
   - Enable cross-exchange arbitrage opportunities

8. **Mobile Companion App**
   - Read-only monitoring via React Native or Flutter
   - Shows positions, P&L, allows manual overrides
   - Push notifications for critical events

---

## Summary of Improvements

### Quantitative Gains
- **5,000% increase** in capital deployment efficiency for small accounts
- **-35% loss protection** vs unlimited downside in original
- **3-tier profit system** vs single all-or-nothing exit
- **4 new performance metrics** for strategy evaluation
- **3 critical bugs** fixed (Unicode crash, NameError, instance variable)
- **1 Manual Buy panel** for on-demand order placement from the Hub UI
- **100% backward compatibility** maintained

### Qualitative Gains
- Suitable for accounts from $250 to $100,000+
- Significantly improved risk management
- Enhanced transparency with detailed metrics
- More predictable P&L outcomes
- Better capital preservation on drawdowns
- Optimized for small account compounding
- Ability to manually enter positions and add new coins without leaving the Hub

---

## Installation & Usage

### For Original PowerTrader AI Users
Simply replace your existing `pt_trader.py` and `pt_hub.py` files with the fork versions. Your existing `gui_settings.json` will continue to work. To enable small account optimizations, add:

```json
"account_mode": "auto",
"small_account_threshold": 2500
```

To revert to 100% original behavior:
```json
"account_mode": "force_existing"
```

### For New Users
Follow garagesteve's original installation guide, but use this fork's files instead. All setup steps remain identical.

---

## Credits & License

**Original Author:** garagesteve1155  
**Fork Maintainer:** Jim  
**License:** Apache 2.0 (same as original)  
**Repository:** [garagesteve1155/PowerTrader_AI](https://github.com/garagesteve1155/PowerTrader_AI)

This fork respects and maintains all original copyright notices and licenses. All improvements are contributed back to the community under the same Apache 2.0 license.

---

## Disclaimer

This software places real trades automatically. You are responsible for everything it does to your money and your account. Keep your API keys private. This is not financial advice. The maintainers are not responsible for any losses incurred. You are fully responsible for doing your own due diligence to understand this trading system and use it properly. You are fully responsible for all of your money and any gains or losses.

**Use at your own risk.**

---

*Last Updated: March 1, 2026*  
*Fork Version: 1.00*  
*Document Version: 1.1*
