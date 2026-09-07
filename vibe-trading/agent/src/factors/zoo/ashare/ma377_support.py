# ============================================================
# 中文名称: MA377 斐波那契支撑因子 (MA377_SUPPORT)
# 简要说明: 股价回踩至377日长周期斐波那契均线获得牛熊分界大支撑。
# 典型用途: 超长周期底部价值投资与回踩低吸。
# ============================================================
"""Ashare 377-day Fibonacci Moving Average Support Factor."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import safe_div, ts_mean, zscore

__alpha_meta__ = {
    'id': 'ashare_ma377_support',
    'nickname': 'Ashare MA377 Fibonacci long-term support',
    'theme': ['reversal'],
    'formula_latex': r'\mathrm{zscore}\Bigl(\exp\bigl(-\frac{(\mathrm{close} - \mathrm{MA}_{377})^2}{2\sigma^2}\bigr)\Bigr)',
    'columns_required': ['close'],
    'universe': ['equity_cn', 'equity_hk', 'equity_us'],
    'frequency': ['1d'],
    'decay_horizon': 30,
    'min_warmup_bars': 377,
    'notes': (
        'Ashare 377-day Fibonacci moving average support. Gaussian proximity score '
        'to the 377-day long-term baseline anchor.'
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Compute MA377 Fibonacci support proximity score."""
    close_df = panel['close']

    ma377 = ts_mean(close_df, 377)
    dist_pct = safe_div(close_df - ma377, ma377)

    sigma = 0.04
    support_density = np.exp(- np.square(dist_pct) / (2.0 * sigma * sigma))

    return zscore(support_density)
