#!/usr/bin/env python3
"""因子标签核对 v2 (修正版)
- LABEL 完整规则: rn>=250 AND DAY_GAP=1 (市场交易日连续) AND 六线排列(T0与T-1) AND 六线全升
- 层1: 全面板从 CSV 列重推导, 舍入敏感比较 (差>1e-3 才判定违规, <=1e-3 记为舍入模糊区)
- 层2: DB 全精度 Decimal 重算 MA + LABEL, 样本股 x 200 日
"""
import csv, sys, random, os
from collections import defaultdict
from decimal import Decimal

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from test_factor_calc import get_db_conn

CSV = os.path.join(BASE_DIR, "ma_features_200d_adj.csv")
random.seed(42)
EPS = Decimal("0.001")  # CSV 3位小数, 两个舍入值差>1e-3 才是确定性违规

# ============ 层 1: 全面板 (含 DAY_GAP 条件 + 舍入模糊区分类) ============
print("=" * 70)
print("层 1: 全面板 1,037,939 行重推导 (完整 LABEL 规则 + 舍入感知)")
print("=" * 70)

def f(x):
    return Decimal(x) if x not in ("", None) else None

def gt_rounded(a, b):
    """从3位舍入值判断 a>b: 返回 True/False/None(模糊)"""
    if a is None or b is None: return False
    d = a - b
    if d > EPS: return True
    if d < -EPS: return False
    return None  # |d|<=1e-3 舍入模糊

viol = defaultdict(int)
ambig = defaultdict(int)
ex = defaultdict(list)
n_total = label1_rows = 0

is_trading_map = {}
with open(CSV, encoding="utf-8-sig") as fh:
    for r in csv.DictReader(fh):
        is_trading_map[(r["SECUCODE"], r["T0"])] = float(r["TURNOVERVALUE"] or 0) > 0

with open(CSV, encoding="utf-8-sig") as fh:
    for r in csv.DictReader(fh):
        n_total += 1
        hd = int(r["HISTORY_DAYS"])
        mas = [f(r[m]) for m in ["MA5","MA10","MA20","MA60","MA120","MA250"]]
        pmas = [f(r[m]) for m in ["PREV_MA5","PREV_MA10","PREV_MA20","PREV_MA60","PREV_MA120","PREV_MA250"]]

        def check(name, stored, comps):
            """comps: 六个 gt_rounded 结果列表; 确定性才判违规"""
            if any(c is False for c in comps):
                derived = False
            elif all(c is True for c in comps):
                derived = True
            else:
                ambig[name] += 1
                return
            if derived != (stored == "1"):
                viol[name] += 1
                if len(ex[name]) < 3: ex[name].append((r["SECUCODE"], r["T0"], "derived" if derived else "stored", stored))

        is_trading = is_trading_map.get((r["SECUCODE"], r["T0"]), False)
        if not is_trading:
            if r["ALIGN_T0"] != "0":
                viol["ALIGN_T0"] += 1
                if len(ex["ALIGN_T0"]) < 3: ex["ALIGN_T0"].append((r["SECUCODE"], r["T0"], "derived_0", r["ALIGN_T0"]))
        else:
            check("ALIGN_T0", r["ALIGN_T0"], [gt_rounded(mas[i], mas[i+1]) for i in range(5)])

        check("ALIGN_T1", r["ALIGN_T1"], [gt_rounded(pmas[i], pmas[i+1]) for i in range(5)])
        check("ALL_UP", r["ALL_UP"], [gt_rounded(a, b) for a, b in zip(mas, pmas)])

        # LABEL: 三个条件全部确定性成立 + DAY_GAP=1 + rn>=251 + IS_TRADING=1 且 T-1 也是正常交易日 (TRADING_CNT_2=2)
        c0 = [gt_rounded(mas[i], mas[i+1]) for i in range(5)]
        c1 = [gt_rounded(pmas[i], pmas[i+1]) for i in range(5)]
        cu = [gt_rounded(a, b) for a, b in zip(mas, pmas)]
        prev_is_trading = is_trading_map.get((r["SECUCODE"], r["PREV_DAY"]), True)
        trading_cnt_2_ok = is_trading and prev_is_trading

        if any(c is False for c in c0+c1+cu) or int(r["DAY_GAP"]) != 1 or hd < 251 or not trading_cnt_2_ok:
            dlabel = 0
        elif all(c is True for c in c0+c1+cu) and trading_cnt_2_ok:
            dlabel = 1
        else:
            ambig["LABEL"] += 1
            dlabel = None
        if dlabel is not None:
            if r["LABEL"] == "1": label1_rows += 1
            if dlabel != int(r["LABEL"]):
                viol["LABEL"] += 1
                if len(ex["LABEL"]) < 3: ex["LABEL"].append((r["SECUCODE"], r["T0"], dlabel, r["LABEL"]))

print(f"总行数: {n_total:,}, LABEL=1: {label1_rows:,}")
for name in ["ALIGN_T0", "ALIGN_T1", "ALL_UP", "LABEL"]:
    v, a = viol[name], ambig[name]
    print(f"[{'PASS' if v == 0 else 'FAIL'}] {name}: 确定性违规 {v}, 舍入模糊区 {a} (占比 {100.0*a/n_total:.2f}%)")
    if ex[name]: print("   违规样例:", ex[name])

# ============ 层 2: DB Decimal 全精度重算 ============
print()
print("=" * 70)
print("层 2: DB 全精度 Decimal 重算 MA + LABEL (含 DAY_GAP 连续性), 样本 x 200 日")
print("=" * 70)

label1_stocks = defaultdict(int)
all_stocks = set()
with open(CSV, encoding="utf-8-sig") as fh:
    for r in csv.DictReader(fh):
        all_stocks.add(r["SECUCODE"])
        if r["LABEL"] == "1": label1_stocks[r["SECUCODE"]] += 1
rich = sorted(label1_stocks, key=lambda c: -label1_stocks[c])[:8]
sample = rich + random.sample(sorted(all_stocks - set(rich)), 9) + ["688012"]

conn = get_db_conn(); cur = conn.cursor()
cur.arraysize = 5000; cur.prefetchrows = 5000
codes_in = ",".join(f"'{c}'" for c in sample)
cur.execute(f"SELECT SECUCODE, INNERCODE FROM ZBJYDB.SECUMAIN WHERE SECUCODE IN ({codes_in}) AND SECUCATEGORY=1")
meta = dict(cur.fetchall())
in_list = ",".join(str(v) for v in meta.values())
cur.execute(f"""SELECT INNERCODE, TRADINGDAY, ADJCLOSEPRICE FROM ZBJYDB.CS_STOCKADJPERFORMANCE
                WHERE INNERCODE IN ({in_list}) AND ADJUSTINGMETHOD=1 AND ADJUSTINGSTANDARD=1
                  AND ADJCLOSEPRICE IS NOT NULL ORDER BY INNERCODE, TRADINGDAY""")
hist = defaultdict(list)
for ic, td, cp in cur.fetchall():
    hist[ic].append((td.strftime("%Y-%m-%d"), Decimal(str(cp))))
# 市场交易日历 (连续性独立判定)
cur.execute("""SELECT TO_CHAR(TRADINGDATE,'YYYY-MM-DD') FROM ZBJYDB.QT_TRADINGDAYNEW
               WHERE SECUMARKET=83 AND IFTRADINGDAY=1 ORDER BY TRADINGDATE""")
seq = {d: i for i, (d,) in enumerate(cur.fetchall())}
conn.close()

csv_rows = defaultdict(dict); dates_200 = set()
with open(CSV, encoding="utf-8-sig") as fh:
    for r in csv.DictReader(fh):
        if r["SECUCODE"] in meta:
            csv_rows[r["SECUCODE"]][r["T0"]] = r
            dates_200.add(r["T0"])

WINS = [5, 10, 20, 60, 120, 250]
tot = ma_mism = lbl_mism = gap_mism = 0
ma_ex, lbl_ex = [], []
for code, ic in meta.items():
    rows = hist[ic]
    n = len(rows)
    prefix = [Decimal(0)]
    for _, v in rows: prefix.append(prefix[-1] + v)
    def ma_at(j, w):
        return (prefix[j+1] - prefix[j+1-w]) / Decimal(w) if j + 1 >= w else None
    idx = {d: j for j, (d, _) in enumerate(rows)}

    for d in dates_200:
        c_row = csv_rows[code].get(d); j = idx.get(d)
        if not c_row or j is None: continue
        tot += 1
        # 连续性 (独立于 CSV 的 DAY_GAP)
        gap = seq[d] - seq[rows[j-1][0]] if j >= 1 else 999
        if int(c_row["DAY_GAP"]) != gap:
            gap_mism += 1
        m0 = {w: ma_at(j, w) for w in WINS}
        m1 = {w: ma_at(j-1, w) for w in WINS} if j >= 1 else {w: None for w in WINS}
        # MA 数值比对 (3位小数展示舍容差 6e-4)
        for w in WINS:
            for tag, mv in (("MA", m0[w]), ("PREV_MA", m1[w])):
                cv = Decimal(c_row[f"{tag}{w}"]) if c_row[f"{tag}{w}"] else None
                if (cv is None) != (mv is None) or (cv is not None and abs(cv - mv) > Decimal("0.0006")):
                    ma_mism += 1
                    if len(ma_ex) < 3: ma_ex.append((code, d, f"{tag}{w}", str(cv), str(mv)))
        # LABEL 完整规则
        vals = [m0[w] for w in WINS]; pvals = [m1[w] for w in WINS]
        a0 = all(v is not None for v in vals) and all(vals[i] > vals[i+1] for i in range(5))
        a1 = all(v is not None for v in pvals) and all(pvals[i] > pvals[i+1] for i in range(5))
        up = all(a is not None and b is not None for a, b in zip(vals, pvals)) and all(a > b for a, b in zip(vals, pvals))
        rn_ok = (j + 1) >= 251
        t0_row = c_row
        t1_row = csv_rows[code].get(rows[j-1][0]) if j >= 1 else None
        is_trading_t0 = float(t0_row["TURNOVERVALUE"] or 0) > 0
        is_trading_t1 = (float(t1_row["TURNOVERVALUE"] or 0) > 0) if t1_row is not None else (gap == 1)
        trading_cnt_2_ok = is_trading_t0 and is_trading_t1
        dl = 1 if (rn_ok and gap == 1 and trading_cnt_2_ok and a0 and a1 and up) else 0
        if dl != int(c_row["LABEL"]):
            lbl_mism += 1
            if len(lbl_ex) < 5: lbl_ex.append((code, d, dl, c_row["LABEL"]))

print(f"比对行数: {tot:,}")
print(f"[{'PASS' if gap_mism == 0 else 'FAIL'}] DAY_GAP 独立重算一致 (差异 {gap_mism})")
print(f"[{'PASS' if ma_mism == 0 else 'FAIL'}] MA5~MA250/PREV_MA Decimal 重算一致 (差异 {ma_mism})")
if ma_ex: print("   样例:", ma_ex)
print(f"[{'PASS' if lbl_mism == 0 else 'FAIL'}] LABEL 完整规则 Decimal 重算一致 (差异 {lbl_mism})")
if lbl_ex: print("   样例:", lbl_ex)

ok = not any(viol.values()) and ma_mism == 0 and lbl_mism == 0 and gap_mism == 0
print()
print("===== 总结论:", "全部标签验证通过" if ok else "存在确定性差异, 需人工复核", "=====")
sys.exit(0 if ok else 1)
