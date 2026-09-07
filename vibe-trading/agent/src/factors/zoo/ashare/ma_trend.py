# ============================================================
# 中文名称: 均线多头排列趋势强度因子 (MA_TREND)
# 简要说明: 短中长期均线(5/10/20/60)完全呈多头顺向排列且均线斜率向上。
# 典型用途: 主升浪趋势跟踪与动量加速策略。
# ============================================================
"""Ashare Moving Average Alignment Trend Strength Factor."""
from __future__ import annotations

import pandas as pd

from src.factors.base import safe_div, ts_mean, zscore

__alpha_meta__ = {
    'id': 'ashare_ma_trend',
    'nickname': 'Ashare multi-MA bullish alignment trend strength',
    'theme': ['momentum'],
    'formula_latex': r'\mathrm{zscore}\Bigl(\frac{\mathrm{MA}_5 - \mathrm{MA}_{10}}{\mathrm{MA}_{10}} + \frac{\mathrm{MA}_{10} - \mathrm{MA}_{20}}{\mathrm{MA}_{20}} + \frac{\mathrm{MA}_{20} - \mathrm{MA}_{60}}{\mathrm{MA}_{60}} + 10 \times \mathrm{slope}_{60}\Bigr)',
    'columns_required': ['close'],
    'universe': ['equity_cn', 'equity_hk', 'equity_us'],
    'frequency': ['1d'],
    'decay_horizon': 30,
    'min_warmup_bars': 60,
    'notes': (
        'Ashare moving average bullish sequence strength. Combines tier spreads '
        'between MA5, MA10, MA20, MA60 along with 60-day moving average upward slope.'
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Compute multi-MA alignment trend score."""
    close_df = panel['close']

    ma5 = ts_mean(close_df, 5)
    ma10 = ts_mean(close_df, 10)
    ma20 = ts_mean(close_df, 20)
    ma60 = ts_mean(close_df, 60)

    # 各层级均线顺向阶差
    spread_5_10 = safe_div(ma5 - ma10, ma10)
    spread_10_20 = safe_div(ma10 - ma20, ma20)
    spread_20_60 = safe_div(ma20 - ma60, ma60)

    # 60 日长均线斜率
    ma60_prev5 = ma60.shift(5)
    slope_60 = safe_div(ma60 - ma60_prev5, ma60_prev5 * 5.0)

    # 综合多头排列度与斜率
    score = spread_5_10 + spread_10_20 + spread_20_60 + 10.0 * slope_60
    return zscore(score)
