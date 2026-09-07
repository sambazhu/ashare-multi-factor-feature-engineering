# ============================================================
# 中文名称: 年线支撑与回踩因子 (MA250_SUPPORT)
# 简要说明: 股价回踩至250日年线附近获得强支撑并企稳回升。
# 典型用途: 中长线价值投资与趋势回调低吸买点。
# ============================================================
"""Ashare 250-day Moving Average Support & Rebound Factor."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import safe_div, ts_mean, zscore

__alpha_meta__ = {
    'id': 'ashare_ma250_support',
    'nickname': 'Ashare MA250 annual moving average support rebound',
    'theme': ['reversal', 'momentum'],
    'formula_latex': r'\mathrm{zscore}\Bigl(\exp\bigl(-\frac{(\mathrm{close} - \mathrm{MA}_{250})^2}{2\sigma^2}\bigr) \times \bigl(1 + \frac{\mathrm{close} - \mathrm{low}}{\mathrm{close}}\bigr)\Bigr)',
    'columns_required': ['close', 'low'],
    'universe': ['equity_cn', 'equity_hk', 'equity_us'],
    'frequency': ['1d'],
    'decay_horizon': 21,
    'min_warmup_bars': 250,
    'notes': (
        'Ashare 250-day moving average support. Gaussian proximity score to the 250-day trend line '
        'weighted by lower-shadow intraday rebound strength.'
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Compute MA250 support and rebound proximity score."""
    close_df = panel['close']
    low_df = panel['low']

    ma250 = ts_mean(close_df, 250)
    dist_pct = safe_div(close_df - ma250, ma250)

    # 高斯近邻支撑度 (距离年线越近，支撑得分越高，带宽 sigma = 0.03)
    sigma = 0.03
    support_density = np.exp(- np.square(dist_pct) / (2.0 * sigma * sigma))

    # 下影线探底回升强度
    lower_shadow_rebound = safe_div(close_df - low_df, close_df)

    score = support_density * (1.0 + lower_shadow_rebound)
    return zscore(score)
