#!/usr/bin/env python3
"""深度分析 200 日因子切片：命中时序、因子重合、前向收益、行业分布、持续性。"""
import json, glob, os
from collections import defaultdict

import numpy as np
import pandas as pd

DATA = "./data"
OUT = "./analysis"

FACTORS = ["hl_5r", "5r", "high_all", "high_500", "high_250",
           "hl_amo", "amo", "ma377_support", "ma250_support"]

slices = sorted(glob.glob(f"{DATA}/data_*.json"))
print(f"slices: {len(slices)}")

rows = []
for path in slices:
    day = os.path.basename(path)[5:15]
    with open(path) as f:
        d = json.load(f)
    for r in d:
        f_ = r["factors"]
        rows.append((
            r["code"], day, r["sw_ind1"], r["adj"]["adj_close"], r["turnover"],
            r["adj"]["label"],
            *[f_[f"factor_{k}"] for k in FACTORS],
            f_["details"]["drawdown_180_pct"],
            f_["details"]["amt_ratio_max15"],
            f_["details"]["return_10_pct"],
            f_["details"]["dist_ma250_pct"],
        ))

cols = (["code", "day", "sw_ind1", "close", "turnover", "label"]
        + FACTORS + ["dd180", "amt_ratio_max15", "ret10", "dist_ma250"])
df = pd.DataFrame(rows, columns=cols)
df["board"] = df["code"].str[:2]
print(f"panel: {len(df)} rows, {df['code'].nunique()} stocks, {df['day'].nunique()} days")
print(f"boards: {df['board'].value_counts().to_dict()}")

# ---------- 1. 每日命中数时序 ----------
daily = df.groupby("day")[FACTORS + ["label"]].sum()
print("\n===== 1. 每日命中数统计（200日） =====")
stat = daily.describe().T[["mean", "std", "min", "max"]]
stat["cv%"] = (stat["std"] / stat["mean"] * 100).round(1)
print(stat.round(1).to_string())

# 市场状态代理：全市场上涨家数占比（close 涨跌无法直接算，用 label 命中数）
# 因子间每日命中数的相关性
print("\n每日命中数相关矩阵：")
print(daily.corr().round(2).to_string())

# ---------- 2. 因子重合（最新日 + 全期间） ----------
print("\n===== 2. 因子重合度 =====")
for scope, sub in [("全期间", df), ("最新日", df[df["day"] == df["day"].max()])]:
    print(f"\n[{scope}] 命中总数 / 占比：")
    tot = len(sub)
    hits = {k: int(sub[k].sum()) for k in FACTORS}
    for k, v in hits.items():
        print(f"  {k:16s} {v:7d}  ({v/tot*100:.2f}%)")
    print(f"[{scope}] 成对重合（Jaccard = |A∩B| / |A∪B|）:")
    for i, a in enumerate(FACTORS):
        for b in FACTORS[i+1:]:
            A, B = sub[a] == 1, sub[b] == 1
            inter, union = int((A & B).sum()), int((A | B).sum())
            if inter > 0:
                print(f"  {a:14s} ∩ {b:14s} {inter:6d}  J={inter/union:.3f}")

# ---------- 3. 前向收益 ----------
print("\n===== 3. 因子命中后前向收益（相对全市场等权基准的超额） =====")
piv = df.pivot_table(index="code", columns="day", values="close")
piv = piv.reindex(columns=sorted(piv.columns))
days = list(piv.columns)
n = len(days)
idx_of = {d: i for i, d in enumerate(days)}

# 全市场等权日收益（作为基准）
mkt_ret = piv.pct_change(axis=1).mean(axis=0)  # 每天全体均值收益

# 累计基准收益
mkt_cum = (1 + mkt_ret.fillna(0)).cumprod()

fwd_h = [1, 3, 5, 10, 20]
res = {}
for k in FACTORS + ["label"]:
    hit = df[df[k] == 1][["code", "day"]].drop_duplicates()
    raws, excs, ns = {h: [] for h in fwd_h}, {h: [] for h in fwd_h}, {h: 0 for h in fwd_h}
    for code, day in hit.itertuples(index=False):
        i = idx_of.get(day)
        if i is None or code not in piv.index:
            continue
        base = piv.at[code, day]
        if pd.isna(base) or base <= 0:
            continue
        for h in fwd_h:
            if i + h >= n:
                continue
            fut = piv.iloc[piv.index.get_loc(code), i + h]
            if pd.isna(fut):
                continue
            r = fut / base - 1
            # 超额 = 个股累计 - 市场累计（同区间）
            m = mkt_cum.iloc[i + h] / mkt_cum.iloc[i] - 1
            raws[h].append(r); excs[h].append(r - m); ns[h] += 1
    res[k] = {
        h: dict(n=ns[h],
                raw_med=np.median(raws[h]) if raws[h] else np.nan,
                raw_mean=np.mean(raws[h]) if raws[h] else np.nan,
                exc_med=np.median(excs[h]) if excs[h] else np.nan,
                exc_mean=np.mean(excs[h]) if excs[h] else np.nan,
                win=np.mean([x > 0 for x in excs[h]]) if excs[h] else np.nan)
        for h in fwd_h
    }

for k in FACTORS + ["label"]:
    line = [f"{k:14s}"]
    for h in fwd_h:
        r = res[k][h]
        line.append(f"T+{h:>2}: n={r['n']:6d} 超额中位={r['exc_med']*100:+6.2f}% 超额均值={r['exc_mean']*100:+6.2f}% 胜率={r['win']*100:4.1f}%")
    print("\n".join(line))

# 分年度/分半场稳定性：前100日 vs 后100日
half1, half2 = days[:n//2], days[n//2:]
print("\n半场对比（T+10 超额中位）：前半 {} ~ {} / 后半 {} ~ {}".format(days[0], half1[-1], half2[0], days[-1]))
for k in FACTORS + ["label"]:
    vals = []
    for window in (half1, half2):
        hit = df[(df[k] == 1) & (df["day"].isin(window))][["code", "day"]].drop_duplicates()
        e = []
        for code, day in hit.itertuples(index=False):
            i = idx_of.get(day)
            if i is None or i + 10 >= n or code not in piv.index:
                continue
            base = piv.at[code, day]; fut = piv.iloc[piv.index.get_loc(code), i + 10]
            if pd.isna(base) or pd.isna(fut):
                continue
            m = mkt_cum.iloc[i + 10] / mkt_cum.iloc[i] - 1
            e.append(fut / base - 1 - m)
        vals.append(np.median(e) * 100 if e else np.nan)
    print(f"  {k:14s} 前半 {vals[0]:+6.2f}%   后半 {vals[1]:+6.2f}%")

# ---------- 4. 行业分布 ----------
print("\n===== 4. 因子命中的行业集中度（全期间，命中数 Top5 行业） =====")
for k in FACTORS:
    sub = df[df[k] == 1]
    if not len(sub):
        continue
    top = sub["sw_ind1"].value_counts().head(5)
    base_share = df["sw_ind1"].value_counts(normalize=True)
    enrich = {ind: f"{cnt} ({cnt/len(sub)*100:.1f}%, 基准{base_share.get(ind,0)*100:.1f}%, 倍数{cnt/len(sub)/base_share.get(ind,0.0001):.1f}x)"
              for ind, cnt in top.items()}
    print(f"  {k:14s}: " + " | ".join(f"{ind} {v}" for ind, v in enrich.items()))

# ---------- 5. 持续性：连续命中天数 ----------
print("\n===== 5. 因子命中持续性（连续命中段长度分布） =====")
df_sorted = df.sort_values(["code", "day"])
for k in FACTORS:
    runs = []
    prev_code, run = None, 0
    for code, v in zip(df_sorted["code"], df_sorted[k]):
        if v == 1:
            if code == prev_code:
                run += 1
            else:
                run = 1
        else:
            if run:
                runs.append(run)
            run = 0
        prev_code = code
    if run:
        runs.append(run)
    runs = np.array(runs) if runs else np.array([0])
    uniq_days = df.groupby("code")["day"].count().max()
    print(f"  {k:14s} 段数={len(runs):6d}  中位长度={np.median(runs):.0f}  均值={runs.mean():.1f}  P90={np.percentile(runs,90):.0f}  最长={runs.max()}")

# ---------- 6. 板块分布 ----------
print("\n===== 6. 因子命中的板块占比 vs 基准占比 =====")
base_board = df["board"].value_counts(normalize=True)
for k in FACTORS:
    sub = df[df[k] == 1]
    if not len(sub):
        continue
    sb = sub["board"].value_counts(normalize=True)
    s = " | ".join(f"{b}: {sb.get(b,0)*100:.1f}%(基准{base_board[b]*100:.1f}%, {sb.get(b,0)/base_board[b]:.1f}x)" for b in ["60", "00", "30", "68"])
    print(f"  {k:14s}: {s}")

# ---------- 7. LABEL(均线多头) 与因子关系、市场状态 ----------
print("\n===== 7. 均线多头 LABEL 每日数量（市场状态代理） =====")
lab = daily["label"]
print(f"  均值 {lab.mean():.0f}  中位 {lab.median():.0f}  min {lab.min():.0f} ({lab.idxmin()})  max {lab.max():.0f} ({lab.idxmax()})")
print(f"  最新日: {lab.iloc[-1]:.0f}  首日: {lab.iloc[0]:.0f}")

# 保存每日命中时序供后续使用
daily.to_csv(f"{OUT}/daily_hit_counts.csv")
print(f"\nsaved {OUT}/daily_hit_counts.csv")
