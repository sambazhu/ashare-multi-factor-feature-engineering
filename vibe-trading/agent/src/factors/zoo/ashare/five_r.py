# ============================================================
# 中文名称: 五连红启动因子 (5R)
# 简要说明: 连续5日收出阳线且第6日为阴线，捕捉短线多头启动点。
# 典型用途: 短线动量突破与多头转折信号。
# ============================================================
"""Ashare 5-Consecutive-Red Momentum Factor: 5 consecutive positive candles."""
from __future__ import annotations

import pandas as pd

from src.factors.base import safe_div, ts_mean, zscore

__alpha_meta__ = {
    'id': 'ashare_5r',
    'nickname': 'Ashare 5-consecutive-red momentum starter',
    'theme': ['momentum'],
    'formula_latex': r'\mathrm{zscore}\Bigl(\sum_{k=0}^4 \frac{\mathrm{close}_{t-k} - \mathrm{open}_{t-k}}{\mathrm{open}_{t-k}} \times \mathbb{I}(\mathrm{close}_{t-5} \le \mathrm{open}_{t-5})\Bigr)',
    'columns_required': ['open', 'close'],
    'universe': ['equity_cn', 'equity_hk', 'equity_us'],
    'frequency': ['1d'],
    'decay_horizon': 10,
    'min_warmup_bars': 10,
    'notes': (
        'A-share 5-consecutive-red breakout momentum. Detects initiation of multi-day '
        'buying pressure where past 5 bars close higher than open, preceded by a non-red bar at t-5.'
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Compute 5-consecutive-red candle momentum score."""
    open_df = panel['open']
    close_df = panel['close']

    # 每天实体涨幅
    body_ret = safe_div(close_df - open_df, open_df)
    is_red = (close_df > open_df).astype(float)

    red_0 = is_red
    red_1 = is_red.shift(1)
    red_2 = is_red.shift(2)
    red_3 = is_red.shift(3)
    red_4 = is_red.shift(4)
    red_count_5 = (red_0 + red_1 + red_2 + red_3 + red_4) / 5.0

    # 前一日 (t-5) 发生阴线/平盘转折
    is_prev_non_red = (close_df.shift(5) <= open_df.shift(5)).astype(float)

    # 累计实体阳线动量强度
    sum_body_5 = (body_ret + body_ret.shift(1) + body_ret.shift(2) + body_ret.shift(3) + body_ret.shift(4))

    score = red_count_5 * sum_body_5 + (1.5 * is_prev_non_red * (red_count_5 == 1.0).astype(float))
    return zscore(score)
