#!/usr/bin/env python3
"""全量回归 DB 深度复核:
1. 全量 HIGH_ALL 行的 LISTING_TDAYS > 500 硬门槛 (27,373 行逐行)
2. HIGH_250 行按上市天数分解: 次新股降级 vs 老股正常 D250
3. 覆盖期交易日数声明复核 (2024-07-10 至今, 512 交易日)
4. 新随机样本 20 只股票全历史 Python 重算 vs 已发布 CSV 全量 9 因子比对
"""
import os, csv, random, sys
from collections import defaultdict
import oracledb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from test_factor_calc import get_db_conn, compute_factors_py

random.seed(20260819)
CSV = os.path.join(BASE_DIR, "ma_features_200d_adj.csv")

conn = get_db_conn()
cur = conn.cursor()
cur.arraysize = 5000
cur.prefetchrows = 5000

# [1] 交易日历
cur.execute("""SELECT TO_CHAR(TRADINGDATE,'YYYY-MM-DD'), ROW_NUMBER() OVER (ORDER BY TRADINGDATE ASC)
               FROM ZBJYDB.QT_TRADINGDAYNEW WHERE SECUMARKET = 83 AND IFTRADINGDAY = 1""")
seq_map = {r[0]: int(r[1]) for r in cur.fetchall()}
print(f"市场交易日历: {len(seq_map):,} 天")

# [2] A 股上市日期
cur.execute("""SELECT SECUCODE, LISTEDDATE FROM ZBJYDB.SECUMAIN
               WHERE SUBSTR(SECUCODE,1,2) IN ('60','68','00','30') AND SECUCATEGORY = 1""")
listed = {r[0]: r[1] for r in cur.fetchall()}
print(f"A 股主数据: {len(listed):,} 只")

# [3] 覆盖期交易日数 (CS_STOCKADJPERFORMANCE 事实日历)
cur.execute("""SELECT COUNT(DISTINCT P.TRADINGDAY), MIN(P.TRADINGDAY), MAX(P.TRADINGDAY)
               FROM ZBJYDB.CS_STOCKADJPERFORMANCE P
               JOIN ZBJYDB.SECUMAIN S ON P.INNERCODE = S.INNERCODE
               WHERE SUBSTR(S.SECUCODE,1,2) IN ('60','68','00','30') AND S.SECUCATEGORY = 1
                 AND P.ADJUSTINGMETHOD = 1 AND P.ADJUSTINGSTANDARD = 1""")
cov_n, cov_min, cov_max = cur.fetchone()
print(f"覆盖期事实日历: {cov_n} 个交易日 ({cov_min} ~ {cov_max}) — 验收报告声明 512/起于 2024-07-10")

conn.close()

# ===== 本地: 加载 CSV 命中行 =====
high_all_rows, high_250_rows, susp_stocks = [], set(), set()
dates_200 = set()
with open(CSV, encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        dates_200.add(r["T0"])
        if r["FACTOR_HIGH_ALL"] == "1": high_all_rows.append((r["SECUCODE"], r["T0"]))
        if r["FACTOR_HIGH_250"] == "1": high_250_rows.add((r["SECUCODE"], r["T0"]))
        if float(r["TURNOVERVALUE"] or 0) == 0.0: susp_stocks.add(r["SECUCODE"])

def listing_tdays(code, d):
    ld = listed.get(code)
    if not ld: return None
    return seq_map.get(d, 0) - seq_map.get(ld.strftime("%Y-%m-%d"), 0) + 1

# ===== 检查 A: 全量 HIGH_ALL 门槛 =====
bad_gate = []
for code, d in high_all_rows:
    lt = listing_tdays(code, d)
    if lt is None or lt <= 500:
        bad_gate.append((code, d, lt))
print(f"\n[A] HIGH_ALL 全量门槛: {len(high_all_rows):,} 行, LISTING_TDAYS<=500 违规 {len(bad_gate)} 行")
if bad_gate[:5]: print("    违规样例:", bad_gate[:5])

# ===== 检查 B: HIGH_250 分解 =====
degraded, normal = 0, 0
for code, d in high_250_rows:
    lt = listing_tdays(code, d)
    if lt is not None and lt <= 500: degraded += 1
    else: normal += 1
print(f"[B] HIGH_250 共 {len(high_250_rows):,} 行: 次新股降级(LISTING_TDAYS<=500) {degraded}, 老股正常D250 {normal}")

# ===== 检查 C: 新随机样本独立重算 =====
codes_all = set()
for code, d in high_all_rows: codes_all.add(code)
h250_codes = {c for c, _ in high_250_rows}
deg_codes = {c for c, d in high_250_rows if (listing_tdays(c, d) or 99999) <= 500}

sample = (
    random.sample(sorted(codes_all), min(len(codes_all), 8)) +
    random.sample(sorted(deg_codes), min(len(deg_codes), 6)) +
    random.sample(sorted(h250_codes - deg_codes), min(len(h250_codes - deg_codes), 4)) +
    random.sample(sorted(susp_stocks), min(len(susp_stocks), 2))
)
sample = list(dict.fromkeys(sample))
print(f"\n[C] 独立随机样本 {len(sample)} 只: {sample}")

conn = get_db_conn(); cur = conn.cursor(); cur.arraysize = 5000; cur.prefetchrows = 5000
codes_in = ",".join(f"'{c}'" for c in sample)
cur.execute(f"""SELECT S.INNERCODE, S.SECUCODE, COALESCE(S.SECUABBR, S.CHINAME), S.LISTEDDATE
                FROM ZBJYDB.SECUMAIN S WHERE S.SECUCODE IN ({codes_in}) AND S.SECUCATEGORY = 1""")
meta = {r[1]: {"innercode": r[0], "name": r[2], "listed": r[3]} for r in cur.fetchall()}
in_list = ",".join(str(m["innercode"]) for m in meta.values())

cur.execute(f"""
    WITH all_quotes AS (
        SELECT INNERCODE, TRADINGDAY, CLOSEPRICE, TURNOVERVALUE FROM ZBJYDB.QT_DAILYQUOTE WHERE INNERCODE IN ({in_list})
        UNION ALL
        SELECT INNERCODE, TRADINGDAY, CLOSEPRICE, TURNOVERVALUE FROM ZBJYDB.LC_STIBDAILYQUOTE WHERE INNERCODE IN ({in_list})
    )
    SELECT P.INNERCODE, P.TRADINGDAY, P.ADJOPENPRICE, P.ADJHIGHPRICE, P.ADJLOWPRICE, P.ADJCLOSEPRICE,
           COALESCE(Q.CLOSEPRICE, P.ADJCLOSEPRICE), COALESCE(Q.TURNOVERVALUE, 0)
    FROM ZBJYDB.CS_STOCKADJPERFORMANCE P
    LEFT JOIN all_quotes Q ON P.INNERCODE = Q.INNERCODE AND P.TRADINGDAY = Q.TRADINGDAY
    WHERE P.INNERCODE IN ({in_list}) AND P.ADJUSTINGMETHOD = 1 AND P.ADJUSTINGSTANDARD = 1
      AND P.ADJCLOSEPRICE IS NOT NULL
    ORDER BY P.INNERCODE, P.TRADINGDAY
""")
cols = ["INNERCODE","TRADINGDAY","ADJOPENPRICE","ADJHIGHPRICE","ADJLOWPRICE","ADJCLOSEPRICE","RAW_CLOSEPRICE","TURNOVERVALUE"]
quotes = defaultdict(list)
for r in cur.fetchall():
    quotes[r[0]].append(dict(zip(cols, r)))
conn.close()

# CSV 面板命中行索引
csv_hit = defaultdict(dict)
with open(CSV, encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        if r["SECUCODE"] in meta: csv_hit[r["SECUCODE"]][r["T0"]] = r

FK = [("FACTOR_HL_5R","factor_hl_5r"),("FACTOR_5R","factor_5r"),("FACTOR_HIGH_ALL","factor_high_all"),
      ("FACTOR_HIGH_500","factor_high_500"),("FACTOR_HIGH_250","factor_high_250"),
      ("FACTOR_HL_AMO","factor_hl_amo"),("FACTOR_AMO","factor_amo"),
      ("FACTOR_MA377_SUPPORT","factor_ma377_support"),("FACTOR_MA250_SUPPORT","factor_ma250_support")]

total, mism = 0, 0
for code, m in meta.items():
    rows = quotes[m["innercode"]]
    ld_s = m["listed"].strftime("%Y-%m-%d") if m["listed"] else "1990-01-01"
    ls = seq_map.get(ld_s, 0)
    ltm = {r["TRADINGDAY"].strftime("%Y-%m-%d"): seq_map.get(r["TRADINGDAY"].strftime("%Y-%m-%d"), 0) - ls + 1 for r in rows}
    py = {x["date"]: x for x in compute_factors_py(rows, market_td_seq_map=seq_map, listing_tdays_map=ltm)}
    sm = 0
    for d in dates_200:
        c_row, p_row = csv_hit[code].get(d), py.get(d)
        if not c_row or not p_row:
            print(f"  [MISSING] {code} {d}: CSV={'Y' if c_row else 'N'} PY={'Y' if p_row else 'N'}")
            continue
        total += 1
        for ck, pk in FK:
            if int(c_row[ck]) != int(p_row[pk]):
                sm += 1; mism += 1
                print(f"  [MISMATCH] {code} {d} {pk}: CSV={c_row[ck]} PY={p_row[pk]}")
    print(f"  {code} ({m['name']}): {len(dates_200)} 行, 不一致 {sm}")

print(f"\n[C] 结果: 比对 {total:,} 行, 不一致 {mism}, 一致率 {100.0*(1-mism/max(total,1)):.2f}%")
print(f"\n===== 汇总: 门槛违规 {len(bad_gate)}, 降级 {degraded} + 正常 {normal} = {len(high_250_rows)}, 样本不一致 {mism} =====")
sys.exit(1 if (bad_gate or mism) else 0)
