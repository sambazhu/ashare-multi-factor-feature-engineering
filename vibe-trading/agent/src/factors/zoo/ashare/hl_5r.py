# ============================================================
# 中文名称: 低位五连红反弹因子 (HL_5R)
# 简要说明: 经历长期深度回撤后在底部企稳并出现连续5日小碎步阳线反弹。
# 典型用途: 捕捉A股超跌反弹与底部蓄势起涨形态。
# ============================================================
"""Ashare HL+5R Reversal Factor: 5 consecutive red candles after deep 180-day pullback."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import safe_div, ts_max, ts_min, zscore

__alpha_meta__ = {
    'id': 'ashare_hl_5r',
    'nickname': 'Ashare low-position 5-consecutive-red reversal',
    'theme': ['reversal', 'momentum'],
    'formula_latex': r'\mathrm{zscore}\Bigl(\mathrm{dd}_{180} \times \frac{\sum_{k=0}^4 \mathbb{I}(\mathrm{close}_{t-k} > \mathrm{open}_{t-k})}{5} \times \bigl(1 - \mathrm{ret}_5\bigr)\Bigr)',
    'columns_required': ['open', 'high', 'low', 'close'],
    'universe': ['equity_cn', 'equity_hk', 'equity_us'],
    'frequency': ['1d'],
    'decay_horizon': 21,
    'min_warmup_bars': 180,
    'notes': (
        'A-share classic bottom accumulation pattern. Requires significant trailing 180-day '
        'drawdown (>25%), recent 10-day stabilization without premature surge, and 5 consecutive '
        'positive daily bars with moderate cumulative return (<13%).'
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Compute continuous low-position 5-red score."""
    open_df = panel['open']
    high_df = panel['high']
    low_df = panel['low']
    close_df = panel['close']

    # 1. 过去 180 天前序高点与近期低点计算回撤深度 (以 T-10 前序 170 天最高价为基准)
    prior_high_170 = ts_max(high_df.shift(10), 170)
    recent_low_10 = ts_min(low_df, 10)
    drawdown_180 = safe_div(prior_high_170 - recent_low_10, prior_high_170)

    # 2. 近 5 日连阳统计
    red_0 = (close_df > open_df).astype(float)
    red_1 = (close_df.shift(1) > open_df.shift(1)).astype(float)
    red_2 = (close_df.shift(2) > open_df.shift(2)).astype(float)
    red_3 = (close_df.shift(3) > open_df.shift(3)).astype(float)
    red_4 = (close_df.shift(4) > open_df.shift(4)).astype(float)
    red_count_5 = (red_0 + red_1 + red_2 + red_3 + red_4) / 5.0

    # 3. 近 5 日涨幅控制 (避免过早暴涨透支)
    open_t4 = open_df.shift(4)
    five_day_ret = safe_div(close_df - open_t4, open_t4)

    # 4. 复合连续强度打分
    is_deep_dd = (drawdown_180 > 0.25).astype(float)
    is_5_red = ((red_0 == 1.0) & (red_1 == 1.0) & (red_2 == 1.0) & (red_3 == 1.0) & (red_4 == 1.0)).astype(float)
    is_moderate_gain = (five_day_ret < 0.13).astype(float)

    # 基础连续分 + 事件命中脉冲权重
    base_score = drawdown_180 * red_count_5 * np.maximum(0.0, 1.0 - np.clip(five_day_ret, 0.0, 0.25))
    event_bonus = 2.0 * (is_deep_dd * is_5_red * is_moderate_gain)
    
    score = base_score + event_bonus
    return zscore(score)
