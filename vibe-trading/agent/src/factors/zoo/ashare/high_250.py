# ============================================================
# 中文名称: 250日(年线)新高突破因子 (HIGH_250)
# 简要说明: 突破过去250个交易日（约1年）最高价的经典动量突破。
# 典型用途: 捕捉A股年度强动量与牛股右侧突破。
# ============================================================
"""Ashare 250-day (Annual) High Breakout Momentum Factor."""
from __future__ import annotations

import pandas as pd

from src.factors.base import safe_div, ts_max, zscore

__alpha_meta__ = {
    'id': 'ashare_high_250',
    'nickname': 'Ashare 250-day (annual) high breakout momentum',
    'theme': ['momentum'],
    'formula_latex': r'\mathrm{zscore}\Bigl(\frac{\mathrm{close}_t - \mathrm{ts\_max}(\mathrm{high}_{t-1},\,250)}{\mathrm{ts\_max}(\mathrm{high}_{t-1},\,250)}\Bigr)',
    'columns_required': ['high', 'close'],
    'universe': ['equity_cn', 'equity_hk', 'equity_us'],
    'frequency': ['1d'],
    'decay_horizon': 60,
    'min_warmup_bars': 250,
    'notes': (
        'Ashare 250-day (annual) high breakout momentum. Measures price positioning and breakout ratio '
        'relative to the trailing 250-day high (excluding current bar, strictly lookahead-free).'
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Compute 250-day high breakout score."""
    high_df = panel['high']
    close_df = panel['close']

    # 严格取 T-1 前序 250 日最高价
    prior_max_250 = ts_max(high_df.shift(1), 250)
    score = safe_div(close_df - prior_max_250, prior_max_250)

    return zscore(score)
