# ============================================================
# 中文名称: 创历史/全周期新高突破因子 (HIGH_ALL)
# 简要说明: 突破覆盖期内所有历史前序交易日最高价，无上方套牢盘阻力。
# 典型用途: 最强动量龙头股主升浪突破策略。
# ============================================================
"""Ashare All-Time High Breakout Momentum Factor."""
from __future__ import annotations

import pandas as pd

from src.factors.base import safe_div, zscore

__alpha_meta__ = {
    'id': 'ashare_high_all',
    'nickname': 'Ashare all-time high breakout momentum',
    'theme': ['momentum'],
    'formula_latex': r'\mathrm{zscore}\Bigl(\frac{\mathrm{close}_t - \mathrm{cummax}(\mathrm{high}_{t-1})}{\mathrm{cummax}(\mathrm{high}_{t-1})}\Bigr)',
    'columns_required': ['high', 'close'],
    'universe': ['equity_cn', 'equity_hk', 'equity_us'],
    'frequency': ['1d'],
    'decay_horizon': 60,
    'min_warmup_bars': 60,
    'notes': (
        'Ashare All-Time High breakout indicator. Measures the distance and breakthrough ratio '
        'of the current close relative to all prior historical high prices. Zero overhead resistance.'
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Compute All-Time High breakout score."""
    high_df = panel['high']
    close_df = panel['close']

    # 严格取 T-1 前序历史最高价 (无未来函数)
    prior_all_high = high_df.shift(1).cummax()
    breakout_ratio = safe_div(close_df - prior_all_high, prior_all_high)

    return zscore(breakout_ratio)
