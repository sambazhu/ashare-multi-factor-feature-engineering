#!/usr/bin/env python3
"""对照组 + IC 分析：因子前向收益是否真的弱于全体；连续信号值的预测力。"""
import json, glob, os
import numpy as np
import pandas as pd

DATA = "./data"
FACTORS = ["hl_5r", "5r", "high_all", "high_250", "hl_amo", "amo",
           "ma377_support", "ma250_support"]

slices = sorted(glob.glob(f"{DATA}/data_*.json"))
rows = []
for path in slices:
    day = os.path.basename(path)[5:15]
    with open(path) as f:
        d = json.load(f)
    for r in d:
        f_ = r["factors"]; det = f_["details"]; adj = r["adj"]
        rows.append((r["code"], day, adj["adj_close"], r["turnover"],
                     *[f_[f"factor_{k}"] for k in FACTORS], adj["label"],
                     det["drawdown_180_pct"], det["amt_ratio_max15"],
                     det["amt_ratio_prev"], det["return_10_pct"],
                     det["dist_ma250_pct"], det["dist_ma377_pct"],
                     det["five_day_gain_pct"], det["low_rebound_30_pct"]))
cols = ["code", "day", "close", "turnover"] + FACTORS + ["label",
         "dd180", "amt_r_max15", "amt_r_prev", "ret10", "dist250", "dist377", "gain5d", "rebound30"]
df = pd.DataFrame(rows, columns=cols)

piv = df.pivot_table(index="code", columns="day", values="close").reindex(columns=sorted(set(df["day"])))
days = list(piv.columns); n = len(days); idx_of = {d: i for i, d in enumerate(days)}
mkt_ret = piv.pct_change(axis=1).mean(axis=0)
mkt_cum = (1 + mkt_ret.fillna(0)).cumprod()

fwd_h = [1, 5, 10, 20]

def fwd_excess(code, day, h):
    i = idx_of.get(day)
    if i is None or i + h >= n or code not in piv.index:
        return None
    base, fut = piv.at[code, day], piv.iloc[piv.index.get_loc(code), i + h]
    if pd.isna(base) or pd.isna(fut):
        return None
    return fut / base - 1 - (mkt_cum.iloc[i + h] / mkt_cum.iloc[i] - 1)

# ---- 对照组：全体股票-日（随机抽样 20 万行） ----
print("===== 对照组：全体股票-日前向超额（等权基准） =====")
rng = np.random.default_rng(42)
sample = df.sample(min(200000, len(df)), random_state=42)[["code", "day"]].values
for h in fwd_h:
    e = [x for x in (fwd_excess(c, d, h) for c, d in sample) if x is not None]
    print(f"T+{h:>2}: n={len(e):6d} 中位={np.median(e)*100:+6.2f}% 均值={np.mean(e)*100:+6.2f}% 胜率={np.mean(np.array(e)>0)*100:4.1f}%")

# ---- 因子 vs 对照，T+10 ----
print("\n===== 因子 T+10 超额 vs 对照（中位 / 均值差, pp） =====")
ctrl_e10 = [x for x in (fwd_excess(c, d, 10) for c, d in df.sample(150000, random_state=7)[["code","day"]].values) if x is not None]
ctrl_med, ctrl_mean = np.median(ctrl_e10)*100, np.mean(ctrl_e10)*100
print(f"对照: 中位 {ctrl_med:+.2f}%  均值 {ctrl_mean:+.2f}%")
for k in FACTORS + ["label"]:
    hit = df[df[k] == 1][["code", "day"]].values
    e = [x for x in (fwd_excess(c, d, 10) for c, d in hit) if x is not None]
    m, mn = np.median(e)*100, np.mean(e)*100
    print(f"  {k:14s} 中位 {m:+6.2f}% ({m-ctrl_med:+5.2f}pp)   均值 {mn:+6.2f}% ({mn-ctrl_mean:+5.2f}pp)")

# ---- 状态环境分层：label 命中数前1/3日(强市) vs 后1/3日(弱市) ----
daily_label = df.groupby("day")["label"].sum().sort_values()
weak_days = set(daily_label.index[:n//3]); strong_days = set(daily_label.index[-n//3:])
print("\n===== 环境分层：T+10 超额均值（强市日=当日label命中数最高1/3, 弱市=最低1/3） =====")
for k in FACTORS + ["label"]:
    out = []
    for scope in (strong_days, weak_days):
        hit = df[(df[k] == 1) & (df["day"].isin(scope))][["code", "day"]].values
        e = [x for x in (fwd_excess(c, d, 10) for c, d in hit) if x is not None]
        out.append(np.mean(e)*100 if e else np.nan)
    print(f"  {k:14s} 强市 {out[0]:+6.2f}%   弱市 {out[1]:+6.2f}%")

# ---- IC：连续信号 vs T+10 超额的秩相关（按日截面取秩相关再平均） ----
print("\n===== 日截面 Rank-IC（信号值 vs T+10 超额，Spearman 均值 / ICIR） =====")
signals = ["dd180", "amt_r_max15", "amt_r_prev", "ret10", "dist250", "dist377", "gain5d", "rebound30", "turnover"]
df["fwd10"] = [fwd_excess(c, d, 10) if (x := fwd_excess(c, d, 10)) is not None else np.nan
               for c, d in zip(df["code"], df["day"])]
# 向量化重算 fwd10
fwd10_mat = {}
for h in [10]:
    ret = piv.copy()
    ret.iloc[:, :] = np.nan
    vals = piv.values
    ret_vals = np.full_like(vals, np.nan)
    for j in range(n - h):
        b, f_ = vals[:, j], vals[:, j + h]
        with np.errstate(invalid="ignore", divide="ignore"):
            r = f_ / b - 1 - (mkt_cum.iloc[j + h] / mkt_cum.iloc[j] - 1)
        ret_vals[:, j] = r
    fwd10_mat[h] = pd.DataFrame(ret_vals, index=piv.index, columns=piv.columns)
f10 = fwd10_mat[10]
df["fwd10"] = [f10.at[c, d] if (c in f10.index and d in f10.columns) else np.nan
               for c, d in zip(df["code"], df["day"])]

def rankdata_(a):
    a = np.asarray(a, dtype=float)
    order = a.argsort().argsort().astype(float)
    # 处理并列值：用平均秩
    _, inv, counts = np.unique(a, return_inverse=True, return_counts=True)
    ranks = np.empty(len(counts)); cum = 0
    for i, c in enumerate(counts):
        ranks[i] = cum + (c + 1) / 2.0; cum += c
    return ranks[inv]

def spearman_(x, y):
    rx, ry = rankdata_(x), rankdata_(y)
    rx -= rx.mean(); ry -= ry.mean()
    denom = np.sqrt((rx**2).sum() * (ry**2).sum())
    return float((rx * ry).sum() / denom) if denom > 0 else np.nan

for s in signals:
    ics = []
    for day, g in df.groupby("day"):
        g2 = g[[s, "fwd10"]].dropna()
        if len(g2) < 300:
            continue
        # turnover 取对数
        x = np.log10(g2[s] + 1) if s == "turnover" else g2[s]
        ic = spearman_(x, g2["fwd10"].values)
        if not np.isnan(ic):
            ics.append(ic)
    ics = np.array(ics)
    if len(ics):
        print(f"  {s:14s} IC均值={ics.mean():+.4f}  ICIR={ics.mean()/ics.std():+.2f}  IC>0占比={np.mean(ics>0)*100:.0f}%  天数={len(ics)}")

# ---- hl_5r 峰值日解剖 ----
print("\n===== hl_5r 单日爆发解剖 =====")
cnt = df.groupby("day")["hl_5r"].sum()
top_days = cnt.sort_values(ascending=False).head(5)
print(top_days.to_string())
# 检查这些日前后市场状态
lab = df.groupby("day")["label"].sum()
for d_ in top_days.index:
    i = idx_of[d_]
    window = days[max(0, i-5):i+6]
    print(f"  {d_}: label前后 = {lab.reindex(window).values.tolist()}")

# ---- 命中时股票市值代理（成交额）分层表现 ----
print("\n===== AMO 类因子按成交额分层 T+10 超额均值 =====")
for k in ["amo", "hl_amo"]:
    sub = df[df[k] == 1].copy()
    sub["e10"] = sub["fwd10"]
    try:
        sub["bucket"] = pd.qcut(sub["turnover"], 3, labels=["低额", "中额", "高额"])
        print(k, sub.groupby("bucket", observed=True)["e10"].agg(["count", "mean"]).assign(mean=lambda x: (x["mean"]*100).round(2)).to_dict()["mean"])
    except Exception as ex:
        print(k, "skip", ex)
