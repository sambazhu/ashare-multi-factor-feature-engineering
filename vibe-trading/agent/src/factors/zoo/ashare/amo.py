# ============================================================
# 中文名称: 成交额异动放量因子 (AMO)
# 简要说明: 单日成交额相对前15日均量及前15日最高成交额急剧放量。
# 典型用途: 捕捉短线资金剧烈博弈与突破放量。
# ============================================================
"""Ashare Turnover Volume Surge Factor (AMO)."""
from __future__ import annotations

import pandas as pd

from src.factors.base import safe_div, ts_max, ts_mean, zscore

__alpha_meta__ = {
    'id': 'ashare_amo',
    'nickname': 'Ashare turnover surge breakout momentum',
    'theme': ['volume', 'momentum'],
    'formula_latex': r'\mathrm{zscore}\Bigl(0.6 \times \frac{\mathrm{amount}_t}{\mathrm{ts\_mean}(\mathrm{amount}_{t-1},\,15)} + 0.4 \times \frac{\mathrm{amount}_t}{\mathrm{ts\_max}(\mathrm{amount}_{t-1},\,15)}\Bigr)',
    'columns_required': ['amount'],
    'universe': ['equity_cn', 'equity_hk', 'equity_us'],
    'frequency': ['1d'],
    'decay_horizon': 10,
    'min_warmup_bars': 15,
    'notes': (
        'Ashare volume expansion anomaly. Combines turnover multiple over trailing 15-day average '
        'and breakthrough ratio over trailing 15-day peak turnover.'
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Compute volume surge composite score."""
    amount_df = panel['amount']

    prior_mean_15 = ts_mean(amount_df.shift(1), 15)
    prior_max_15 = ts_max(amount_df.shift(1), 15)

    spike_mean = safe_div(amount_df, prior_mean_15)
    spike_max = safe_div(amount_df, prior_max_15)

    score = 0.6 * spike_mean + 0.4 * spike_max
    return zscore(score)
