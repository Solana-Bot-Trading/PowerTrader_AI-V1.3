import base64
import csv
import datetime
import json
import uuid
import time
import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional
import requests
from nacl.signing import SigningKey
import os
import colorama
from colorama import Fore, Style
import traceback
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

# -----------------------------
# GUI HUB OUTPUTS
# -----------------------------
HUB_DATA_DIR = os.environ.get("POWERTRADER_HUB_DIR", os.path.join(os.path.dirname(__file__), "hub_data"))
os.makedirs(HUB_DATA_DIR, exist_ok=True)

TRADER_STATUS_PATH = os.path.join(HUB_DATA_DIR, "trader_status.json")
TRADE_HISTORY_PATH = os.path.join(HUB_DATA_DIR, "trade_history.jsonl")
PNL_LEDGER_PATH = os.path.join(HUB_DATA_DIR, "pnl_ledger.json")
ACCOUNT_VALUE_HISTORY_PATH = os.path.join(HUB_DATA_DIR, "account_value_history.jsonl")
FORM_8949_CSV_PATH = os.path.join(HUB_DATA_DIR, "form_8949_trades.csv")



# Initialize colorama
colorama.init(autoreset=True)

# -----------------------------
# GUI SETTINGS (coins list + main_neural_dir)
# -----------------------------
_GUI_SETTINGS_PATH = os.environ.get("POWERTRADER_GUI_SETTINGS") or os.path.join(
	os.path.dirname(os.path.abspath(__file__)),
	"gui_settings.json"
)

_gui_settings_cache = {
	"mtime": None,
	"coins": ['BTC', 'ETH', 'XRP', 'BNB', 'DOGE'],  # fallback defaults
	"main_neural_dir": None,
	"trade_start_level": 3,
	"start_allocation_pct": 0.005,
	"dca_multiplier": 2.0,
	"dca_levels": [-2.5, -5.0, -10.0, -20.0, -30.0, -40.0, -50.0],
	"max_dca_buys_per_24h": 2,

	# Trailing PM settings (defaults match previous hardcoded behavior)
	"pm_start_pct_no_dca": 5.0,
	"pm_start_pct_with_dca": 2.5,
	"trailing_gap_pct": 0.5,
	
	# Account mode settings (new - backward compatible)
	"account_mode": "auto",
	"small_account_threshold": 2500,
	"small_account_settings": {},
}







def _load_gui_settings() -> dict:
	"""
	Reads gui_settings.json and returns a dict with:
	- coins: uppercased list
	- main_neural_dir: string (may be None)
	Caches by mtime so it is cheap to call frequently.
	"""
	try:
		if not os.path.isfile(_GUI_SETTINGS_PATH):
			return dict(_gui_settings_cache)

		mtime = os.path.getmtime(_GUI_SETTINGS_PATH)
		if _gui_settings_cache["mtime"] == mtime:
			return dict(_gui_settings_cache)

		with open(_GUI_SETTINGS_PATH, "r", encoding="utf-8") as f:
			data = json.load(f) or {}

		coins = data.get("coins", None)
		if not isinstance(coins, list) or not coins:
			coins = list(_gui_settings_cache["coins"])
		coins = [str(c).strip().upper() for c in coins if str(c).strip()]
		if not coins:
			coins = list(_gui_settings_cache["coins"])

		main_neural_dir = data.get("main_neural_dir", None)
		if isinstance(main_neural_dir, str):
			main_neural_dir = main_neural_dir.strip() or None
		else:
			main_neural_dir = None

		trade_start_level = data.get("trade_start_level", _gui_settings_cache.get("trade_start_level", 3))
		try:
			trade_start_level = int(float(trade_start_level))
		except Exception:
			trade_start_level = int(_gui_settings_cache.get("trade_start_level", 3))
		trade_start_level = max(1, min(trade_start_level, 9))

		start_allocation_pct = data.get("start_allocation_pct", _gui_settings_cache.get("start_allocation_pct", 0.005))
		try:
			start_allocation_pct = float(str(start_allocation_pct).replace("%", "").strip())
		except Exception:
			start_allocation_pct = float(_gui_settings_cache.get("start_allocation_pct", 0.005))
		if start_allocation_pct < 0.0:
			start_allocation_pct = 0.0

		dca_multiplier = data.get("dca_multiplier", _gui_settings_cache.get("dca_multiplier", 2.0))
		try:
			dca_multiplier = float(str(dca_multiplier).strip())
		except Exception:
			dca_multiplier = float(_gui_settings_cache.get("dca_multiplier", 2.0))
		if dca_multiplier < 0.0:
			dca_multiplier = 0.0

		dca_levels = data.get("dca_levels", _gui_settings_cache.get("dca_levels", [-2.5, -5.0, -10.0, -20.0, -30.0, -40.0, -50.0]))
		if not isinstance(dca_levels, list) or not dca_levels:
			dca_levels = list(_gui_settings_cache.get("dca_levels", [-2.5, -5.0, -10.0, -20.0, -30.0, -40.0, -50.0]))
		parsed = []
		for v in dca_levels:
			try:
				parsed.append(float(v))
			except Exception:
				pass
		if parsed:
			dca_levels = parsed
		else:
			dca_levels = list(_gui_settings_cache.get("dca_levels", [-2.5, -5.0, -10.0, -20.0, -30.0, -40.0, -50.0]))

		max_dca_buys_per_24h = data.get("max_dca_buys_per_24h", _gui_settings_cache.get("max_dca_buys_per_24h", 2))
		try:
			max_dca_buys_per_24h = int(float(max_dca_buys_per_24h))
		except Exception:
			max_dca_buys_per_24h = int(_gui_settings_cache.get("max_dca_buys_per_24h", 2))
		if max_dca_buys_per_24h < 0:
			max_dca_buys_per_24h = 0


		# --- Trailing PM settings ---
		pm_start_pct_no_dca = data.get("pm_start_pct_no_dca", _gui_settings_cache.get("pm_start_pct_no_dca", 5.0))
		try:
			pm_start_pct_no_dca = float(str(pm_start_pct_no_dca).replace("%", "").strip())
		except Exception:
			pm_start_pct_no_dca = float(_gui_settings_cache.get("pm_start_pct_no_dca", 5.0))
		if pm_start_pct_no_dca < 0.0:
			pm_start_pct_no_dca = 0.0

		pm_start_pct_with_dca = data.get("pm_start_pct_with_dca", _gui_settings_cache.get("pm_start_pct_with_dca", 2.5))
		try:
			pm_start_pct_with_dca = float(str(pm_start_pct_with_dca).replace("%", "").strip())
		except Exception:
			pm_start_pct_with_dca = float(_gui_settings_cache.get("pm_start_pct_with_dca", 2.5))
		if pm_start_pct_with_dca < 0.0:
			pm_start_pct_with_dca = 0.0

		trailing_gap_pct = data.get("trailing_gap_pct", _gui_settings_cache.get("trailing_gap_pct", 0.5))
		try:
			trailing_gap_pct = float(str(trailing_gap_pct).replace("%", "").strip())
		except Exception:
			trailing_gap_pct = float(_gui_settings_cache.get("trailing_gap_pct", 0.5))
		if trailing_gap_pct < 0.0:
			trailing_gap_pct = 0.0


		_gui_settings_cache["mtime"] = mtime
		_gui_settings_cache["coins"] = coins
		_gui_settings_cache["main_neural_dir"] = main_neural_dir
		_gui_settings_cache["trade_start_level"] = trade_start_level
		_gui_settings_cache["start_allocation_pct"] = start_allocation_pct
		_gui_settings_cache["dca_multiplier"] = dca_multiplier
		_gui_settings_cache["dca_levels"] = dca_levels
		_gui_settings_cache["max_dca_buys_per_24h"] = max_dca_buys_per_24h

		_gui_settings_cache["pm_start_pct_no_dca"] = pm_start_pct_no_dca
		_gui_settings_cache["pm_start_pct_with_dca"] = pm_start_pct_with_dca
		_gui_settings_cache["trailing_gap_pct"] = trailing_gap_pct


		# --- Small account mode settings (new - backward compatible) ---
		account_mode = data.get("account_mode", "auto")
		small_threshold = float(data.get("small_account_threshold", 2500))
		small_settings = data.get("small_account_settings", {})

		_gui_settings_cache["account_mode"] = account_mode
		_gui_settings_cache["small_account_threshold"] = small_threshold
		_gui_settings_cache["small_account_settings"] = small_settings


		return {
			"mtime": mtime,
			"coins": list(coins),
			"main_neural_dir": main_neural_dir,
			"trade_start_level": trade_start_level,
			"start_allocation_pct": start_allocation_pct,
			"dca_multiplier": dca_multiplier,
			"dca_levels": list(dca_levels),
			"max_dca_buys_per_24h": max_dca_buys_per_24h,

			"pm_start_pct_no_dca": pm_start_pct_no_dca,
			"pm_start_pct_with_dca": pm_start_pct_with_dca,
			"trailing_gap_pct": trailing_gap_pct,
			
			# Small account mode fields
			"account_mode": account_mode,
			"small_account_threshold": small_threshold,
			"small_account_settings": small_settings,
		}




	except Exception:
		return dict(_gui_settings_cache)


def _build_base_paths(main_dir_in: str, coins_in: list) -> dict:
	"""
	Safety rule:
	- BTC uses main_dir directly
	- other coins use <main_dir>/<SYM> ONLY if that folder exists
	  (no fallback to BTC folder — avoids corrupting BTC data)
	"""
	out = {"BTC": main_dir_in}
	try:
		for sym in coins_in:
			sym = str(sym).strip().upper()
			if not sym:
				continue
			if sym == "BTC":
				out["BTC"] = main_dir_in
				continue
			sub = os.path.join(main_dir_in, sym)
			if os.path.isdir(sub):
				out[sym] = sub
	except Exception:
		pass
	return out


# Live globals (will be refreshed inside manage_trades())
crypto_symbols = ['BTC', 'ETH', 'XRP', 'BNB', 'DOGE']

# Default main_dir behavior if settings are missing
main_dir = os.getcwd()
base_paths = {"BTC": main_dir}
TRADE_START_LEVEL = 3
START_ALLOC_PCT = 0.005
DCA_MULTIPLIER = 2.0
DCA_LEVELS = [-2.5, -5.0, -10.0, -20.0, -30.0, -40.0, -50.0]
MAX_DCA_BUYS_PER_24H = 2

# Trailing PM hot-reload globals (defaults match previous hardcoded behavior)
TRAILING_GAP_PCT = 0.5
PM_START_PCT_NO_DCA = 5.0
PM_START_PCT_WITH_DCA = 2.5



_last_settings_mtime = None




def _refresh_paths_and_symbols():
	"""
	Hot-reload GUI settings while trader is running.
	Updates globals: crypto_symbols, main_dir, base_paths,
	                TRADE_START_LEVEL, START_ALLOC_PCT, DCA_MULTIPLIER, DCA_LEVELS, MAX_DCA_BUYS_PER_24H,
	                TRAILING_GAP_PCT, PM_START_PCT_NO_DCA, PM_START_PCT_WITH_DCA
	"""
	global crypto_symbols, main_dir, base_paths
	global TRADE_START_LEVEL, START_ALLOC_PCT, DCA_MULTIPLIER, DCA_LEVELS, MAX_DCA_BUYS_PER_24H
	global TRAILING_GAP_PCT, PM_START_PCT_NO_DCA, PM_START_PCT_WITH_DCA
	global _last_settings_mtime


	s = _load_gui_settings()
	mtime = s.get("mtime", None)

	# If settings file doesn't exist, keep current defaults
	if mtime is None:
		return

	if _last_settings_mtime == mtime:
		return

	_last_settings_mtime = mtime

	coins = s.get("coins") or list(crypto_symbols)
	mndir = s.get("main_neural_dir") or main_dir
	TRADE_START_LEVEL = max(1, min(int(s.get("trade_start_level", TRADE_START_LEVEL) or TRADE_START_LEVEL), 9))
	START_ALLOC_PCT = float(s.get("start_allocation_pct", START_ALLOC_PCT) or START_ALLOC_PCT)
	if START_ALLOC_PCT < 0.0:
		START_ALLOC_PCT = 0.0

	DCA_MULTIPLIER = float(s.get("dca_multiplier", DCA_MULTIPLIER) or DCA_MULTIPLIER)
	if DCA_MULTIPLIER < 0.0:
		DCA_MULTIPLIER = 0.0

	DCA_LEVELS = list(s.get("dca_levels", DCA_LEVELS) or DCA_LEVELS)

	try:
		MAX_DCA_BUYS_PER_24H = int(float(s.get("max_dca_buys_per_24h", MAX_DCA_BUYS_PER_24H) or MAX_DCA_BUYS_PER_24H))
	except Exception:
		MAX_DCA_BUYS_PER_24H = int(MAX_DCA_BUYS_PER_24H)
	if MAX_DCA_BUYS_PER_24H < 0:
		MAX_DCA_BUYS_PER_24H = 0


	# Trailing PM hot-reload values
	TRAILING_GAP_PCT = float(s.get("trailing_gap_pct", TRAILING_GAP_PCT) or TRAILING_GAP_PCT)
	if TRAILING_GAP_PCT < 0.0:
		TRAILING_GAP_PCT = 0.0

	PM_START_PCT_NO_DCA = float(s.get("pm_start_pct_no_dca", PM_START_PCT_NO_DCA) or PM_START_PCT_NO_DCA)
	if PM_START_PCT_NO_DCA < 0.0:
		PM_START_PCT_NO_DCA = 0.0

	PM_START_PCT_WITH_DCA = float(s.get("pm_start_pct_with_dca", PM_START_PCT_WITH_DCA) or PM_START_PCT_WITH_DCA)
	if PM_START_PCT_WITH_DCA < 0.0:
		PM_START_PCT_WITH_DCA = 0.0


	# Keep it safe if folder isn't real on this machine
	if not os.path.isdir(mndir):
		mndir = os.getcwd()

	crypto_symbols = list(coins)
	main_dir = mndir
	base_paths = _build_base_paths(main_dir, crypto_symbols)






#API STUFF
API_KEY = ""
BASE64_PRIVATE_KEY = ""

try:
    with open('r_key.txt', 'r', encoding='utf-8') as f:
        API_KEY = (f.read() or "").strip()
    with open('r_secret.txt', 'r', encoding='utf-8') as f:
        BASE64_PRIVATE_KEY = (f.read() or "").strip()
except Exception:
    API_KEY = ""
    BASE64_PRIVATE_KEY = ""

if not API_KEY or not BASE64_PRIVATE_KEY:
    print(
        "\n[PowerTrader] Robinhood API credentials not found.\n"
        "Open the GUI and go to Settings → Robinhood API → Setup / Update.\n"
        "That wizard will generate your keypair, tell you where to paste the public key on Robinhood,\n"
        "and will save r_key.txt + r_secret.txt so this trader can authenticate.\n"
    )
    raise SystemExit(1)

class CryptoAPITrading:
    def __init__(self):
        # keep a copy of the folder map (same idea as trader.py)
        self.path_map = dict(base_paths)

        self.api_key = API_KEY
        private_key_seed = base64.b64decode(BASE64_PRIVATE_KEY)
        self.private_key = SigningKey(private_key_seed)
        self.base_url = "https://trading.robinhood.com"

        self.dca_levels_triggered = {}  # Track DCA levels for each crypto
        self.dca_levels = list(DCA_LEVELS)  # Hard DCA triggers (percent PnL)


        # --- Trailing profit margin (per-coin state) ---
        # Each coin keeps its own trailing PM line, peak, and "was above line" flag.
        self.trailing_pm = {}  # { "BTC": {"active": bool, "line": float, "peak": float, "was_above": bool}, . }
        self.trailing_gap_pct = float(TRAILING_GAP_PCT)  # % trail gap behind peak
        self.pm_start_pct_no_dca = float(PM_START_PCT_NO_DCA)
        self.pm_start_pct_with_dca = float(PM_START_PCT_WITH_DCA)

        # Track trailing-related settings so we can reset trailing state if they change
        self._last_trailing_settings_sig = (
            float(self.trailing_gap_pct),
            float(self.pm_start_pct_no_dca),
            float(self.pm_start_pct_with_dca),
        )

        # --- Tiered profit taking (per-coin state) ---
        # { "BTC": {"orig_qty": float, 1: bool, 2: bool} }
        self.tiered_profits = {}

        # Tier settings — 0.0 pct = disabled (falls back to plain trailing stop)
        self.profit_tier1_pct      = 0.0
        self.profit_tier1_fraction = 0.33
        self.profit_tier2_pct      = 0.0
        self.profit_tier2_fraction = 0.50



        self.cost_basis = self.calculate_cost_basis()  # Initialize cost basis at startup
        self.initialize_dca_levels()  # Initialize DCA levels based on historical buy orders

        # GUI hub persistence
        self._pnl_ledger = self._load_pnl_ledger()
        self._reconcile_pending_orders()


        # Cache last known bid/ask per symbol so transient API misses don't zero out account value
        self._last_good_bid_ask = {}

        # Cache last *complete* account snapshot so transient holdings/price misses can't write a bogus low value
        self._last_good_account_snapshot = {
            "total_account_value": None,
            "buying_power": None,
            "holdings_sell_value": None,
            "holdings_buy_value": None,
            "percent_in_trade": None,
        }

        # --- DCA rate-limit (per trade, per coin, rolling 24h window) ---
        self.max_dca_buys_per_24h = int(MAX_DCA_BUYS_PER_24H)
        self.dca_window_seconds = 24 * 60 * 60

        self._dca_buy_ts = {}         # { "BTC": [ts, ts, ...] } (DCA buys only)
        self._dca_last_sell_ts = {}   # { "BTC": ts_of_last_sell }
        self._seed_dca_window_from_history()

        # Apply account tier-specific settings (small account optimizations)
        self._apply_account_tier_settings()





    def _apply_account_tier_settings(self):
        """
        Detect account size and apply appropriate settings overrides.
        Falls back to existing globals if account_mode is not 'small' or 'auto'.
        This method is backward compatible - if account_mode is missing or set to
        'force_existing', no changes are made.
        """
        try:
            settings = _load_gui_settings()
            account_mode = settings.get("account_mode", "auto")
            
            # If mode is 'force_existing', use existing behavior but load from settings
            if account_mode == "force_existing":
                print("Account mode: FORCE_EXISTING - Using current production settings")
                # Still load the settings values (don't use hardcoded defaults)
                self.start_allocation_pct = float(START_ALLOC_PCT)
                self.dca_multiplier = float(DCA_MULTIPLIER)
                return
            
            # Get account value to determine tier.
            # Uses get_account() (buying_power) + get_holdings() (holdings value) so the
            # total reflects actual portfolio value, not just uninvested cash.
            try:
                _acct = self.get_account()
                _bp = float(_acct.get("buying_power", 0.0) or 0.0)
                _holdings = self.get_holdings()
                _holdings_val = 0.0
                for _h in _holdings.get("results", []):
                    try:
                        _qty = float(_h.get("total_quantity", 0.0) or 0.0)
                        _cost = float(_h.get("cost_held_for_display", 0.0) or 0.0)
                        _holdings_val += _cost if _cost > 0 else 0.0
                    except Exception:
                        pass
                account_value = _bp + _holdings_val
                if account_value <= 0.0:
                    # Fallback: use buying_power alone if holdings parse failed
                    account_value = _bp
                if account_value <= 0.0:
                    raise ValueError("Account value is zero or negative")
            except Exception as _e:
                print(f"Warning: Could not get account value for tier detection ({_e}). Using standard settings.")
                return
            
            small_threshold = settings.get("small_account_threshold", 2500)
            
            # Determine if small account settings should apply
            should_use_small = (
                account_mode == "small" or 
                (account_mode == "auto" and account_value < small_threshold)
            )
            
            if not should_use_small:
                print(f"[STANDARD MODE] Account: ${account_value:,.2f} - Using standard settings")
                self.start_allocation_pct = float(START_ALLOC_PCT)
                self.dca_multiplier = float(DCA_MULTIPLIER)
                self.hard_stop_enabled = False
                self.hard_stop_pct = -35.0
                self.max_positions = 999
                self.reserve_minimum_pct = 0.0
                self.require_neural_dca_confirmation = False
                # Tiered profits: disabled in standard mode unless configured at top level
                self.profit_tier1_pct      = float(settings.get("profit_tier1_pct", 0.0))
                self.profit_tier1_fraction = float(settings.get("profit_tier1_fraction", 0.33))
                self.profit_tier2_pct      = float(settings.get("profit_tier2_pct", 0.0))
                self.profit_tier2_fraction = float(settings.get("profit_tier2_fraction", 0.50))
                self._small_account_active = False
                return
            
            # Apply small account overrides
            self._small_account_active = True
            print(f"[SMALL ACCOUNT MODE] Account: ${account_value:,.2f} - Using small account optimizations")
            
            small = settings.get("small_account_settings", {})
            
            if not small:
                print("  Warning: small_account_settings not configured. Using standard settings.")
                return
            
            # Override instance variables with small account settings
            if "start_allocation_pct" in small:
                self.start_allocation_pct = float(small["start_allocation_pct"])
            else:
                self.start_allocation_pct = float(START_ALLOC_PCT)
                
            if "dca_multiplier" in small:
                self.dca_multiplier = float(small["dca_multiplier"])
            else:
                self.dca_multiplier = float(DCA_MULTIPLIER)
                
            if "dca_levels" in small:
                self.dca_levels = list(small["dca_levels"])
            
            if "max_dca_buys_per_24h" in small:
                self.max_dca_buys_per_24h = int(small["max_dca_buys_per_24h"])
                
            if "pm_start_pct_no_dca" in small:
                self.pm_start_pct_no_dca = float(small["pm_start_pct_no_dca"])
                
            if "pm_start_pct_with_dca" in small:
                self.pm_start_pct_with_dca = float(small["pm_start_pct_with_dca"])
                
            if "trailing_gap_pct" in small:
                self.trailing_gap_pct = float(small["trailing_gap_pct"])
            
            # New small-account-only features
            self.hard_stop_enabled = small.get("hard_stop_enabled", False)
            self.hard_stop_pct = float(small.get("hard_stop_pct", -35.0))
            self.max_positions = int(small.get("max_positions", 999))
            self.reserve_minimum_pct = float(small.get("reserve_minimum_pct", 0.0))
            self.require_neural_dca_confirmation = small.get("require_neural_dca_confirmation", True)

            # Tiered profit taking (small account; 0.0 pct = disabled)
            self.profit_tier1_pct      = float(small.get("profit_tier1_pct", 7.0))
            self.profit_tier1_fraction = float(small.get("profit_tier1_fraction", 0.33))
            self.profit_tier2_pct      = float(small.get("profit_tier2_pct", 15.0))
            self.profit_tier2_fraction = float(small.get("profit_tier2_fraction", 0.50))

            # Update trailing settings signature for state reset detection
            self._last_trailing_settings_sig = (
                float(self.trailing_gap_pct),
                float(self.pm_start_pct_no_dca),
                float(self.pm_start_pct_with_dca),
            )

            print(f"  * Initial position: {self.start_allocation_pct:.2f}%")
            print(f"  * DCA multiplier: {self.dca_multiplier:.1f}x")
            print(f"  * DCA levels: {self.dca_levels}")
            print(f"  * Profit targets: {self.pm_start_pct_no_dca:.1f}% / {self.pm_start_pct_with_dca:.1f}%")
            print(f"  * Hard stop: {self.hard_stop_pct:.1f}% (enabled={self.hard_stop_enabled})")
            print(f"  * Max positions: {self.max_positions}")
            print(f"  * Reserve minimum: {self.reserve_minimum_pct:.1f}%")
            t1_pct = self.profit_tier1_pct
            t2_pct = self.profit_tier2_pct
            if t1_pct > 0.0:
                print(f"  * Tiered profits: T1=+{t1_pct:.1f}% (sell {self.profit_tier1_fraction*100:.0f}%)  "
                      f"T2=+{t2_pct:.1f}% (sell {self.profit_tier2_fraction*100:.0f}% of remainder)  Trail rest")
            else:
                print(f"  * Tiered profits: DISABLED (full trailing stop)")

        except Exception as e:
            print(f"Warning: Could not apply account tier settings: {e}")
            print("Continuing with standard settings...")
            self.hard_stop_enabled = False
            self.hard_stop_pct = -35.0
            self.max_positions = 999
            self.reserve_minimum_pct = 0.0
            self.require_neural_dca_confirmation = False
            self.start_allocation_pct = float(START_ALLOC_PCT)
            self.dca_multiplier = float(DCA_MULTIPLIER)
            self.profit_tier1_pct      = 0.0
            self.profit_tier1_fraction = 0.33
            self.profit_tier2_pct      = 0.0
            self.profit_tier2_fraction = 0.50
            self._small_account_active = False








    def _atomic_write_json(self, path: str, data: dict) -> None:
        try:
            tmp = f"{path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, path)
        except Exception:
            pass

    def _append_jsonl(self, path: str, obj: dict) -> None:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(obj) + "\n")
        except Exception:
            pass

    def _load_pnl_ledger(self) -> dict:
        try:
            if os.path.isfile(PNL_LEDGER_PATH):
                with open(PNL_LEDGER_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f) or {}
                if not isinstance(data, dict):
                    data = {}
                # Back-compat upgrades
                data.setdefault("total_realized_profit_usd", 0.0)
                data.setdefault("last_updated_ts", time.time())
                data.setdefault("open_positions", {})   # { "BTC": {"usd_cost": float, "qty": float} }
                data.setdefault("pending_orders", {})   # { "<order_id>": {...} }
                return data
        except Exception:
            pass
        return {
            "total_realized_profit_usd": 0.0,
            "last_updated_ts": time.time(),
            "open_positions": {},
            "pending_orders": {},
        }

    def _save_pnl_ledger(self) -> None:
        try:
            self._pnl_ledger["last_updated_ts"] = time.time()
            self._atomic_write_json(PNL_LEDGER_PATH, self._pnl_ledger)
        except Exception:
            pass

    def _trade_history_has_order_id(self, order_id: str) -> bool:
        try:
            if not order_id:
                return False
            if not os.path.isfile(TRADE_HISTORY_PATH):
                return False
            with open(TRADE_HISTORY_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = (line or "").strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if str(obj.get("order_id", "")).strip() == str(order_id).strip():
                        return True
        except Exception:
            return False
        return False

    def _get_buying_power(self) -> float:
        try:
            acct = self.get_account()
            if isinstance(acct, dict):
                return float(acct.get("buying_power", 0.0) or 0.0)
        except Exception:
            pass
        return 0.0

    def _get_order_by_id(self, symbol: str, order_id: str) -> Optional[dict]:
        try:
            orders = self.get_orders(symbol)
            results = orders.get("results", []) if isinstance(orders, dict) else []
            for o in results:
                try:
                    if o.get("id") == order_id:
                        return o
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def _extract_fill_from_order(self, order: dict) -> tuple:
        """Returns (filled_qty, avg_fill_price). avg_fill_price may be None."""
        try:
            execs = order.get("executions", []) or []
            total_qty = 0.0
            total_notional = 0.0
            for ex in execs:
                try:
                    q = float(ex.get("quantity", 0.0) or 0.0)
                    p = float(ex.get("effective_price", 0.0) or 0.0)
                    if q > 0.0 and p > 0.0:
                        total_qty += q
                        total_notional += (q * p)
                except Exception:
                    continue

            avg_price = (total_notional / total_qty) if (total_qty > 0.0 and total_notional > 0.0) else None

            # Fallbacks if executions are not populated yet
            if total_qty <= 0.0:
                for k in ("filled_asset_quantity", "filled_quantity", "asset_quantity", "quantity"):
                    if k in order:
                        try:
                            v = float(order.get(k) or 0.0)
                            if v > 0.0:
                                total_qty = v
                                break
                        except Exception:
                            continue

            if avg_price is None:
                for k in ("average_price", "avg_price", "price", "effective_price"):
                    if k in order:
                        try:
                            v = float(order.get(k) or 0.0)
                            if v > 0.0:
                                avg_price = v
                                break
                        except Exception:
                            continue

            return float(total_qty), (float(avg_price) if avg_price is not None else None)
        except Exception:
            return 0.0, None

    def _extract_amounts_and_fees_from_order(self, order: dict) -> tuple:
        """
        Returns (filled_qty, avg_price, notional_usd, fees_usd) using Decimal math
        for cent-accurate P&L tracking. Prefers order-level filled fields for USD
        notional (matches Robinhood's accounting) and falls back to execution sums
        only when those fields are missing.
        """
        try:
            def _fee_to_float(v: Any) -> float:
                try:
                    if v is None:
                        return 0.0
                    if isinstance(v, (int, float)):
                        return float(v)
                    if isinstance(v, str):
                        return float(v)
                    if isinstance(v, dict):
                        for k in ("amount", "value", "usd_amount", "fee", "quantity"):
                            if k in v:
                                try:
                                    return float(v[k])
                                except Exception:
                                    continue
                    if isinstance(v, (list, tuple)):
                        return float(sum(_fee_to_float(x) for x in v))
                    return 0.0
                except Exception:
                    return 0.0

            def _to_decimal(x: Any) -> Decimal:
                try:
                    if x is None:
                        return Decimal("0")
                    return Decimal(str(x))
                except Exception:
                    return Decimal("0")

            def _usd_cents(d: Decimal) -> Decimal:
                """Round a Decimal to 2 decimal places (cents)."""
                return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            # --- Fees (sum from executions + order-level) ---
            fee_total = 0.0
            execs = order.get("executions", []) or []
            for ex in execs:
                try:
                    for fk in ("fee", "fees", "fee_amount", "fee_usd", "fee_in_usd"):
                        if fk in ex:
                            fee_total += _fee_to_float(ex.get(fk))
                except Exception:
                    continue
            for fk in ("fee", "fees", "fee_amount", "fee_usd", "fee_in_usd"):
                if fk in order:
                    fee_total += _fee_to_float(order.get(fk))

            # --- Try order-level filled fields first (Robinhood's own accounting) ---
            avg_p_raw = order.get("average_price", None) or order.get("avg_price", None)
            filled_q_raw = order.get("filled_asset_quantity", None) or order.get("filled_quantity", None)

            if avg_p_raw is not None and filled_q_raw is not None:
                avg_p_d = _to_decimal(avg_p_raw)
                filled_q_d = _to_decimal(filled_q_raw)
                if filled_q_d > 0 and avg_p_d > 0:
                    notional_d = _usd_cents(avg_p_d * filled_q_d)
                    return (
                        float(filled_q_d),
                        float(avg_p_d),
                        float(notional_d),
                        float(fee_total),
                    )

            # --- Fallback: sum from executions ---
            if execs:
                total_notional_d = Decimal("0")
                total_qty_d = Decimal("0")
                for ex in execs:
                    try:
                        q = _to_decimal(ex.get("quantity", 0))
                        p = _to_decimal(ex.get("effective_price", 0))
                        if q > 0 and p > 0:
                            total_qty_d += q
                            total_notional_d += (q * p)
                    except Exception:
                        continue

                if total_qty_d > 0 and total_notional_d > 0:
                    avg_d = _usd_cents(total_notional_d / total_qty_d)
                    notional_d = _usd_cents(total_notional_d)
                    return (
                        float(total_qty_d),
                        float(avg_d),
                        float(notional_d),
                        float(fee_total),
                    )

            return 0.0, None, 0.0, float(fee_total)
        except Exception:
            return 0.0, None, 0.0, 0.0

    def _wait_for_order_terminal(self, symbol: str, order_id: str) -> Optional[dict]:
        """Blocks until order is filled/canceled/rejected, then returns the order dict."""
        terminal = {"filled", "canceled", "cancelled", "rejected", "failed", "error"}
        while True:
            o = self._get_order_by_id(symbol, order_id)
            if not o:
                time.sleep(1)
                continue
            st = str(o.get("state", "")).lower().strip()
            if st in terminal:
                return o
            time.sleep(1)

    def _reconcile_pending_orders(self) -> None:
        """
        If the hub/trader restarts mid-order, we keep the pre-order buying_power on disk and
        finish the accounting once the order shows as terminal in Robinhood.
        """
        try:
            pending = self._pnl_ledger.get("pending_orders", {})
            if not isinstance(pending, dict) or not pending:
                return

            # Loop until everything pending is resolved (matches your design: bot waits here).
            while True:
                pending = self._pnl_ledger.get("pending_orders", {})
                if not isinstance(pending, dict) or not pending:
                    break

                progressed = False

                for order_id, info in list(pending.items()):
                    try:
                        if self._trade_history_has_order_id(order_id):
                            # Already recorded (e.g., crash after writing history) -> just clear pending.
                            self._pnl_ledger["pending_orders"].pop(order_id, None)
                            self._save_pnl_ledger()
                            progressed = True
                            continue

                        symbol = str(info.get("symbol", "")).strip()
                        side = str(info.get("side", "")).strip().lower()
                        bp_before = float(info.get("buying_power_before", 0.0) or 0.0)

                        if not symbol or not side or not order_id:
                            self._pnl_ledger["pending_orders"].pop(order_id, None)
                            self._save_pnl_ledger()
                            progressed = True
                            continue

                        order = self._wait_for_order_terminal(symbol, order_id)
                        if not order:
                            continue

                        state = str(order.get("state", "")).lower().strip()
                        if state != "filled":
                            # Not filled -> no trade to record, clear pending.
                            self._pnl_ledger["pending_orders"].pop(order_id, None)
                            self._save_pnl_ledger()
                            progressed = True
                            continue

                        filled_qty, avg_price, notional_usd, fees_usd_val = self._extract_amounts_and_fees_from_order(order)
                        bp_after = self._get_buying_power()
                        bp_delta = float(bp_after) - float(bp_before)

                        self._record_trade(
                            side=side,
                            symbol=symbol,
                            qty=float(filled_qty),
                            price=float(avg_price) if avg_price is not None else None,
                            avg_cost_basis=info.get("avg_cost_basis", None),
                            pnl_pct=info.get("pnl_pct", None),
                            tag=info.get("tag", None),
                            order_id=order_id,
                            fees_usd=float(fees_usd_val) if fees_usd_val else None,
                            buying_power_before=bp_before,
                            buying_power_after=bp_after,
                            buying_power_delta=bp_delta,
                        )

                        # Clear pending now that we recorded it
                        self._pnl_ledger["pending_orders"].pop(order_id, None)
                        self._save_pnl_ledger()
                        progressed = True

                    except Exception:
                        continue

                if not progressed:
                    time.sleep(1)

        except Exception:
            pass

    def _record_trade(
        self,
        side: str,
        symbol: str,
        qty: float,
        price: Optional[float] = None,
        avg_cost_basis: Optional[float] = None,
        pnl_pct: Optional[float] = None,
        tag: Optional[str] = None,
        order_id: Optional[str] = None,
        fees_usd: Optional[float] = None,
        buying_power_before: Optional[float] = None,
        buying_power_after: Optional[float] = None,
        buying_power_delta: Optional[float] = None,
    ) -> None:
        """
        Minimal local ledger for GUI:
        - append trade_history.jsonl
        - update pnl_ledger.json on sells (now using buying power delta when available)
        - persist per-coin open position cost (USD) so realized profit is exact
        """
        ts = time.time()

        side_l = str(side or "").lower().strip()
        base = str(symbol or "").upper().split("-")[0].strip()

        # Ensure ledger keys exist (back-compat)
        try:
            if not isinstance(self._pnl_ledger, dict):
                self._pnl_ledger = {}
            self._pnl_ledger.setdefault("total_realized_profit_usd", 0.0)
            self._pnl_ledger.setdefault("open_positions", {})
            self._pnl_ledger.setdefault("pending_orders", {})
        except Exception:
            pass

        realized = None
        position_cost_used = None
        position_cost_after = None

        # --- Exact USD-based accounting (your design) ---
        if base and (buying_power_delta is not None):
            try:
                bp_delta = float(buying_power_delta)
            except Exception:
                bp_delta = None

            if bp_delta is not None:
                try:
                    open_pos = self._pnl_ledger.get("open_positions", {})
                    if not isinstance(open_pos, dict):
                        open_pos = {}
                        self._pnl_ledger["open_positions"] = open_pos

                    pos = open_pos.get(base, None)
                    if not isinstance(pos, dict):
                        pos = {"usd_cost": 0.0, "qty": 0.0}
                        open_pos[base] = pos

                    pos_usd_cost = float(pos.get("usd_cost", 0.0) or 0.0)
                    pos_qty = float(pos.get("qty", 0.0) or 0.0)

                    q = float(qty or 0.0)

                    if side_l == "buy":
                        usd_used = -bp_delta  # buying power drops on buys
                        if usd_used < 0.0:
                            usd_used = 0.0

                        pos["usd_cost"] = float(pos_usd_cost) + float(usd_used)
                        pos["qty"] = float(pos_qty) + float(q if q > 0.0 else 0.0)

                        position_cost_after = float(pos["usd_cost"])

                        # Save because open position changed (needs to persist across restarts)
                        self._save_pnl_ledger()

                    elif side_l == "sell":
                        usd_got = bp_delta  # buying power rises on sells
                        if usd_got < 0.0:
                            usd_got = 0.0

                        # If partial sell ever happens, allocate cost pro-rata by qty.
                        if pos_qty > 0.0 and q > 0.0:
                            frac = min(1.0, float(q) / float(pos_qty))
                        else:
                            frac = 1.0

                        cost_used = float(pos_usd_cost) * float(frac)
                        pos["usd_cost"] = float(pos_usd_cost) - float(cost_used)
                        pos["qty"] = float(pos_qty) - float(q if q > 0.0 else 0.0)

                        position_cost_used = float(cost_used)
                        position_cost_after = float(pos.get("usd_cost", 0.0) or 0.0)

                        realized = float(usd_got) - float(cost_used)
                        self._pnl_ledger["total_realized_profit_usd"] = float(self._pnl_ledger.get("total_realized_profit_usd", 0.0) or 0.0) + float(realized)

                        # Clean up tiny dust
                        if float(pos.get("qty", 0.0) or 0.0) <= 1e-12 or float(pos.get("usd_cost", 0.0) or 0.0) <= 1e-6:
                            open_pos.pop(base, None)

                        self._save_pnl_ledger()

                except Exception:
                    pass

        # --- Fallback (old behavior) if we couldn't compute from buying power ---
        if realized is None and side_l == "sell" and price is not None and avg_cost_basis is not None:
            try:
                fee_val = float(fees_usd) if fees_usd is not None else 0.0
                realized = (float(price) - float(avg_cost_basis)) * float(qty) - fee_val
                self._pnl_ledger["total_realized_profit_usd"] = float(self._pnl_ledger.get("total_realized_profit_usd", 0.0)) + float(realized)
                self._save_pnl_ledger()
            except Exception:
                realized = None

        entry = {
            "ts": ts,
            "side": side,
            "tag": tag,
            "symbol": symbol,
            "qty": qty,
            "price": price,
            "avg_cost_basis": avg_cost_basis,
            "pnl_pct": pnl_pct,
            "fees_usd": fees_usd,
            "realized_profit_usd": realized,
            "order_id": order_id,
            "buying_power_before": float(buying_power_before) if buying_power_before is not None else None,
            "buying_power_after": float(buying_power_after) if buying_power_after is not None else None,
            "buying_power_delta": float(buying_power_delta) if buying_power_delta is not None else None,
            "position_cost_used_usd": float(position_cost_used) if position_cost_used is not None else None,
            "position_cost_after_usd": float(position_cost_after) if position_cost_after is not None else None,
        }
        self._append_jsonl(TRADE_HISTORY_PATH, entry)




    def _write_trader_status(self, status: dict) -> None:
        self._atomic_write_json(TRADER_STATUS_PATH, status)

    @staticmethod
    def _get_current_timestamp() -> int:
        return int(datetime.datetime.now(tz=datetime.timezone.utc).timestamp())

    @staticmethod
    def _fmt_price(price: float) -> str:
        """
        Dynamic decimal formatting by magnitude:
        - >= 1.0   -> 2 decimals (BTC/ETH/etc won't show 8 decimals)
        - <  1.0   -> enough decimals to show meaningful digits (based on first non-zero),
                     then trim trailing zeros.
        """
        try:
            p = float(price)
        except Exception:
            return "N/A"

        if p == 0:
            return "0"

        ap = abs(p)

        if ap >= 1.0:
            decimals = 2
        else:
            # Example:
            # 0.5      -> decimals ~ 4 (prints "0.5" after trimming zeros)
            # 0.05     -> 5
            # 0.005    -> 6
            # 0.000012 -> 8
            decimals = int(-math.floor(math.log10(ap))) + 3
            decimals = max(2, min(12, decimals))

        s = f"{p:.{decimals}f}"

        # Trim useless trailing zeros for cleaner output (0.5000 -> 0.5)
        if "." in s:
            s = s.rstrip("0").rstrip(".")

        return s


    @staticmethod
    def _read_long_dca_signal(symbol: str) -> int:
        """
        Reads long_dca_signal.txt from the per-coin folder (same folder rules as trader.py).

        Used for:
        - Start gate: start trades at level 3+
        - DCA assist: levels 4-9 map to trader DCA stages 0-5 (trade starts at level 3 => stage 0)
        """
        sym = str(symbol).upper().strip()
        folder = base_paths.get(sym, main_dir if sym == "BTC" else os.path.join(main_dir, sym))
        path = os.path.join(folder, "long_dca_signal.txt")
        try:
            with open(path, "r") as f:
                raw = f.read().strip()
            val = int(float(raw))
            return val
        except Exception:
            return 0


    @staticmethod
    def _read_short_dca_signal(symbol: str) -> int:
        """
        Reads short_dca_signal.txt from the per-coin folder (same folder rules as trader.py).

        Used for:
        - Start gate: start trades at level 3+
        - DCA assist: levels 4-9 map to trader DCA stages 0-5 (trade starts at level 3 => stage 0)
        """
        sym = str(symbol).upper().strip()
        folder = base_paths.get(sym, main_dir if sym == "BTC" else os.path.join(main_dir, sym))
        path = os.path.join(folder, "short_dca_signal.txt")
        try:
            with open(path, "r") as f:
                raw = f.read().strip()
            val = int(float(raw))
            return val
        except Exception:
            return 0

    @staticmethod
    def _read_long_price_levels(symbol: str) -> list:
        """
        Reads low_bound_prices.html from the per-coin folder and returns a list of LONG (blue) price levels.

        Returned ordering is highest->lowest so:
          N1 = 1st blue line (top)
          ...
          N9 = 9th blue line (bottom)
        """
        sym = str(symbol).upper().strip()
        folder = base_paths.get(sym, main_dir if sym == "BTC" else os.path.join(main_dir, sym))
        path = os.path.join(folder, "low_bound_prices.html")
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = (f.read() or "").strip()
            if not raw:
                return []

            # Normalize common formats: python-list, comma-separated, newline-separated
            raw = raw.strip().strip("[]()")
            raw = raw.replace(",", " ").replace(";", " ").replace("|", " ")
            raw = raw.replace("\n", " ").replace("\t", " ")
            parts = [p for p in raw.split() if p]

            vals = []
            for p in parts:
                try:
                    vals.append(float(p))
                except Exception:
                    continue

            # De-dupe, then sort high->low for stable N1..N9 mapping
            out = []
            seen = set()
            for v in vals:
                k = round(float(v), 12)
                if k in seen:
                    continue
                seen.add(k)
                out.append(float(v))
            out.sort(reverse=True)
            return out
        except Exception:
            return []



    def initialize_dca_levels(self):

        """
        Initializes the DCA levels_triggered dictionary based on the number of buy orders
        that have occurred after the first buy order following the most recent sell order
        for each cryptocurrency.
        """
        holdings = self.get_holdings()
        if not holdings or "results" not in holdings:
            print("No holdings found. Skipping DCA levels initialization.")
            return

        for holding in holdings.get("results", []):
            symbol = holding["asset_code"]

            full_symbol = f"{symbol}-USD"
            orders = self.get_orders(full_symbol)
            
            if not orders or "results" not in orders:
                print(f"No orders found for {full_symbol}. Skipping.")
                continue

            # Filter for filled buy and sell orders
            filled_orders = [
                order for order in orders["results"]
                if order["state"] == "filled" and order["side"] in ["buy", "sell"]
            ]
            
            if not filled_orders:
                print(f"No filled buy or sell orders for {full_symbol}. Skipping.")
                continue

            # Sort orders by creation time in ascending order (oldest first)
            filled_orders.sort(key=lambda x: x["created_at"])

            # Find the timestamp of the most recent sell order
            most_recent_sell_time = None
            for order in reversed(filled_orders):
                if order["side"] == "sell":
                    most_recent_sell_time = order["created_at"]
                    break

            # Determine the cutoff time for buy orders
            if most_recent_sell_time:
                # Find all buy orders after the most recent sell
                relevant_buy_orders = [
                    order for order in filled_orders
                    if order["side"] == "buy" and order["created_at"] > most_recent_sell_time
                ]
                if not relevant_buy_orders:
                    print(f"No buy orders after the most recent sell for {full_symbol}.")
                    self.dca_levels_triggered[symbol] = []
                    continue
                print(f"Most recent sell for {full_symbol} at {most_recent_sell_time}.")
            else:
                # If no sell orders, consider all buy orders
                relevant_buy_orders = [
                    order for order in filled_orders
                    if order["side"] == "buy"
                ]
                if not relevant_buy_orders:
                    print(f"No buy orders for {full_symbol}. Skipping.")
                    self.dca_levels_triggered[symbol] = []
                    continue
                print(f"No sell orders found for {full_symbol}. Considering all buy orders.")

            # Ensure buy orders are sorted by creation time ascending
            relevant_buy_orders.sort(key=lambda x: x["created_at"])

            # Identify the first buy order in the relevant list
            first_buy_order = relevant_buy_orders[0]
            first_buy_time = first_buy_order["created_at"]

            # Count the number of buy orders after the first buy
            buy_orders_after_first = [
                order for order in relevant_buy_orders
                if order["created_at"] > first_buy_time
            ]

            triggered_levels_count = len(buy_orders_after_first)

            # Track DCA by stage index (0, 1, 2, ...) rather than % values.
            # This makes neural-vs-hardcoded clean, and allows repeating the -50% stage indefinitely.
            self.dca_levels_triggered[symbol] = list(range(triggered_levels_count))
            print(f"Initialized DCA stages for {symbol}: {triggered_levels_count}")


    def _seed_dca_window_from_history(self) -> None:
        """
        Seeds in-memory DCA buy timestamps from TRADE_HISTORY_PATH so the 24h limit
        works across restarts.

        Uses the local GUI trade history (tag == "DCA") and resets per trade at the most recent sell.
        """
        now_ts = time.time()
        cutoff = now_ts - float(getattr(self, "dca_window_seconds", 86400))

        self._dca_buy_ts = {}
        self._dca_last_sell_ts = {}

        if not os.path.isfile(TRADE_HISTORY_PATH):
            return

        try:
            with open(TRADE_HISTORY_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = (line or "").strip()
                    if not line:
                        continue

                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue

                    ts = obj.get("ts", None)
                    side = str(obj.get("side", "")).lower()
                    tag = obj.get("tag", None)
                    sym_full = str(obj.get("symbol", "")).upper().strip()
                    base = sym_full.split("-")[0].strip() if sym_full else ""
                    if not base:
                        continue

                    try:
                        ts_f = float(ts)
                    except Exception:
                        continue

                    if side == "sell":
                        prev = float(self._dca_last_sell_ts.get(base, 0.0) or 0.0)
                        if ts_f > prev:
                            self._dca_last_sell_ts[base] = ts_f

                    elif side == "buy" and tag == "DCA":
                        self._dca_buy_ts.setdefault(base, []).append(ts_f)

        except Exception:
            return

        # Keep only DCA buys after the last sell (current trade) and within rolling 24h
        for base, ts_list in list(self._dca_buy_ts.items()):
            last_sell = float(self._dca_last_sell_ts.get(base, 0.0) or 0.0)
            kept = [t for t in ts_list if (t > last_sell) and (t >= cutoff)]
            kept.sort()
            self._dca_buy_ts[base] = kept


    def _dca_window_count(self, base_symbol: str, now_ts: Optional[float] = None) -> int:
        """
        Count of DCA buys for this coin within rolling 24h in the *current trade*.
        Current trade boundary = most recent sell we observed for this coin.
        """
        base = str(base_symbol).upper().strip()
        if not base:
            return 0

        now = float(now_ts if now_ts is not None else time.time())
        cutoff = now - float(getattr(self, "dca_window_seconds", 86400))
        last_sell = float(self._dca_last_sell_ts.get(base, 0.0) or 0.0)

        ts_list = list(self._dca_buy_ts.get(base, []) or [])
        ts_list = [t for t in ts_list if (t > last_sell) and (t >= cutoff)]
        self._dca_buy_ts[base] = ts_list
        return len(ts_list)


    def _note_dca_buy(self, base_symbol: str, ts: Optional[float] = None) -> None:
        base = str(base_symbol).upper().strip()
        if not base:
            return
        t = float(ts if ts is not None else time.time())
        self._dca_buy_ts.setdefault(base, []).append(t)
        self._dca_window_count(base, now_ts=t)  # prune in-place


    def _reset_dca_window_for_trade(self, base_symbol: str, sold: bool = False, ts: Optional[float] = None) -> None:
        base = str(base_symbol).upper().strip()
        if not base:
            return
        if sold:
            self._dca_last_sell_ts[base] = float(ts if ts is not None else time.time())
        self._dca_buy_ts[base] = []


    def make_api_request(self, method: str, path: str, body: Optional[str] = "") -> Any:

        timestamp = self._get_current_timestamp()
        headers = self.get_authorization_header(method, path, body, timestamp)
        url = self.base_url + path

        try:
            if method == "GET":
                response = requests.get(url, headers=headers, timeout=10)
            elif method == "POST":
                response = requests.post(url, headers=headers, json=json.loads(body), timeout=10)

            response.raise_for_status()
            return response.json()
        except requests.HTTPError as http_err:
            try:
                # Parse and return the JSON error response
                error_response = response.json()
                return error_response  # Return the JSON error for further handling
            except Exception:
                return None
        except Exception:
            return None

    def get_authorization_header(
            self, method: str, path: str, body: str, timestamp: int
    ) -> Dict[str, str]:
        message_to_sign = f"{self.api_key}{timestamp}{path}{method}{body}"
        signed = self.private_key.sign(message_to_sign.encode("utf-8"))

        return {
            "x-api-key": self.api_key,
            "x-signature": base64.b64encode(signed.signature).decode("utf-8"),
            "x-timestamp": str(timestamp),
        }

    def get_account(self) -> Any:
        path = "/api/v1/crypto/trading/accounts/"
        return self.make_api_request("GET", path)

    def get_holdings(self) -> Any:
        path = "/api/v1/crypto/trading/holdings/"
        return self.make_api_request("GET", path)

    def get_trading_pairs(self) -> Any:
        path = "/api/v1/crypto/trading/trading_pairs/"
        response = self.make_api_request("GET", path)

        if not response or "results" not in response:
            return []

        trading_pairs = response.get("results", [])
        if not trading_pairs:
            return []

        return trading_pairs

    def get_orders(self, symbol: str, max_pages: int = 25) -> Any:
        """Fetch crypto orders for a symbol, following pagination so older bot buys
        (which may be on earlier pages) are included.

        Robinhood's orders endpoint is paginated. If we only read the first page,
        a newer manual SELL can push earlier bot BUYs off page 1, which then breaks
        cost-basis reconstruction. This method returns a single dict with an
        aggregated "results" list.
        """
        path = f"/api/v1/crypto/trading/orders/?symbol={symbol}"
        first = self.make_api_request("GET", path)

        # If the API didn't return the expected shape, keep legacy behavior.
        if not isinstance(first, dict):
            return first

        results = list(first.get("results", []) or [])
        next_url = first.get("next", None)

        # Follow pagination links (best-effort, capped).
        pages = 1
        while next_url and pages < int(max_pages):
            try:
                nxt = str(next_url).strip()
                if not nxt:
                    break

                # Convert absolute URL -> relative path expected by make_api_request().
                if nxt.startswith(self.base_url):
                    nxt_path = nxt[len(self.base_url):]
                elif nxt.startswith("/"):
                    nxt_path = nxt
                elif "://" in nxt:
                    # Fallback: strip scheme+host
                    try:
                        nxt_path = "/" + nxt.split("://", 1)[1].split("/", 1)[1]
                    except Exception:
                        break
                else:
                    nxt_path = "/" + nxt

                resp = self.make_api_request("GET", nxt_path)
                if not isinstance(resp, dict):
                    break

                results.extend(list(resp.get("results", []) or []))
                next_url = resp.get("next", None)
                pages += 1
            except Exception:
                break

        out = dict(first)
        out["results"] = results
        out["next"] = None
        return out

    def calculate_cost_basis(self):
        holdings = self.get_holdings()
        if not holdings or "results" not in holdings:
            return {}

        active_assets = {holding["asset_code"] for holding in holdings.get("results", [])}
        current_quantities = {
            holding["asset_code"]: float(holding["total_quantity"])
            for holding in holdings.get("results", [])
        }

        cost_basis = {}

        for asset_code in active_assets:
            orders = self.get_orders(f"{asset_code}-USD")
            if not orders or "results" not in orders:
                continue

            # Get all filled buy orders, sorted from most recent to oldest
            buy_orders = [
                order for order in orders["results"]
                if order["side"] == "buy" and order["state"] == "filled"
            ]
            buy_orders.sort(key=lambda x: x["created_at"], reverse=True)

            remaining_quantity = current_quantities[asset_code]
            total_cost = 0.0

            for order in buy_orders:
                for execution in order.get("executions", []):
                    quantity = float(execution["quantity"])
                    price = float(execution["effective_price"])

                    if remaining_quantity <= 0:
                        break

                    # Use only the portion of the quantity needed to match the current holdings
                    if quantity > remaining_quantity:
                        total_cost += remaining_quantity * price
                        remaining_quantity = 0
                    else:
                        total_cost += quantity * price
                        remaining_quantity -= quantity

                if remaining_quantity <= 0:
                    break

            if current_quantities[asset_code] > 0:
                cost_basis[asset_code] = total_cost / current_quantities[asset_code]
            else:
                cost_basis[asset_code] = 0.0

        return cost_basis

    def get_price(self, symbols: list) -> Dict[str, float]:
        buy_prices = {}
        sell_prices = {}
        valid_symbols = []

        for symbol in symbols:
            if symbol == "USDC-USD":
                continue

            path = f"/api/v1/crypto/marketdata/best_bid_ask/?symbol={symbol}"
            response = self.make_api_request("GET", path)

            if response and "results" in response:
                result = response["results"][0]
                ask = float(result["ask_inclusive_of_buy_spread"])
                bid = float(result["bid_inclusive_of_sell_spread"])

                buy_prices[symbol] = ask
                sell_prices[symbol] = bid
                valid_symbols.append(symbol)

                # Update cache for transient failures later
                try:
                    self._last_good_bid_ask[symbol] = {"ask": ask, "bid": bid, "ts": time.time()}
                except Exception:
                    pass
            else:
                # Fallback to cached bid/ask so account value never drops due to a transient miss
                cached = None
                try:
                    cached = self._last_good_bid_ask.get(symbol)
                except Exception:
                    cached = None

                if cached:
                    ask = float(cached.get("ask", 0.0) or 0.0)
                    bid = float(cached.get("bid", 0.0) or 0.0)
                    if ask > 0.0 and bid > 0.0:
                        buy_prices[symbol] = ask
                        sell_prices[symbol] = bid
                        valid_symbols.append(symbol)

        return buy_prices, sell_prices, valid_symbols


    def place_buy_order(
        self,
        client_order_id: str,
        side: str,
        order_type: str,
        symbol: str,
        amount_in_usd: float,
        avg_cost_basis: Optional[float] = None,
        pnl_pct: Optional[float] = None,
        tag: Optional[str] = None,
    ) -> Any:
        # Fetch the current price of the asset (for sizing only)
        current_buy_prices, current_sell_prices, valid_symbols = self.get_price([symbol])
        current_price = current_buy_prices[symbol]
        asset_quantity = amount_in_usd / current_price

        max_retries = 5
        retries = 0

        while retries < max_retries:
            retries += 1
            response = None
            try:
                # Default precision to 8 decimals initially
                rounded_quantity = round(asset_quantity, 8)

                body = {
                    "client_order_id": client_order_id,
                    "side": side,
                    "type": order_type,
                    "symbol": symbol,
                    "market_order_config": {
                        "asset_quantity": f"{rounded_quantity:.8f}"  # Start with 8 decimal places
                    }
                }

                path = "/api/v1/crypto/trading/orders/"

                # --- exact profit tracking snapshot (BEFORE placing order) ---
                buying_power_before = self._get_buying_power()

                response = self.make_api_request("POST", path, json.dumps(body))
                if response and "errors" not in response:
                    order_id = response.get("id", None)

                    # Persist the pre-order buying power so restarts can reconcile precisely
                    try:
                        if order_id:
                            self._pnl_ledger.setdefault("pending_orders", {})
                            self._pnl_ledger["pending_orders"][order_id] = {
                                "symbol": symbol,
                                "side": "buy",
                                "buying_power_before": float(buying_power_before),
                                "avg_cost_basis": float(avg_cost_basis) if avg_cost_basis is not None else None,
                                "pnl_pct": float(pnl_pct) if pnl_pct is not None else None,
                                "tag": tag,
                                "created_ts": time.time(),
                            }
                            self._save_pnl_ledger()
                    except Exception:
                        pass

                    # Wait until the order is actually complete in the system, then use order history executions
                    if order_id:
                        order = self._wait_for_order_terminal(symbol, order_id)
                        state = str(order.get("state", "")).lower().strip() if isinstance(order, dict) else ""
                        if state != "filled":
                            # Not filled -> clear pending and do not record a trade
                            try:
                                self._pnl_ledger.get("pending_orders", {}).pop(order_id, None)
                                self._save_pnl_ledger()
                            except Exception:
                                pass
                            return None

                        filled_qty, avg_fill_price, notional_usd, fees_usd_val = self._extract_amounts_and_fees_from_order(order)

                        buying_power_after = self._get_buying_power()
                        buying_power_delta = float(buying_power_after) - float(buying_power_before)

                        # Record for GUI history (ACTUAL fill from order history)
                        self._record_trade(
                            side="buy",
                            symbol=symbol,
                            qty=float(filled_qty),
                            price=float(avg_fill_price) if avg_fill_price is not None else None,
                            avg_cost_basis=float(avg_cost_basis) if avg_cost_basis is not None else None,
                            pnl_pct=float(pnl_pct) if pnl_pct is not None else None,
                            tag=tag,
                            order_id=order_id,
                            fees_usd=float(fees_usd_val) if fees_usd_val else None,
                            buying_power_before=buying_power_before,
                            buying_power_after=buying_power_after,
                            buying_power_delta=buying_power_delta,
                        )

                        # Clear pending now that it is recorded
                        try:
                            self._pnl_ledger.get("pending_orders", {}).pop(order_id, None)
                            self._save_pnl_ledger()
                        except Exception:
                            pass

                    return response  # Successfully placed (and fully filled) order

            except Exception:
                pass #print(traceback.format_exc())

            # Check for precision errors
            if response and "errors" in response:
                for error in response["errors"]:
                    if "has too much precision" in error.get("detail", ""):
                        # Extract required precision directly from the error message
                        detail = error["detail"]
                        nearest_value = detail.split("nearest ")[1].split(" ")[0]

                        decimal_places = len(nearest_value.split(".")[1].rstrip("0"))
                        asset_quantity = round(asset_quantity, decimal_places)
                        break
                    elif "must be greater than or equal to" in error.get("detail", ""):
                        return None

        return None



    def place_sell_order(
        self,
        client_order_id: str,
        side: str,
        order_type: str,
        symbol: str,
        asset_quantity: float,
        expected_price: Optional[float] = None,
        avg_cost_basis: Optional[float] = None,
        pnl_pct: Optional[float] = None,
        tag: Optional[str] = None,
    ) -> Any:
        body = {
            "client_order_id": client_order_id,
            "side": side,
            "type": order_type,
            "symbol": symbol,
            "market_order_config": {
                "asset_quantity": f"{asset_quantity:.8f}"
            }
        }

        path = "/api/v1/crypto/trading/orders/"

        # --- exact profit tracking snapshot (BEFORE placing order) ---
        buying_power_before = self._get_buying_power()

        response = self.make_api_request("POST", path, json.dumps(body))

        if response and isinstance(response, dict) and "errors" not in response:
            order_id = response.get("id", None)

            # Persist the pre-order buying power so restarts can reconcile precisely
            try:
                if order_id:
                    self._pnl_ledger.setdefault("pending_orders", {})
                    self._pnl_ledger["pending_orders"][order_id] = {
                        "symbol": symbol,
                        "side": "sell",
                        "buying_power_before": float(buying_power_before),
                        "avg_cost_basis": float(avg_cost_basis) if avg_cost_basis is not None else None,
                        "pnl_pct": float(pnl_pct) if pnl_pct is not None else None,
                        "tag": tag,
                        "created_ts": time.time(),
                    }
                    self._save_pnl_ledger()
            except Exception:
                pass

            # Best-effort: pull actual avg fill price + fees from order executions
            actual_price = float(expected_price) if expected_price is not None else None
            actual_qty = float(asset_quantity)
            fees_usd = None

            try:
                if order_id:
                    match = self._wait_for_order_terminal(symbol, order_id)
                    if not match:
                        return response

                    if str(match.get("state", "")).lower() != "filled":
                        # Not filled -> clear pending and do not record a trade
                        try:
                            self._pnl_ledger.get("pending_orders", {}).pop(order_id, None)
                            self._save_pnl_ledger()
                        except Exception:
                            pass
                        return response

                    # Use Decimal-precision extraction for accurate P&L
                    filled_qty, avg_fill, notional_usd, fee_total = self._extract_amounts_and_fees_from_order(match)

                    if filled_qty > 0.0 and avg_fill is not None:
                        actual_qty = filled_qty
                        actual_price = avg_fill

                    fees_usd = float(fee_total) if fee_total else 0.0

            except Exception:
                pass #print(traceback.format_exc())

            # If we managed to get a better fill price, update the displayed PnL% too
            if avg_cost_basis is not None and actual_price is not None:
                try:
                    acb = float(avg_cost_basis)
                    if acb > 0:
                        pnl_pct = ((float(actual_price) - acb) / acb) * 100.0
                except Exception:
                    pass

            # --- exact profit tracking snapshot (AFTER the order is complete) ---
            buying_power_after = self._get_buying_power()
            buying_power_delta = float(buying_power_after) - float(buying_power_before)

            self._record_trade(
                side="sell",
                symbol=symbol,
                qty=float(actual_qty),
                price=float(actual_price) if actual_price is not None else None,
                avg_cost_basis=float(avg_cost_basis) if avg_cost_basis is not None else None,
                pnl_pct=float(pnl_pct) if pnl_pct is not None else None,
                tag=tag,
                order_id=order_id,
                fees_usd=float(fees_usd) if fees_usd is not None else None,
                buying_power_before=buying_power_before,
                buying_power_after=buying_power_after,
                buying_power_delta=buying_power_delta,
            )

            # Clear pending now that it is recorded
            try:
                if order_id:
                    self._pnl_ledger.get("pending_orders", {}).pop(order_id, None)
                    self._save_pnl_ledger()
            except Exception:
                pass

        return response




    def _check_hard_stop_loss(self, symbol: str, gain_loss_pct: float, 
                              quantity: float, full_symbol: str, 
                              avg_cost_basis: float = 0.0) -> bool:
        """
        Check and execute hard stop loss if enabled in small account settings.
        Returns True if position was closed, False otherwise.
        
        This is opt-in via small_account_settings.hard_stop_enabled.
        If not enabled, this method does nothing (preserves existing behavior).
        """
        # Only active if explicitly enabled in settings
        if not getattr(self, 'hard_stop_enabled', False):
            return False
        
        hard_stop = getattr(self, 'hard_stop_pct', -35.0)
        
        if gain_loss_pct <= hard_stop:
            # One-time neural override: if network is nearly unanimous BUY, allow one more chance
            neural_level = self._read_long_dca_signal(symbol)
            override_key = f"{symbol}_stop_override"
            
            if not hasattr(self, '_stop_overrides'):
                self._stop_overrides = {}
            
            if neural_level >= 8 and not self._stop_overrides.get(override_key, False):
                print(
                    f"  [WARNING] HARD STOP at {gain_loss_pct:.1f}% BUT neural L{neural_level} "
                    f"is screaming BUY. Allowing ONE more chance to recover."
                )
                self._stop_overrides[override_key] = True
                return False
            
            print(
                f"  [HARD STOP] {symbol} at {gain_loss_pct:.1f}%. "
                f"Force exiting {quantity:.8f} units to preserve capital."
            )
            
            response = self.place_sell_order(
                str(uuid.uuid4()),
                "sell",
                "market",
                full_symbol,
                quantity,
                avg_cost_basis=avg_cost_basis,
                pnl_pct=gain_loss_pct,
                tag="HARD_STOP",
            )
            
            if response and "errors" not in response:
                # Cleanup state
                self.dca_levels_triggered.pop(symbol, None)
                self.trailing_pm.pop(symbol, None)
                self.tiered_profits.pop(symbol, None)
                if hasattr(self, '_stop_overrides'):
                    self._stop_overrides.pop(override_key, None)
                return True
        
        return False

    def _check_position_limits(self, symbol: str, additional_capital: float) -> bool:
        """
        Check if adding capital to a position would violate position limits.
        Returns True if okay to proceed, False if limit would be exceeded.
        
        Checks:
        - Max positions limit
        - Reserve requirement
        - Per-coin capital limit (future enhancement)
        """
        # Check reserve requirement
        if hasattr(self, 'reserve_minimum_pct') and self.reserve_minimum_pct > 0:
            try:
                _acct2 = self.get_account()
                buying_power = float(_acct2.get("buying_power", 0.0) or 0.0)
                # Estimate total account value = buying_power + cost of held positions
                _h2 = self.get_holdings()
                _held_cost = 0.0
                for _hh in _h2.get("results", []):
                    try:
                        _held_cost += float(_hh.get("cost_held_for_display", 0.0) or 0.0)
                    except Exception:
                        pass
                account_value = buying_power + _held_cost if (_held_cost > 0) else buying_power
                reserve_required = account_value * (self.reserve_minimum_pct / 100.0)
                
                if buying_power - additional_capital < reserve_required:
                    print(
                        f"  [WARNING] Reserve requirement (${reserve_required:.2f}, "
                        f"{self.reserve_minimum_pct:.1f}%) would be violated. "
                        f"Skipping trade."
                    )
                    return False
            except Exception:
                pass
        
        return True



    def manage_trades(self):
        trades_made = False  # Flag to track if any trade was made in this iteration

        # Hot-reload coins list + paths + trade params from GUI settings while running
        try:
            _refresh_paths_and_symbols()
            self.path_map = dict(base_paths)
            self.dca_levels = list(DCA_LEVELS)
            self.max_dca_buys_per_24h = int(MAX_DCA_BUYS_PER_24H)

            # Trailing PM settings (hot-reload)
            # Small account mode sets its own pm/trail values at startup via
            # _apply_account_tier_settings(). Those must NOT be overwritten here
            # by the GUI-level globals — doing so was causing the SELL line and
            # trailing stop to operate at the wrong (GUI-level) values.
            old_sig = getattr(self, "_last_trailing_settings_sig", None)

            if not getattr(self, '_small_account_active', False):
                # Standard mode: allow GUI-level hot-reload to update PM settings.
                new_gap = float(TRAILING_GAP_PCT)
                new_pm0 = float(PM_START_PCT_NO_DCA)
                new_pm1 = float(PM_START_PCT_WITH_DCA)
                self.trailing_gap_pct = new_gap
                self.pm_start_pct_no_dca = new_pm0
                self.pm_start_pct_with_dca = new_pm1

            # Build sig from the current instance values (whether just updated or
            # already set by small account mode) so the state-reset comparison is
            # always based on what the bot is actually using.
            new_sig = (
                float(self.trailing_gap_pct),
                float(self.pm_start_pct_no_dca),
                float(self.pm_start_pct_with_dca),
            )

            # If trailing settings genuinely changed, reset per-coin trailing state
            # so the line and peak update immediately with the new values.
            if (old_sig is not None) and (new_sig != old_sig):
                self.trailing_pm = {}

            self._last_trailing_settings_sig = new_sig
        except Exception:
            pass




        # Fetch account details
        account = self.get_account()
        # Fetch holdings
        holdings = self.get_holdings()
        # Fetch trading pairs
        trading_pairs = self.get_trading_pairs()

        # Use the stored cost_basis instead of recalculating
        cost_basis = self.cost_basis
        # Fetch current prices
        symbols = [holding["asset_code"] + "-USD" for holding in holdings.get("results", [])]

        # ALSO fetch prices for tracked coins even if not currently held (so GUI can show bid/ask lines)
        for s in crypto_symbols:
            full = f"{s}-USD"
            if full not in symbols:
                symbols.append(full)

        current_buy_prices, current_sell_prices, valid_symbols = self.get_price(symbols)

        # Calculate total account value (robust: never drop a held coin to $0 on transient API misses)
        snapshot_ok = True

        # buying power
        try:
            buying_power = float(account.get("buying_power", 0))
        except Exception:
            buying_power = 0.0
            snapshot_ok = False

        # holdings list (treat missing/invalid holdings payload as transient error)
        try:
            holdings_list = holdings.get("results", None) if isinstance(holdings, dict) else None
            if not isinstance(holdings_list, list):
                holdings_list = []
                snapshot_ok = False
        except Exception:
            holdings_list = []
            snapshot_ok = False

        holdings_buy_value = 0.0
        holdings_sell_value = 0.0

        for holding in holdings_list:
            try:
                asset = holding.get("asset_code")
                if asset == "USDC":
                    continue

                qty = float(holding.get("total_quantity", 0.0))
                if qty <= 0.0:
                    continue

                sym = f"{asset}-USD"
                bp = float(current_buy_prices.get(sym, 0.0) or 0.0)
                sp = float(current_sell_prices.get(sym, 0.0) or 0.0)

                # If any held asset is missing a usable price this tick, do NOT allow a new "low" snapshot
                if bp <= 0.0 or sp <= 0.0:
                    snapshot_ok = False
                    continue

                holdings_buy_value += qty * bp
                holdings_sell_value += qty * sp
            except Exception:
                snapshot_ok = False
                continue

        total_account_value = buying_power + holdings_sell_value
        in_use = (holdings_sell_value / total_account_value) * 100 if total_account_value > 0 else 0.0

        # If this tick is incomplete, fall back to last known-good snapshot so the GUI chart never gets a bogus dip.
        if (not snapshot_ok) or (total_account_value <= 0.0):
            last = getattr(self, "_last_good_account_snapshot", None) or {}
            if last.get("total_account_value") is not None:
                total_account_value = float(last["total_account_value"])
                buying_power = float(last.get("buying_power", buying_power or 0.0))
                holdings_sell_value = float(last.get("holdings_sell_value", holdings_sell_value or 0.0))
                holdings_buy_value = float(last.get("holdings_buy_value", holdings_buy_value or 0.0))
                in_use = float(last.get("percent_in_trade", in_use or 0.0))
        else:
            # Save last complete snapshot
            self._last_good_account_snapshot = {
                "total_account_value": float(total_account_value),
                "buying_power": float(buying_power),
                "holdings_sell_value": float(holdings_sell_value),
                "holdings_buy_value": float(holdings_buy_value),
                "percent_in_trade": float(in_use),
            }

        os.system('cls' if os.name == 'nt' else 'clear')
        print("\n--- Account Summary ---")
        print(f"Total Account Value: ${total_account_value:.2f}")
        print(f"Holdings Value: ${holdings_sell_value:.2f}")
        print(f"Percent In Trade: {in_use:.2f}%")
        _t1 = float(getattr(self, "profit_tier1_pct", 0.0))
        _t2 = float(getattr(self, "profit_tier2_pct", 0.0))
        if _t1 > 0.0:
            print(
                f"Profit Mode: TIERED  T1=+{_t1:.1f}% ({float(getattr(self, 'profit_tier1_fraction', 0.33))*100:.0f}%)  "
                f"T2=+{_t2:.1f}% ({float(getattr(self, 'profit_tier2_fraction', 0.50))*100:.0f}% of remainder)  "
                f"Trail rest | gap {self.trailing_gap_pct:.2f}%"
            )
        else:
            print(
                f"Trailing PM: start +{self.pm_start_pct_no_dca:.2f}% (no DCA) / +{self.pm_start_pct_with_dca:.2f}% (with DCA) "
                f"| gap {self.trailing_gap_pct:.2f}%"
            )
        print("\n--- Current Trades ---")

        positions = {}
        for holding in holdings.get("results", []):
            symbol = holding["asset_code"]
            full_symbol = f"{symbol}-USD"

            if full_symbol not in valid_symbols or symbol == "USDC":
                continue

            quantity = float(holding["total_quantity"])
            current_buy_price = current_buy_prices.get(full_symbol, 0)
            current_sell_price = current_sell_prices.get(full_symbol, 0)
            avg_cost_basis = cost_basis.get(symbol, 0)

            if avg_cost_basis > 0:
                gain_loss_percentage_buy = ((current_buy_price - avg_cost_basis) / avg_cost_basis) * 100
                gain_loss_percentage_sell = ((current_sell_price - avg_cost_basis) / avg_cost_basis) * 100
            else:
                gain_loss_percentage_buy = 0
                gain_loss_percentage_sell = 0
                print(f"  Warning: Average Cost Basis is 0 for {symbol}, Gain/Loss calculation skipped.")

            value = quantity * current_sell_price
            triggered_levels_count = len(self.dca_levels_triggered.get(symbol, []))
            triggered_levels = triggered_levels_count  # Number of DCA levels triggered

            # Determine the next DCA trigger for this coin (hardcoded % and optional neural level)
            next_stage = triggered_levels_count  # stage 0 == first DCA after entry (trade starts at neural level 3)

            # Hardcoded % for this stage (repeat -50% after we reach it)
            hard_next = self.dca_levels[next_stage] if next_stage < len(self.dca_levels) else self.dca_levels[-1]

            # Neural DCA applies to the levels BELOW the trade-start level.
            # Example: trade_start_level=3 => stages 0..5 map to N4..N9 (6 total).
            start_level = max(1, min(int(TRADE_START_LEVEL or 3), 9))
            neural_dca_max = max(0, 9 - start_level)

            if next_stage < neural_dca_max:
                neural_next = start_level + 1 + next_stage
                next_dca_display = f"{hard_next:.2f}% / N{neural_next}"
            else:
                next_dca_display = f"{hard_next:.2f}%"

            # --- DCA DISPLAY LINE (show whichever trigger will be hit first: higher of NEURAL line vs HARD line) ---
            # Hardcoded gives an actual price line: cost_basis * (1 + hard_next%).
            # Neural gives an actual price line from low_bound_prices.html (N1..N9).
            dca_line_source = "HARD"
            dca_line_price = 0.0
            dca_line_pct = 0.0

            if avg_cost_basis > 0:
                # Hardcoded trigger line price
                hard_line_price = avg_cost_basis * (1.0 + (hard_next / 100.0))

                # Default to hardcoded unless neural line is higher (hit first)
                dca_line_price = hard_line_price

                if next_stage < neural_dca_max:
                    neural_level_needed_disp = start_level + 1 + next_stage
                    neural_levels = self._read_long_price_levels(symbol)  # highest->lowest == N1..N9

                    neural_line_price = 0.0
                    if len(neural_levels) >= neural_level_needed_disp:
                        neural_line_price = float(neural_levels[neural_level_needed_disp - 1])

                    # Whichever is higher will be hit first as price drops
                    if neural_line_price > dca_line_price:
                        dca_line_price = neural_line_price
                        dca_line_source = f"NEURAL N{neural_level_needed_disp}"


                # PnL% shown alongside DCA is the normal buy-side PnL%
                # (same calculation as GUI "Buy Price PnL": current buy/ask vs avg cost basis)
                dca_line_pct = gain_loss_percentage_buy




            dca_line_price_disp = self._fmt_price(dca_line_price) if avg_cost_basis > 0 else "N/A"

            # Set color code:
            # - DCA is green if we're above the chosen DCA line, red if we're below it
            # - SELL stays based on profit vs cost basis (your original behavior)
            if dca_line_pct >= 0:
                color = Fore.GREEN
            else:
                color = Fore.RED

            if gain_loss_percentage_sell >= 0:
                color2 = Fore.GREEN
            else:
                color2 = Fore.RED

            # --- Trailing PM display (per-coin, isolated) ---
            # Display uses current state if present; otherwise shows the base PM start line.
            trail_status = "N/A"
            pm_start_pct_disp = 0.0
            base_pm_line_disp = 0.0
            trail_line_disp = 0.0
            trail_peak_disp = 0.0
            above_disp = False
            dist_to_trail_pct = 0.0

            if avg_cost_basis > 0:
                pm_start_pct_disp = self.pm_start_pct_no_dca if int(triggered_levels) == 0 else self.pm_start_pct_with_dca
                base_pm_line_disp = avg_cost_basis * (1.0 + (pm_start_pct_disp / 100.0))

                state = self.trailing_pm.get(symbol)
                if state is None:
                    trail_line_disp = base_pm_line_disp
                    trail_peak_disp = 0.0
                    active_disp = False
                else:
                    trail_line_disp = float(state.get("line", base_pm_line_disp))
                    trail_peak_disp = float(state.get("peak", 0.0))
                    active_disp = bool(state.get("active", False))

                above_disp = current_sell_price >= trail_line_disp
                # If we're already above the line, trailing is effectively "on/armed" (even if active flips this tick)
                trail_status = "ON" if (active_disp or above_disp) else "OFF"

                if trail_line_disp > 0:
                    dist_to_trail_pct = ((current_sell_price - trail_line_disp) / trail_line_disp) * 100.0
            file = open(symbol+'_current_price.txt', 'w+')
            file.write(str(current_buy_price))
            file.close()
            positions[symbol] = {
                "quantity": quantity,
                "avg_cost_basis": avg_cost_basis,
                "current_buy_price": current_buy_price,
                "current_sell_price": current_sell_price,
                "gain_loss_pct_buy": gain_loss_percentage_buy,
                "gain_loss_pct_sell": gain_loss_percentage_sell,
                "value_usd": value,
                "dca_triggered_stages": int(triggered_levels_count),
                "next_dca_display": next_dca_display,
                "dca_line_price": float(dca_line_price) if dca_line_price else 0.0,
                "dca_line_source": dca_line_source,
                "dca_line_pct": float(dca_line_pct) if dca_line_pct else 0.0,
                "trail_active": True if (trail_status == "ON") else False,
                "trail_line": float(trail_line_disp) if trail_line_disp else 0.0,
                "trail_peak": float(trail_peak_disp) if trail_peak_disp else 0.0,
                "dist_to_trail_pct": float(dist_to_trail_pct) if dist_to_trail_pct else 0.0,
            }


            print(
                f"\nSymbol: {symbol}"
                f"  |  DCA: {color}{dca_line_pct:+.2f}%{Style.RESET_ALL} @ {self._fmt_price(current_buy_price)} (Line: {dca_line_price_disp} {dca_line_source} | Next: {next_dca_display})"
                f"  |  Gain/Loss SELL: {color2}{gain_loss_percentage_sell:.2f}%{Style.RESET_ALL} @ {self._fmt_price(current_sell_price)}"
                f"  |  DCA Levels Triggered: {triggered_levels}"
                f"  |  Trade Value: ${value:.2f}"
            )




            if avg_cost_basis > 0:
                print(
                    f"  Trailing Profit Margin"
                    f"  |  Line: {self._fmt_price(trail_line_disp)}"
                    f"  |  Above: {above_disp}"
                )
            else:
                print("  PM/Trail: N/A (avg_cost_basis is 0)")


            # --- HARD STOP LOSS CHECK (before trailing PM) ---
            # Only active if enabled in small account settings
            if self._check_hard_stop_loss(symbol, gain_loss_percentage_buy, quantity, full_symbol, avg_cost_basis):
                # Position was force-closed due to hard stop
                trades_made = True
                time.sleep(5)
                holdings = self.get_holdings()
                continue


            # --- Tiered profit taking + trailing stop ---
            # Tier 1 (e.g. +7%):  sell profit_tier1_fraction of ORIGINAL qty.
            # Tier 2 (e.g. +15%): sell profit_tier2_fraction of ORIGINAL qty.
            # Remainder:          trail with trailing_gap_pct until cross-below triggers full exit.
            # If tier pcts are 0.0 the tiers are skipped and the full position trails as before.
            if avg_cost_basis > 0:
                pm_start_pct = self.pm_start_pct_no_dca if int(triggered_levels) == 0 else self.pm_start_pct_with_dca
                base_pm_line = avg_cost_basis * (1.0 + (pm_start_pct / 100.0))
                trail_gap = self.trailing_gap_pct / 100.0

                t1_pct  = float(getattr(self, "profit_tier1_pct", 0.0))
                t1_frac = float(getattr(self, "profit_tier1_fraction", 0.33))
                t2_pct  = float(getattr(self, "profit_tier2_pct", 0.0))
                t2_frac = float(getattr(self, "profit_tier2_fraction", 0.50))

                # Init or retrieve per-coin tier state; orig_qty captured on first sight.
                tier_state = self.tiered_profits.get(symbol)
                if tier_state is None:
                    tier_state = {"orig_qty": quantity, 1: False, 2: False}
                    self.tiered_profits[symbol] = tier_state
                # Reset if position has grown (fresh entry after full exit)
                if quantity > tier_state.get("orig_qty", 0.0) * 1.01:
                    tier_state = {"orig_qty": quantity, 1: False, 2: False}
                    self.tiered_profits[symbol] = tier_state

                orig_qty = float(tier_state["orig_qty"])

                # --- Tier 1 partial sell ---
                if t1_pct > 0.0 and (not tier_state[1]) and gain_loss_percentage_sell >= t1_pct:
                    tier1_qty = round(orig_qty * t1_frac, 8)
                    tier1_qty = min(tier1_qty, quantity)
                    if tier1_qty > 0.0:
                        print(
                            f"  [TIER 1] {symbol} reached +{gain_loss_percentage_sell:.2f}% "
                            f"(target +{t1_pct:.1f}%). Selling {tier1_qty:.8f} "
                            f"({t1_frac*100:.0f}% of original position)."
                        )
                        response = self.place_sell_order(
                            str(uuid.uuid4()),
                            "sell",
                            "market",
                            full_symbol,
                            tier1_qty,
                            expected_price=current_sell_price,
                            avg_cost_basis=avg_cost_basis,
                            pnl_pct=gain_loss_percentage_sell,
                            tag="TIER1_SELL",
                        )
                        if response and isinstance(response, dict) and "errors" not in response:
                            tier_state[1] = True
                            trades_made = True
                            print(f"  Tier 1 sell placed for {symbol}. Holding remainder.")
                            time.sleep(5)
                            holdings = self.get_holdings()
                            continue

                # --- Tier 2 partial sell ---
                if t2_pct > 0.0 and tier_state[1] and (not tier_state[2]) and gain_loss_percentage_sell >= t2_pct:
                    tier2_qty = round(orig_qty * t2_frac, 8)
                    tier2_qty = min(tier2_qty, quantity)
                    if tier2_qty > 0.0:
                        print(
                            f"  [TIER 2] {symbol} reached +{gain_loss_percentage_sell:.2f}% "
                            f"(target +{t2_pct:.1f}%). Selling {tier2_qty:.8f} "
                            f"({t2_frac*100:.0f}% of original position)."
                        )
                        response = self.place_sell_order(
                            str(uuid.uuid4()),
                            "sell",
                            "market",
                            full_symbol,
                            tier2_qty,
                            expected_price=current_sell_price,
                            avg_cost_basis=avg_cost_basis,
                            pnl_pct=gain_loss_percentage_sell,
                            tag="TIER2_SELL",
                        )
                        if response and isinstance(response, dict) and "errors" not in response:
                            tier_state[2] = True
                            trades_made = True
                            print(f"  Tier 2 sell placed for {symbol}. Trailing remainder.")
                            time.sleep(5)
                            holdings = self.get_holdings()
                            continue

                # --- Trailing stop on remainder (or full position if tiers disabled) ---
                settings_sig = (
                    float(self.trailing_gap_pct),
                    float(self.pm_start_pct_no_dca),
                    float(self.pm_start_pct_with_dca),
                )

                state = self.trailing_pm.get(symbol)
                if (state is None) or (state.get("settings_sig") != settings_sig):
                    state = {
                        "active": False,
                        "line": base_pm_line,
                        "peak": 0.0,
                        "was_above": False,
                        "settings_sig": settings_sig,
                    }
                    self.trailing_pm[symbol] = state
                else:
                    state["settings_sig"] = settings_sig
                    if not state.get("active", False):
                        state["line"] = base_pm_line
                    else:
                        if state.get("line", 0.0) < base_pm_line:
                            state["line"] = base_pm_line

                above_now = current_sell_price >= state["line"]

                if (not state["active"]) and above_now:
                    state["active"] = True
                    state["peak"] = current_sell_price

                if state["active"]:
                    if current_sell_price > state["peak"]:
                        state["peak"] = current_sell_price

                    new_line = state["peak"] * (1.0 - trail_gap)
                    if new_line < base_pm_line:
                        new_line = base_pm_line
                    if new_line > state["line"]:
                        state["line"] = new_line

                    if state["was_above"] and (current_sell_price < state["line"]):
                        print(
                            f"  Trailing PM hit for {symbol}. "
                            f"Sell price {current_sell_price:.8f} fell below trailing line {state['line']:.8f}."
                        )
                        response = self.place_sell_order(
                            str(uuid.uuid4()),
                            "sell",
                            "market",
                            full_symbol,
                            quantity,
                            expected_price=current_sell_price,
                            avg_cost_basis=avg_cost_basis,
                            pnl_pct=gain_loss_percentage_sell,
                            tag="TRAIL_SELL",
                        )

                        if response and isinstance(response, dict) and "errors" not in response:
                            trades_made = True
                            self.trailing_pm.pop(symbol, None)
                            self.tiered_profits.pop(symbol, None)

                            # Trade ended -> reset rolling 24h DCA window for this coin
                            self._reset_dca_window_for_trade(symbol, sold=True)

                            print(f"  Successfully sold {quantity} {symbol}.")
                            time.sleep(5)
                            holdings = self.get_holdings()
                            continue

                # Save this tick's position relative to the line (needed for "above -> below" detection)
                state["was_above"] = above_now



            # DCA (NEURAL or hardcoded %, whichever hits first for the current stage)
            # Trade starts at neural level 3 => trader is at stage 0.
            # Neural-driven DCA stages (max 6 with 9 timeframes):
            #   stage 0 => neural 4 OR -2.5%
            #   stage 1 => neural 5 OR -5.0%
            #   stage 2 => neural 6 OR -10.0%
            #   stage 3 => neural 7 OR -20.0%
            #   stage 4 => neural 8 OR -30.0%
            #   stage 5 => neural 9 OR -40.0%
            # After that: hardcoded only (-50, then repeat -50 forever).
            current_stage = len(self.dca_levels_triggered.get(symbol, []))

            # Hardcoded loss % for this stage (repeat last level after list ends)
            hard_level = self.dca_levels[current_stage] if current_stage < len(self.dca_levels) else self.dca_levels[-1]
            hard_hit = gain_loss_percentage_buy <= hard_level

            # Neural trigger for DCA stages (dynamic based on timeframe count)
            neural_level_needed = None
            neural_level_now = None
            neural_hit = False
            _dca_start_level = max(1, min(int(TRADE_START_LEVEL or 3), 9))
            _dca_neural_max = max(0, 9 - _dca_start_level)
            if current_stage < _dca_neural_max:
                neural_level_needed = _dca_start_level + 1 + current_stage
                neural_level_now = self._read_long_dca_signal(symbol)

                # Keep it sane: don't DCA from neural if we're not even below cost basis.
                neural_hit = (gain_loss_percentage_buy < 0) and (neural_level_now >= neural_level_needed)

            # Small account mode: require neural confirmation for DCA
            require_neural = getattr(self, 'require_neural_dca_confirmation', False)
            
            if require_neural and hard_hit and not neural_hit and current_stage < len(self.dca_levels):
                # Loss threshold hit but neural not confirming - skip DCA
                print(
                    f"  [WARNING] DCA stage {current_stage + 1} loss threshold {hard_level:.1f}% hit, "
                    f"but neural L{neural_level_now or 0} < required L{neural_level_needed}. "
                    f"Skipping DCA - waiting for neural confirmation (small account mode)."
                )
            elif hard_hit or neural_hit:
                if neural_hit and hard_hit:
                    reason = f"NEURAL L{neural_level_now}>=L{neural_level_needed} OR HARD {hard_level:.2f}%"
                elif neural_hit:
                    reason = f"NEURAL L{neural_level_now}>=L{neural_level_needed}"
                else:
                    reason = f"HARD {hard_level:.2f}%"

                print(f"  DCAing {symbol} (stage {current_stage + 1}) via {reason}.")

                print(f"  Current Value: ${value:.2f}")
                
                # Use DCA multiplier from settings (could be 1.0 for linear, 2.0 for exponential)
                dca_multiplier = getattr(self, 'dca_multiplier', float(DCA_MULTIPLIER or 2.0))
                dca_amount = value * dca_multiplier
                
                print(f"  DCA Amount: ${dca_amount:.2f} ({dca_multiplier:.1f}x position value)")
                print(f"  Buying Power: ${buying_power:.2f}")
                
                # Check recent DCA count for this symbol
                recent_dca = self._dca_window_count(symbol)
                
                # Check position limits before DCA
                if not self._check_position_limits(symbol, dca_amount):
                    pass  # Already printed warning in check method
                elif recent_dca >= int(getattr(self, "max_dca_buys_per_24h", 2)):
                    print(
                        f"  Skipping DCA for {symbol}. "
                        f"Already placed {recent_dca} DCA buys in the last 24h (max {self.max_dca_buys_per_24h})."
                    )

                elif dca_amount <= buying_power:
                    response = self.place_buy_order(
                        str(uuid.uuid4()),
                        "buy",
                        "market",
                        full_symbol,
                        dca_amount,
                        avg_cost_basis=avg_cost_basis,
                        pnl_pct=gain_loss_percentage_buy,
                        tag="DCA",
                    )

                    print(f"  Buy Response: {response}")
                    if response and "errors" not in response:
                        # record that we completed THIS stage (no matter what triggered it)
                        self.dca_levels_triggered.setdefault(symbol, []).append(current_stage)

                        # Only record a DCA buy timestamp on success (so skips never advance anything)
                        self._note_dca_buy(symbol)

                        # DCA changes avg_cost_basis, so the PM line and tier state must be rebuilt.
                        # (this will re-init to 5% if DCA=0, or 2.5% if DCA>=1)
                        self.trailing_pm.pop(symbol, None)
                        self.tiered_profits.pop(symbol, None)

                        trades_made = True
                        print(f"  Successfully placed DCA buy order for {symbol}.")
                    else:
                        print(f"  Failed to place DCA buy order for {symbol}.")

                else:
                    print(f"  Skipping DCA for {symbol}. Not enough funds.")

            else:
                pass


        # --- ensure GUI gets bid/ask lines even for coins not currently held ---
        try:
            for sym in crypto_symbols:
                if sym in positions:
                    continue

                full_symbol = f"{sym}-USD"
                if full_symbol not in valid_symbols or sym == "USDC":
                    continue

                current_buy_price = current_buy_prices.get(full_symbol, 0.0)
                current_sell_price = current_sell_prices.get(full_symbol, 0.0)

                # keep the per-coin current price file behavior for consistency
                try:
                    file = open(sym + '_current_price.txt', 'w+')
                    file.write(str(current_buy_price))
                    file.close()
                except Exception:
                    pass

                positions[sym] = {
                    "quantity": 0.0,
                    "avg_cost_basis": 0.0,
                    "current_buy_price": current_buy_price,
                    "current_sell_price": current_sell_price,
                    "gain_loss_pct_buy": 0.0,
                    "gain_loss_pct_sell": 0.0,
                    "value_usd": 0.0,
                    "dca_triggered_stages": int(len(self.dca_levels_triggered.get(sym, []))),
                    "next_dca_display": "",
                    "dca_line_price": 0.0,
                    "dca_line_source": "N/A",
                    "dca_line_pct": 0.0,
                    "trail_active": False,
                    "trail_line": 0.0,
                    "trail_peak": 0.0,
                    "dist_to_trail_pct": 0.0,
                }
        except Exception:
            pass

        if not trading_pairs:
            return



        # Position sizing - use instance variable if set by account tier, otherwise global
        # NOTE: start_allocation_pct is ALREADY a percentage (e.g., 10.0 means 10%)
        # The global START_ALLOC_PCT might be stored as 0.005 (old format) or 10.0 (new format)
        # Instance variable is always set correctly by _apply_account_tier_settings
        if hasattr(self, 'start_allocation_pct'):
            alloc_pct = float(self.start_allocation_pct)
        else:
            alloc_pct = float(START_ALLOC_PCT or 0.005)
        
        allocation_in_usd = total_account_value * (alloc_pct / 100.0)
        
        # Minimum allocation safety
        if allocation_in_usd < 0.5:
            allocation_in_usd = 0.5
        
        # Debug output (no emojis for Windows compatibility)
        print(f"\n[ALLOCATION] Position Sizing: {alloc_pct:.3f}% of ${total_account_value:.2f} = ${allocation_in_usd:.2f}")
        if allocation_in_usd == 0.5:
            print(f"   (Minimum $0.50 enforced)")


        holding_full_symbols = [f"{h['asset_code']}-USD" for h in holdings.get("results", [])]
        
        # Check max positions limit for new entries
        max_positions = getattr(self, 'max_positions', 999)
        current_positions = len(holdings.get("results", []))

        start_index = 0
        while start_index < len(crypto_symbols):
            base_symbol = crypto_symbols[start_index].upper().strip()
            full_symbol = f"{base_symbol}-USD"

            # Skip if already held
            if full_symbol in holding_full_symbols:
                start_index += 1
                continue
            
            # Skip if at max positions limit
            if current_positions >= max_positions:
                # Don't spam this message for every coin
                if start_index == 0:
                    print(f"  [WARNING] Max positions ({max_positions}) reached. No new entries allowed.")
                start_index += 1
                continue

            # Neural signals are used as a "permission to start" gate.
            buy_count = self._read_long_dca_signal(base_symbol)
            sell_count = self._read_short_dca_signal(base_symbol)

            start_level = max(1, min(int(TRADE_START_LEVEL or 3), 9))

            # Default behavior: long must be >= start_level and short must be 0
            if not (buy_count >= start_level and sell_count == 0):
                start_index += 1
                continue
            
            # Check position limits (reserve requirement, etc)
            if not self._check_position_limits(base_symbol, allocation_in_usd):
                start_index += 1
                continue





            response = self.place_buy_order(
                str(uuid.uuid4()),
                "buy",
                "market",
                full_symbol,
                allocation_in_usd,
            )

            if response and "errors" not in response:
                trades_made = True
                # Do NOT pre-trigger any DCA levels. Hardcoded DCA will mark levels only when it hits your loss thresholds.
                self.dca_levels_triggered[base_symbol] = []

                # Fresh trade -> clear any rolling 24h DCA window for this coin
                self._reset_dca_window_for_trade(base_symbol, sold=False)

                # Reset trailing PM state for this coin (fresh trade, fresh trailing logic)
                self.trailing_pm.pop(base_symbol, None)


                print(
                    f"Starting new trade for {full_symbol} (AI start signal long={buy_count}, short={sell_count}). "
                    f"Allocating ${allocation_in_usd:.2f}."
                )
                time.sleep(5)
                holdings = self.get_holdings()
                holding_full_symbols = [f"{h['asset_code']}-USD" for h in holdings.get("results", [])]


            start_index += 1

        # If any trades were made, recalculate the cost basis
        if trades_made:
            time.sleep(5)
            print("Trades were made in this iteration. Recalculating cost basis...")
            new_cost_basis = self.calculate_cost_basis()
            if new_cost_basis:
                self.cost_basis = new_cost_basis
                print("Cost basis recalculated successfully.")
            else:
                print("Failed to recalculcate cost basis.")
            self.initialize_dca_levels()

        # --- GUI HUB STATUS WRITE ---
        try:
            status = {
                "timestamp": time.time(),
                "account": {
                    "total_account_value": total_account_value,
                    "buying_power": buying_power,
                    "holdings_sell_value": holdings_sell_value,
                    "holdings_buy_value": holdings_buy_value,
                    "percent_in_trade": in_use,
                    # trailing PM config (matches what's printed above current trades)
                    "pm_start_pct_no_dca": float(getattr(self, "pm_start_pct_no_dca", 0.0)),
                    "pm_start_pct_with_dca": float(getattr(self, "pm_start_pct_with_dca", 0.0)),
                    "trailing_gap_pct": float(getattr(self, "trailing_gap_pct", 0.0)),
                },
                "positions": positions,
            }
            self._append_jsonl(
                ACCOUNT_VALUE_HISTORY_PATH,
                {"ts": status["timestamp"], "total_account_value": total_account_value},
            )
            self._write_trader_status(status)
        except Exception:
            pass


    # ------------------------------------------------------------------
    # IRS Form 8949 CSV Export
    # ------------------------------------------------------------------
    def export_8949_csv(self, year: Optional[int] = None, output_path: Optional[str] = None) -> Optional[str]:
        """
        Reads trade_history.jsonl and writes a CSV with the columns required by
        IRS Form 8949:

            (a) Description of property
            (b) Date acquired
            (c) Date sold or disposed of
            (d) Proceeds (sales price)
            (e) Cost or other basis
            (f) Code
            (g) Amount of adjustment
            (h) Gain or (loss)

        Only SELL trades are tax-reportable dispositions. Each sell is paired with
        its cost basis from the trade record. The CSV is written to hub_data/ by
        default and the path is returned.

        Args:
            year: Tax year to filter (e.g. 2026). None = all trades.
            output_path: Override output file path. None = hub_data/form_8949_trades.csv
                         (or form_8949_trades_YYYY.csv when year is specified).

        Returns:
            The path of the written CSV, or None on error.
        """
        try:
            if not os.path.isfile(TRADE_HISTORY_PATH):
                print("[8949 EXPORT] No trade history file found.")
                return None

            # Determine output path
            if output_path is None:
                if year is not None:
                    fname = f"form_8949_trades_{int(year)}.csv"
                else:
                    fname = "form_8949_trades.csv"
                output_path = os.path.join(HUB_DATA_DIR, fname)

            # Read all trades
            trades: List[dict] = []
            with open(TRADE_HISTORY_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    line = (line or "").strip()
                    if not line:
                        continue
                    try:
                        trades.append(json.loads(line))
                    except Exception:
                        continue

            if not trades:
                print("[8949 EXPORT] Trade history is empty.")
                return None

            # Build a map of buy-side records keyed by symbol so we can look up
            # the acquisition date for each sell. For positions built through
            # multiple DCA buys, we use the EARLIEST buy timestamp as the
            # acquisition date (matching FIFO / specific-identification intent).
            # The map resets when a sell fully closes a position.
            buy_dates: Dict[str, float] = {}   # symbol -> earliest buy ts for current position
            buy_costs: Dict[str, Decimal] = {} # symbol -> accumulated cost for current position
            buy_qtys: Dict[str, Decimal] = {}  # symbol -> accumulated qty for current position

            rows_8949: List[dict] = []

            for t in trades:
                try:
                    side = str(t.get("side", "")).lower().strip()
                    symbol_raw = str(t.get("symbol", "")).upper().strip()
                    base = symbol_raw.split("-")[0].strip()
                    ts = float(t.get("ts", 0.0) or 0.0)

                    if not base or ts <= 0.0:
                        continue

                    qty_d = Decimal(str(t.get("qty", 0) or 0))
                    price_raw = t.get("price", None)
                    price_d = Decimal(str(price_raw)) if price_raw is not None else Decimal("0")
                    fees_raw = t.get("fees_usd", None)
                    fees_d = Decimal(str(fees_raw)) if fees_raw is not None else Decimal("0")

                    if side == "buy":
                        # Track earliest buy date for current open position
                        if base not in buy_dates or buy_qtys.get(base, Decimal("0")) <= 0:
                            buy_dates[base] = ts
                            buy_costs[base] = Decimal("0")
                            buy_qtys[base] = Decimal("0")

                        # Use buying_power_delta for exact cost when available
                        bp_delta = t.get("buying_power_delta", None)
                        if bp_delta is not None:
                            cost_this_buy = abs(Decimal(str(bp_delta)))
                        else:
                            cost_this_buy = (qty_d * price_d) + fees_d

                        buy_costs[base] = buy_costs.get(base, Decimal("0")) + cost_this_buy
                        buy_qtys[base] = buy_qtys.get(base, Decimal("0")) + qty_d

                    elif side == "sell":
                        # Year filter
                        sell_dt = datetime.datetime.fromtimestamp(ts)
                        if year is not None and sell_dt.year != int(year):
                            # Still update position tracking even if we skip the row
                            sell_frac = Decimal("1")
                            if buy_qtys.get(base, Decimal("0")) > 0 and qty_d > 0:
                                sell_frac = min(Decimal("1"), qty_d / buy_qtys[base])
                            cost_allocated = (buy_costs.get(base, Decimal("0")) * sell_frac).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                            buy_costs[base] = buy_costs.get(base, Decimal("0")) - cost_allocated
                            buy_qtys[base] = buy_qtys.get(base, Decimal("0")) - qty_d
                            if buy_qtys.get(base, Decimal("0")) <= Decimal("0.000000001"):
                                buy_dates.pop(base, None)
                                buy_costs.pop(base, None)
                                buy_qtys.pop(base, None)
                            continue

                        # Calculate proceeds (what you received)
                        bp_delta_sell = t.get("buying_power_delta", None)
                        if bp_delta_sell is not None:
                            proceeds_d = Decimal(str(bp_delta_sell)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                        else:
                            proceeds_d = ((qty_d * price_d) - fees_d).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

                        # Calculate cost basis (pro-rata from accumulated buys)
                        sell_frac = Decimal("1")
                        if buy_qtys.get(base, Decimal("0")) > 0 and qty_d > 0:
                            sell_frac = min(Decimal("1"), qty_d / buy_qtys[base])

                        cost_basis_d = (buy_costs.get(base, Decimal("0")) * sell_frac).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

                        # Gain or loss
                        gain_loss_d = (proceeds_d - cost_basis_d).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

                        # Dates
                        acquired_dt = datetime.datetime.fromtimestamp(buy_dates.get(base, ts))
                        sold_dt = sell_dt

                        # Description - e.g. "0.00234500 BTC (Robinhood Crypto)"
                        qty_str = f"{float(qty_d):.8f}".rstrip("0").rstrip(".")
                        description = f"{qty_str} {base} (Robinhood Crypto)"

                        rows_8949.append({
                            "description": description,
                            "date_acquired": acquired_dt.strftime("%m/%d/%Y"),
                            "date_sold": sold_dt.strftime("%m/%d/%Y"),
                            "proceeds": f"{float(proceeds_d):.2f}",
                            "cost_basis": f"{float(cost_basis_d):.2f}",
                            "code": "",
                            "adjustment": "",
                            "gain_loss": f"{float(gain_loss_d):.2f}",
                            "hold_period": "Short" if (sold_dt - acquired_dt).days <= 365 else "Long",
                            "symbol": base,
                            "tag": str(t.get("tag", "") or ""),
                            "order_id": str(t.get("order_id", "") or ""),
                        })

                        # Update position tracking
                        buy_costs[base] = buy_costs.get(base, Decimal("0")) - cost_basis_d
                        buy_qtys[base] = buy_qtys.get(base, Decimal("0")) - qty_d
                        if buy_qtys.get(base, Decimal("0")) <= Decimal("0.000000001"):
                            buy_dates.pop(base, None)
                            buy_costs.pop(base, None)
                            buy_qtys.pop(base, None)

                except Exception:
                    continue

            if not rows_8949:
                print(f"[8949 EXPORT] No sell trades found{f' for {year}' if year else ''}.")
                return None

            # Write CSV
            fieldnames = [
                "description",
                "date_acquired",
                "date_sold",
                "proceeds",
                "cost_basis",
                "code",
                "adjustment",
                "gain_loss",
                "hold_period",
                "symbol",
                "tag",
                "order_id",
            ]

            with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                # Write header row with 8949 column labels
                writer.writerow({
                    "description": "(a) Description of property",
                    "date_acquired": "(b) Date acquired",
                    "date_sold": "(c) Date sold",
                    "proceeds": "(d) Proceeds",
                    "cost_basis": "(e) Cost or other basis",
                    "code": "(f) Code",
                    "adjustment": "(g) Adjustment",
                    "gain_loss": "(h) Gain or (loss)",
                    "hold_period": "Hold Period",
                    "symbol": "Symbol",
                    "tag": "Trade Tag",
                    "order_id": "Order ID",
                })

                # Write totals row
                total_proceeds = sum(Decimal(r["proceeds"]) for r in rows_8949)
                total_cost = sum(Decimal(r["cost_basis"]) for r in rows_8949)
                total_gain = sum(Decimal(r["gain_loss"]) for r in rows_8949)

                for row in rows_8949:
                    writer.writerow(row)

                writer.writerow({})  # blank separator
                writer.writerow({
                    "description": "TOTALS",
                    "date_acquired": "",
                    "date_sold": "",
                    "proceeds": f"{float(total_proceeds):.2f}",
                    "cost_basis": f"{float(total_cost):.2f}",
                    "code": "",
                    "adjustment": "",
                    "gain_loss": f"{float(total_gain):.2f}",
                    "hold_period": "",
                    "symbol": "",
                    "tag": "",
                    "order_id": "",
                })

            count = len(rows_8949)
            year_str = f" for tax year {year}" if year else ""
            print(f"[8949 EXPORT] Wrote {count} sell transactions{year_str} to: {output_path}")
            print(f"[8949 EXPORT] Total Proceeds: ${float(total_proceeds):.2f}  |  Total Cost Basis: ${float(total_cost):.2f}  |  Net Gain/Loss: ${float(total_gain):.2f}")
            return output_path

        except Exception:
            print(f"[8949 EXPORT] Error exporting CSV: {traceback.format_exc()}")
            return None


    def run(self):
        while True:
            try:
                self.manage_trades()
                time.sleep(0.5)
            except Exception as e:
                print(traceback.format_exc())

if __name__ == "__main__":
    trading_bot = CryptoAPITrading()
    trading_bot.run()
