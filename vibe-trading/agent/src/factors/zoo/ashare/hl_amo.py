# ============================================================
# 中文名称: 低位爆量异动因子 (HL_AMO)
# 简要说明: 股价处于相对低位时成交额急剧放大超前序均量1.8倍以上。
# 典型用途: 识别主力资金底部建仓与逆势吸筹信号。
# ============================================================
"""Ashare Low-Position Turnover Volume Spike Factor (HL_AMO)."""
from __future__ import annotations

import pandas as pd

from src.factors.base import safe_div, ts_mean, ts_rank, zscore

__alpha_meta__ = {
    'id': 'ashare_hl_amo',
    'nickname': 'Ashare low-position volume spike accumulator',
    'theme': ['volume', 'reversal'],
    'formula_latex': r'\mathrm{zscore}\Bigl(\bigl(1 - \mathrm{ts\_rank}(\mathrm{close},\,60)\bigr) \times \frac{\mathrm{amount}_t}{\mathrm{ts\_mean}(\mathrm{amount}_{t-1},\,15)}\Bigr)',
    'columns_required': ['close', 'amount'],
    'universe': ['equity_cn', 'equity_hk', 'equity_us'],
    'frequency': ['1d'],
    'decay_horizon': 21,
    'min_warmup_bars': 60,
    'notes': (
        'A-share low-position institutional turnover surge. Measures volume explosion '
        'ratio when stock price is located in the lower historical percentile of the last 60 days.'
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Compute low-position turnover surge score."""
    close_df = panel['close']
    amount_df = panel['amount']

    # 1. 价格相对低位度 (近 60 日分位数越低，低位得分越高)
    price_rank_60 = ts_rank(close_df, 60)
    low_pos_score = 1.0 - price_rank_60

    # 2. 前序 15 日成交额均值 (T-1 为止)
    prior_mean_amt_15 = ts_mean(amount_df.shift(1), 15)
    vol_spike_ratio = safe_div(amount_df, prior_mean_amt_15)

    # 3. 复合低位爆量得分
    score = low_pos_score * vol_spike_ratio
    return zscore(score)
