"""The tracked market universe.

This is a *fixed* list, not user data. The whole point of the rebuild is that
the dashboard analyses the market rather than anyone's holdings, so what gets
tracked is a property of the application, not of a user.

Grouping matters for the analytics:
  * ``benchmark`` -- the reference series everything is measured against.
  * ``index``     -- broad market, used for regime and breadth.
  * ``sector``    -- the 11 GICS sector SPDRs, used for rotation.
  * ``crypto``    -- 24/7 risk appetite.
  * ``volatility``-- fear gauge; behaves inversely to everything else.
  * ``bond``/``commodity`` -- cross-asset context.
"""

from __future__ import annotations

from dataclasses import dataclass

BENCHMARK = "SPY"


@dataclass(frozen=True)
class Instrument:
    symbol: str
    name: str
    group: str
    # Sector ETFs get a short label for the rotation chart.
    short: str = ""

    @property
    def display(self) -> str:
        return self.short or self.symbol


UNIVERSE: list[Instrument] = [
    # --- broad market ----------------------------------------------------
    Instrument("SPY", "S&P 500", "index", "S&P 500"),
    Instrument("QQQ", "Nasdaq 100", "index", "Nasdaq"),
    Instrument("IWM", "Russell 2000 (small cap)", "index", "Small cap"),
    Instrument("DIA", "Dow Jones Industrial Average", "index", "Dow"),
    Instrument("EFA", "Developed markets ex-US", "index", "Intl dev"),
    Instrument("EEM", "Emerging markets", "index", "Emerging"),

    # --- sectors (SPDR select sector) ------------------------------------
    Instrument("XLK", "Technology", "sector", "Tech"),
    Instrument("XLF", "Financials", "sector", "Financials"),
    Instrument("XLV", "Health Care", "sector", "Health"),
    Instrument("XLY", "Consumer Discretionary", "sector", "Cons disc"),
    Instrument("XLP", "Consumer Staples", "sector", "Staples"),
    Instrument("XLE", "Energy", "sector", "Energy"),
    Instrument("XLI", "Industrials", "sector", "Industrials"),
    Instrument("XLB", "Materials", "sector", "Materials"),
    Instrument("XLU", "Utilities", "sector", "Utilities"),
    Instrument("XLRE", "Real Estate", "sector", "Real estate"),
    Instrument("XLC", "Communication Services", "sector", "Comms"),

    # --- cross-asset ------------------------------------------------------
    Instrument("TLT", "20+ Year Treasuries", "bond", "Long bonds"),
    Instrument("HYG", "High Yield Corporate Bonds", "bond", "High yield"),
    Instrument("GLD", "Gold", "commodity", "Gold"),
    Instrument("USO", "Crude Oil", "commodity", "Oil"),
    Instrument("UUP", "US Dollar Index", "commodity", "Dollar"),

    # --- crypto -----------------------------------------------------------
    Instrument("BTC-USD", "Bitcoin", "crypto", "Bitcoin"),
    Instrument("ETH-USD", "Ethereum", "crypto", "Ethereum"),
    Instrument("SOL-USD", "Solana", "crypto", "Solana"),

    # --- volatility -------------------------------------------------------
    # ^VIX is an index, not an ETF -- yfinance serves it, Alpaca does not.
    Instrument("^VIX", "CBOE Volatility Index", "volatility", "VIX"),
]

BY_SYMBOL: dict[str, Instrument] = {i.symbol: i for i in UNIVERSE}
SYMBOLS: list[str] = [i.symbol for i in UNIVERSE]

# Groups whose members are directly comparable on a returns basis. VIX is
# excluded from rotation/correlation ranking because it is a volatility index,
# not an investable total-return series -- ranking it alongside equities would
# be meaningless.
RANKABLE_GROUPS = {"index", "sector", "bond", "commodity", "crypto"}


def symbols_in(*groups: str) -> list[str]:
    return [i.symbol for i in UNIVERSE if i.group in groups]


def rankable_symbols() -> list[str]:
    return symbols_in(*RANKABLE_GROUPS)
