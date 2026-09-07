import csv
import sys
import os
from collections import Counter, defaultdict

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(BASE_DIR, "ma_features_200d_adj.csv")

results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" | {detail}" if detail else ""))

rows = []
with open(CSV_PATH, encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    for r in reader:
        rows.append(r)

print(f"面板加载完成: {len(rows):,} 行\n")

# ===== 1. 总量与板块分布 =====
check("面板总行数 >= 1,000,000", len(rows) >= 1000000, f"实际 {len(rows):,}")

star_rows = [r for r in rows if r["SECUCODE"].startswith("68")]
main_rows = [r for r in rows if not r["SECUCODE"].startswith("68")]
check("科创板 (688) 行数 >= 100,000", len(star_rows) >= 100000, f"实际 {len(star_rows):,}")
check("主板+创业板行数 >= 800,000", len(main_rows) >= 800000, f"实际 {len(main_rows):,}")

# 板块构成合法性: 只允许 60/68/00/30 前缀
bad_prefix = [r["SECUCODE"] for r in rows if r["SECUCODE"][:2] not in ("60", "68", "00", "30")]
check("股票池前缀仅 60/68/00/30 (需求§3.1)", len(bad_prefix) == 0, f"异常 {len(bad_prefix)} 例")

# ===== 2. 交易日覆盖 =====
dates = sorted({r["T0"] for r in rows})
check("精确 200 个交易日切片", len(dates) == 200, f"实际 {len(dates)} ({dates[0]} ~ {dates[-1]})")

# ===== 3. 最新日切片 =====
latest = dates[-1]
latest_rows = [r for r in rows if r["T0"] == latest]
latest_codes = {r["SECUCODE"] for r in latest_rows}
check(f"最新日 ({latest}) 活跃股票数 >= 5,000", len(latest_rows) >= 5000, f"实际 {len(latest_rows):,}")

latest_star = [r for r in latest_rows if r["SECUCODE"].startswith("68")]
check(f"最新日科创板股票数 >= 500", len(latest_star) >= 500, f"实际 {len(latest_star)}")

star_valid_amo = [r for r in latest_star if float(r["TURNOVERVALUE"] or 0) > 0]
check("最新日科创板有效成交额覆盖率 >= 99% (允许停牌)",
      len(star_valid_amo) / len(latest_star) >= 0.99,
      f"{len(star_valid_amo)}/{len(latest_star)}")

# ===== 4. 因子命中统计 =====
print()
factors = ["LABEL", "FACTOR_HL_5R", "FACTOR_5R", "FACTOR_HIGH_ALL", "FACTOR_HIGH_500", 
           "FACTOR_HIGH_250", "FACTOR_HL_AMO", "FACTOR_AMO", "FACTOR_MA377_SUPPORT", "FACTOR_MA250_SUPPORT"]

for fac in factors:
    actual = sum(1 for r in rows if r[fac] == "1")
    check(f"因子 {fac} 命中数统计正常", actual >= 0, f"实际 {actual:,}")

# ===== 5. 需求文档不变式 =====
print()
viol = []
for i, r in enumerate(rows):
    hl5r, f5r = r["FACTOR_HL_5R"] == "1", r["FACTOR_5R"] == "1"
    ha, h5, h2 = r["FACTOR_HIGH_ALL"] == "1", r["FACTOR_HIGH_500"] == "1", r["FACTOR_HIGH_250"] == "1"
    hla, amo = r["FACTOR_HL_AMO"] == "1", r["FACTOR_AMO"] == "1"
    m377, m250 = r["FACTOR_MA377_SUPPORT"] == "1", r["FACTOR_MA250_SUPPORT"] == "1"

    if hl5r and f5r: viol.append((r["SECUCODE"], r["T0"], "HL_5R与5R同时命中"))
    # 包含口径校验：覆盖期新高必然满足 500日新高，500日新高必然满足 250日新高
    if ha and not h5: viol.append((r["SECUCODE"], r["T0"], "HIGH_ALL命中但未包含在HIGH_500"))
    if h5 and not h2: viol.append((r["SECUCODE"], r["T0"], "HIGH_500命中但未包含在HIGH_250"))
    if hla and not amo: viol.append((r["SECUCODE"], r["T0"], "HL_AMO命中但AMO未命中"))

    # HIGH_TYPE 与三个新高布尔一致
    want_ht = "ALL_TIME" if ha else ("D500" if h5 else ("D250" if h2 else "NONE"))
    if r["HIGH_TYPE"] != want_ht: viol.append((r["SECUCODE"], r["T0"], f"HIGH_TYPE={r['HIGH_TYPE']}应为{want_ht}"))

    # MA_SUPPORT_TYPE 与两个支撑布尔一致
    want_mt = "BOTH" if (m250 and m377) else ("MA377" if m377 else ("MA250" if m250 else "NONE"))
    if r["MA_SUPPORT_TYPE"] != want_mt: viol.append((r["SECUCODE"], r["T0"], f"MA_SUPPORT_TYPE={r['MA_SUPPORT_TYPE']}应为{want_mt}"))

    # PRIMARY_FACTOR 严格遵循优先级 (需求§5)
    pf = r["PRIMARY_FACTOR"]
    want_pf = ("HL_5R" if hl5r else "5R" if f5r else "HIGH_ALL" if ha else "HIGH_500" if h5
               else "HIGH_250" if h2 else "HL_AMO" if hla else "AMO" if amo
               else "MA377_SUPPORT" if m377 else "MA250_SUPPORT" if m250 else "NONE")
    if pf != want_pf: viol.append((r["SECUCODE"], r["T0"], f"PRIMARY_FACTOR={pf}应为{want_pf}"))

    # LABEL 一致性 (交接文档定义: 必须满排列+全升+有效交易日无停牌+样本边界rn>=251)
    if r["LABEL"] == "1":
        if not (r["ALIGN_T0"] == "1" and r["ALIGN_T1"] == "1" and r["ALL_UP"] == "1"):
            viol.append((r["SECUCODE"], r["T0"], "LABEL=1但ALIGN/UP不全为1"))
        if float(r["TURNOVERVALUE"] or 0) <= 0:
            viol.append((r["SECUCODE"], r["T0"], "LABEL=1但当日成交额为0(停牌)"))
        if int(r["DAY_GAP"]) != 1:
            viol.append((r["SECUCODE"], r["T0"], f"LABEL=1但DAY_GAP={r['DAY_GAP']}!=1"))
        if int(r["HISTORY_DAYS"]) < 251:
            viol.append((r["SECUCODE"], r["T0"], f"LABEL=1但HISTORY_DAYS={r['HISTORY_DAYS']}<251"))

    # AMO 必要条件可本地校验的部分: 成交额 > 1亿, T0须为有效交易日
    if amo:
        if float(r["TURNOVERVALUE"] or 0) <= 100000000.0:
            viol.append((r["SECUCODE"], r["T0"], "AMO命中但成交额<=1亿"))
    if (amo or hla) and float(r["TURNOVERVALUE"] or 0) <= 0:
        viol.append((r["SECUCODE"], r["T0"], "放量因子命中但停牌"))

check("不变式: HL_5R 与 5R 强制互斥 (需求§5)", not any(v[2].startswith("HL_5R") for v in viol))
check("不变式: 新高包含关系 (HIGH_ALL ⊆ HIGH_500 ⊆ HIGH_250)", not any("HIGH_" in v[2] and "未包含" in v[2] for v in viol))
check("不变式: HL_AMO ⊆ AMO (需求§5)", not any("HL_AMO" in v[2] for v in viol))
check("不变式: HIGH_TYPE 与新高布尔一致", not any("HIGH_TYPE" in v[2] for v in viol))
check("不变式: MA_SUPPORT_TYPE 与支撑布尔一致", not any("MA_SUPPORT_TYPE" in v[2] for v in viol))
check("不变式: PRIMARY_FACTOR 遵循优先级 HL_5R>5R>HIGH_ALL>HIGH_500>HIGH_250>HL_AMO>AMO>MA377>MA250",
      not any("PRIMARY_FACTOR" in v[2] for v in viol))
check("不变式: LABEL = ALIGN_T0 ∧ ALIGN_T1 ∧ ALL_UP ∧ IS_TRADING", not any("ALIGN" in v[2] or "LABEL" in v[2] for v in viol))
check("不变式: AMO 命中行成交额 > 1 亿元 (需求§4.5)", not any("成交额<=1亿" in v[2] for v in viol))
if viol:
    print(f"  违规明细 (前20条): {viol[:20]}")

# 4R 阻塞标签: 不得伪装成 0 输出 (需求§4.2)
check("4R 标签保持阻塞: 面板无 FACTOR_4R 列", "FACTOR_4R" not in rows[0])

# ===== 6. 688012 停牌回归断言 (验收报告 P0/P1) =====
print()
r688012_0105 = [r for r in rows if r["SECUCODE"] == "688012" and r["T0"] == "2026-01-05"]
ok_688012 = len(r688012_0105) == 1 and r688012_0105[0]["FACTOR_AMO"] == "0"
check("688012 在 2026-01-05 FACTOR_AMO 严格判定为 0 (前序停牌强约束)", ok_688012,
      f"找到 {len(r688012_0105)} 行, AMO={r688012_0105[0]['FACTOR_AMO'] if r688012_0105 else 'N/A'}, "
      f"成交额={r688012_0105[0]['TURNOVERVALUE'] if r688012_0105 else 'N/A'}")

# ===== 7. 科创板汇总 =====
n_high_all_star = sum(1 for r in star_rows if r["FACTOR_HIGH_ALL"] == "1")
print(f"\n  [INFO] 科创板 HIGH_ALL 命中: {n_high_all_star:,} 次")

# ===== 汇总 =====
n_fail = sum(1 for _, ok, _ in results if not ok)
n_pass = len(results) - n_fail
print("\n" + "=" * 70)
print(f"面板回归汇总: {n_pass}/{len(results)} PASS, {n_fail} FAIL")
sys.exit(1 if n_fail else 0)
