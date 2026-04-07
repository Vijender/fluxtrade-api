TICKER_RULES = {
    "DEFAULT": {
        "weeks_out": [2, 3, 4, 5],
        "allowed_widths": [5],

        # --- STRATEGY SPECIFIC OTM ---
        "min_otm_spread": 7.0,   # Buffer: Must be at least this far away to sell
        "max_otm_long": 5.0,     # Hurdle: Must be closer than this to buy

        "max_risk_reward": 3.0,
        "min_iv_rank_spread": 25, # Sell high IV
        "max_iv_rank_long": 20,   # Buy low IV
        "max_bid_ask_pct": 6.0,
        "min_liquidity_score": 4.0,
        "min_days_to_earnings": 7,

        "decision_thresholds": {
            "trade": 7.5,
            "watch": 6.5
        }
    },
    "NVDA": {
        "weeks_out": [1, 2, 3],
        "allowed_widths": [5, 10],
        "min_otm_spread": 10.0,  # NVDA swings 5% in a day; give it 10% buffer
        "max_otm_long": 3.5,    # Don't buy NVDA puts/calls more than 3.5% out
        "decision_thresholds": {"trade": 6.0, "watch": 5.0}
    },
    "MU": {
        "min_otm_spread": 9.0,
        "max_otm_long": 4.0,
        "decision_thresholds": {"trade": 7.0, "watch": 6.0}
    },
    "TSLA": {
        "weeks_out": [2, 3],
        "min_otm_spread": 12.0,  # High Beta: Needs massive buffer
        "max_otm_long": 5.0,
        "decision_thresholds": {"trade": 7.0, "watch": 6.0}
    },
    "SPY": {
        "min_otm_spread": 4.0,   # Low Beta: 4% is very safe
        "max_otm_long": 2.5,    # SPY moves slow; 2.5% is a realistic target
        "max_risk_reward": 2.5,
        "decision_thresholds": {"trade": 7.5, "watch": 6.5}
    },
    "SNDK": {
        "min_otm_spread": 8.0,
        "max_otm_long": 4.5,
        "min_iv_rank_spread": 35, # Only sell SNDK if IV is actually juiced
        "decision_thresholds": {"trade": 7.0, "watch": 6.0}
    }
}

PRESELECTED_TICKERS = {"AMD","MU","NVDA","SNDK","WDC", "SPY", "QQQ", "META", "AAPL", "TSLA"}
thresholds = {
    "AGGRESSIVE": 35,  # Sell more often, even if premium isn't at peak
    "BALANCED": 45,    # The standard "middle ground"
    "DEFENSIVE": 55    # Only sell when fear is at extreme levels (Best for War)
}

MODE_CONFIG = {
    "DEFENSIVE": {
        "iv_high": 50,
        "iv_low": 20,
        "credit_bias": True,
        "target_delta": 0.15,
        "spread_width": 5,
        "min_score_trade": 7.5
    },
    "BALANCED": {
        "iv_high": 45,
        "iv_low": 18,
        "credit_bias": False,
        "target_delta": 0.20,
        "spread_width": 7,
        "min_score_trade": 7.0
    },
    "AGGRESSIVE": {
        "iv_high": 40,
        "iv_low": 15,
        "credit_bias": False,
        "target_delta": 0.30,
        "spread_width": 10,
        "min_score_trade": 6.5
    }
}