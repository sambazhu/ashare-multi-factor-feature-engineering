# ============================================================
# 中文名称: 500日新高突破因子 (HIGH_500)
# 简要说明: 突破过去500个交易日（约2年）最高价的中长周期趋势突破。
# 典型用途: 捕捉中长周期反转进入大级别多头主升浪。
# ============================================================
"""Ashare 500-day High Breakout Momentum Factor."""
from __future__ import annotations

import pandas as pd

from src.factors.base import safe_div, ts_max, zscore

__alpha_meta__ = {
    'id': 'ashare_high_500',
    'nickname': 'Ashare 500-day high breakout momentum',
    'theme': ['momentum'],
    'formula_latex': r'\mathrm{zscore}\Bigl(\frac{\mathrm{close}_t - \mathrm{ts\_max}(\mathrm{high}_{t-1},\,500)}{\mathrm{ts\_max}(\mathrm{high}_{t-1},\,500)}\Bigr)',
    'columns_required': ['high', 'close'],
    'universe': ['equity_cn', 'equity_hk', 'equity_us'],
    'frequency': ['1d'],
    'decay_horizon': 60,
    'min_warmup_bars': 500,
    'notes': (
        'Ashare 500-day high breakout momentum. Measures price positioning and breakout ratio '
        'relative to the rolling 500-day high (excluding current bar, lookahead-free).'
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Compute 500-day high breakout score."""
    high_df = panel['high']
    close_df = panel['close']

    # 严格取 T-1 前序 500 日最高价
    prior_max_500 = ts_max(high_df.shift(1), 500)
    score = safe_div(close_df - prior_max_500, prior_max_500)

    return zscore(score)
