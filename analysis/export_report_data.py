#!/usr/bin/env python3
"""把深度分析结果导出为 HTML 报告所需的 report_data.json（数字全部程序化重算）。"""
import json, glob, os
import numpy as np
import pandas as pd

DATA = "./data"
OUT = "./analysis/report_data.json"
FACTORS = ["hl_5r", "5r", "high_all", "high_250", "hl_amo", "amo", "ma377_support", "ma250_support"]
FNAME = {"hl_5r": "HL+5R 底部五阳", "5r": "5R 五连阳", "high_all": "HIGH_ALL 覆盖期新高",
         "high_500": "HIGH_500", "high_250": "HIGH_250", "hl_amo": "HL+AMO 低位放量",
         "amo": "AMO 放量突破", "ma377_support": "MA377 支撑", "ma250_support": "MA250 支撑",
         "label": "LABEL 均线多头"}

slices = sorted(glob.glob(f"{DATA}/data_*.json"))
rows = []
for path in slices:
    day = os.path.basename(path)[5:15]
    with open(path) as f:
        d = json.load(f)
    for r in d:
        f_ = r["factors"]; det = f_["details"]; adj = r["adj"]
        rows.append((r["code"], day, adj["adj_close"], r["turnover"], adj["label"],
                     *[f_[f"factor_{k}"] for k in FACTORS],
                     det["drawdown_180_pct"], det["amt_ratio_max15"], det["amt_ratio_prev"],
                     det["return_10_pct"], det["dist_ma250_pct"], det["dist_ma377_pct"]))
cols = ["code", "day", "close", "turnover", "label"] + FACTORS + ["dd180", "amt_r_max15", "amt_r_prev", "ret10", "dist250", "dist377"]
df = pd.DataFrame(rows, columns=cols)

piv = df.pivot_table(index="code", columns="day", values="close").reindex(columns=sorted(df["day"].unique()))
days = list(piv.columns); n = len(days)
mkt_cum = (1 + piv.pct_change(axis=1).mean(axis=0).fillna(0)).cumprod()

# 前向收益矩阵（向量化）
fwd = {}
for h in (1, 5, 10, 20):
    v = np.full_like(piv.values, np.nan)
    for j in range(n - h):
        b, f_ = piv.values[:, j], piv.values[:, j + h]
        m = mkt_cum.iloc[j + h] / mkt_cum.iloc[j] - 1
        with np.errstate(invalid="ignore", divide="ignore"):
            v[:, j] = f_ / b - 1 - m
    fwd[h] = pd.DataFrame(v, index=piv.index, columns=piv.columns)

def stats_of(pairs, h):
    e = np.array([fwd[h].at[c, d] for c, d in pairs if not pd.isna(fwd[h].at[c, d])])
    if not len(e):
        return None
    return dict(n=int(len(e)), med=round(float(np.median(e)) * 100, 2),
                mean=round(float(np.mean(e)) * 100, 2), win=round(float((e > 0).mean()) * 100, 1))

out = {"meta": {"days": [days[0], days[-1]], "n_days": n, "n_stocks": int(df["code"].nunique()),
                "n_rows": int(len(df)), "version": "ver_20260819_091435", "generated": "2026-08-20"}}

# 1) 每日命中时序
daily = df.groupby("day")[FACTORS + ["label"]].sum()
out["daily"] = {"dates": list(daily.index),
                "label": daily["label"].astype(int).tolist(),
                **{k: daily[k].astype(int).tolist() for k in FACTORS}}

# 2) 前向收益（因子 + 对照）
ctrl_pairs = df.sample(150000, random_state=7)[["code", "day"]].values
out["fwd"] = {}
for h in (1, 5, 10, 20):
    ctrl = stats_of([tuple(x) for x in ctrl_pairs], h)
    entry = {"_control": ctrl}
    for k in FACTORS + ["label"]:
        pairs = df[df[k] == 1][["code", "day"]].drop_duplicates().values
        entry[k] = stats_of([tuple(x) for x in pairs], h)
    out["fwd"][str(h)] = entry

# 3) 半场对比 (T+10)
half = n // 2
out["halves"] = {}
for k in FACTORS + ["label"]:
    vv = []
    for scope in (days[:half], days[half:]):
        pairs = df[(df[k] == 1) & (df["day"].isin(scope))][["code", "day"]].drop_duplicates().values
        s = stats_of([tuple(x) for x in pairs], 10)
        vv.append(s["mean"] if s else None)
    out["halves"][k] = vv

# 4) 环境分层 (label 命中数三分解)
lab_daily = daily["label"].sort_values()
weak, strong = set(lab_daily.index[:n // 3]), set(lab_daily.index[-n // 3:])
out["regime"] = {}
for k in FACTORS + ["label"]:
    vv = []
    for scope in (strong, weak):
        pairs = df[(df[k] == 1) & (df["day"].isin(scope))][["code", "day"]].drop_duplicates().values
        s = stats_of([tuple(x) for x in pairs], 10)
        vv.append(s["mean"] if s else None)
    out["regime"][k] = vv

# 5) IC
def rank_(a):
    a = np.asarray(a, float)
    _, inv, counts = np.unique(a, return_inverse=True, return_counts=True)
    r = np.empty(len(counts)); c = 0
    for i, cc in enumerate(counts):
        r[i] = c + (cc + 1) / 2; c += cc
    return r[inv]

def spearman_(x, y):
    rx, ry = rank_(x) - rank_(x).mean(), rank_(y) - rank_(y).mean()
    d = np.sqrt((rx ** 2).sum() * (ry ** 2).sum())
    return float((rx * ry).sum() / d) if d > 0 else np.nan

out["ic"] = {}
for s, label in [("turnover", "log(成交额)"), ("rebound30", "30日反弹"), ("dist250", "偏离MA250"),
                 ("dist377", "偏离MA377"), ("ret10", "10日涨幅"), ("dd180", "180日回撤"),
                 ("amt_r_max15", "放量倍数(max15)")]:
    # rebound30 不在导出列，近似跳过（用 dist250 与 gain 数据）
    if s == "rebound30":
        continue
    ics = []
    for day, g in df.groupby("day"):
        g2 = g[[s]].copy()
        g2["f"] = [fwd[10].at[c, day] for c in g["code"]]
        g2 = g2.dropna()
        if len(g2) < 300:
            continue
        x = np.log10(g2[s] + 1) if s == "turnover" else g2[s]
        ic = spearman_(x, g2["f"].values)
        if not np.isnan(ic):
            ics.append(ic)
    ics = np.array(ics)
    out["ic"][s] = {"label": label, "ic": round(float(ics.mean()), 4),
                    "icir": round(float(ics.mean() / ics.std()), 2),
                    "pos_pct": round(float((ics > 0).mean()) * 100)}

# 6) high_all T+10 分布
e = np.array([fwd[10].at[c, d] for c, d in df[df["high_all"] == 1][["code", "day"]].values if not pd.isna(fwd[10].at[c, d])]) * 100
qs = np.percentile(e, [5, 10, 25, 50, 75, 90, 95, 99])
out["high_all_dist"] = {"pcts": [5, 10, 25, 50, 75, 90, 95, 99], "vals": [round(float(x), 1) for x in qs]}

# 7) 行业富集 (主要因子)：单独带出行业列
out["industry"] = {}
rows_ind = []
for path in slices:
    day = os.path.basename(path)[5:15]
    with open(path) as f:
        for r in json.load(f):
            rows_ind.append((day, r["sw_ind1"], *[r["factors"][f"factor_{k}"] for k in FACTORS]))
di = pd.DataFrame(rows_ind, columns=["day", "ind"] + FACTORS)
base = di["ind"].value_counts(normalize=True)
for k in ["high_all", "hl_amo", "ma250_support", "ma377_support", "5r", "amo"]:
    sub = di[di[k] == 1]
    vc = sub["ind"].value_counts(normalize=True)
    top = vc.head(5)
    out["industry"][k] = [{"ind": i, "pct": round(float(p) * 100, 1), "base": round(float(base.get(i, 0)) * 100, 1),
                           "x": round(float(p / base.get(i, 0.0001)), 1)} for i, p in top.items()]

# 8) 持续性
ds = df.sort_values(["code", "day"])
out["persist"] = {}
for k in FACTORS:
    runs, prev, run = [], None, 0
    for code, v in zip(ds["code"], ds[k]):
        if v == 1:
            run = run + 1 if code == prev else 1
        else:
            if run: runs.append(run)
            run = 0
        prev = code
    if run: runs.append(run)
    runs = np.array(runs)
    out["persist"][k] = {"segments": int(len(runs)), "med": float(np.median(runs)) if len(runs) else 0,
                         "mean": round(float(runs.mean()), 1) if len(runs) else 0,
                         "p90": float(np.percentile(runs, 90)) if len(runs) else 0,
                         "max": int(runs.max()) if len(runs) else 0}

# 9) 命中总量
out["totals"] = {k: int(df[k].sum()) for k in FACTORS}
out["totals"]["label"] = int(df["label"].sum())
out["fnames"] = FNAME

with open(OUT, "w") as f:
    json.dump(out, f, ensure_ascii=False)
print("saved", OUT, os.path.getsize(OUT), "bytes")
