#!/usr/bin/env python3
"""
全市场 A 股均线多头排列特征工程 — 标签规则（LABEL & 中间标记）全面严谨性验证脚本

校验项:
1. 17 项逻辑不等式逐行全面校验 (SQL 计算 vs Python 规则重算 100% 匹配性)
2. 假阳性 (False Positive) 检查: 是否存在 LABEL=1 但不满足任何一条规则的股票
3. 假阴性 (False Negative) 检查: 是否存在完全满足所有规则但 LABEL=0 的股票
4. 边缘边界 (Edge Cases) 校验: 次新股 (HISTORY_DAYS < 250)、停牌股 (DAY_GAP > 7)、微小斜率拐头
5. 详细打印 LABEL=1 命中股票的全量数值明细供审计
"""

import os
import csv

def verify_dataset(filepath, dataset_name):
    print(f"\n=======================================================")
    print(f" 开始验证数据集: {dataset_name} ({filepath})")
    print(f"=======================================================")
    
    if not os.path.exists(filepath):
        print(f"错误: 文件不存在 {filepath}")
        return

    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    total_count = len(rows)
    print(f"读取样本总数: {total_count} 只 A 股")

    fp_count = 0  # False Positives
    fn_count = 0  # False Negatives
    align_t0_mismatch = 0
    align_t1_mismatch = 0
    all_up_mismatch = 0
    label_mismatch = 0

    label1_stocks = []

    for idx, r in enumerate(rows):
        code = r.get("SECUCODE")
        name = r.get("SECNAME")
        t0 = r.get("T0")
        prev_day = r.get("PREV_DAY")
        day_gap = int(r.get("DAY_GAP")) if r.get("DAY_GAP") else 999
        history_days = int(r.get("HISTORY_DAYS")) if r.get("HISTORY_DAYS") else 0

        # Parse MAs (if empty string, set None)
        def parse_float(val):
            return float(val) if val != "" and val is not None else None

        ma5 = parse_float(r.get("MA5"))
        ma10 = parse_float(r.get("MA10"))
        ma20 = parse_float(r.get("MA20"))
        ma60 = parse_float(r.get("MA60"))
        ma120 = parse_float(r.get("MA120"))
        ma250 = parse_float(r.get("MA250"))

        p_ma5 = parse_float(r.get("PREV_MA5"))
        p_ma10 = parse_float(r.get("PREV_MA10"))
        p_ma20 = parse_float(r.get("PREV_MA20"))
        p_ma60 = parse_float(r.get("PREV_MA60"))
        p_ma120 = parse_float(r.get("PREV_MA120"))
        p_ma250 = parse_float(r.get("PREV_MA250"))

        align_t0_sql = int(r.get("ALIGN_T0")) if r.get("ALIGN_T0") else 0
        align_t1_sql = int(r.get("ALIGN_T1")) if r.get("ALIGN_T1") else 0
        all_up_sql = int(r.get("ALL_UP")) if r.get("ALL_UP") else 0
        label_sql = int(r.get("LABEL")) if r.get("LABEL") else 0

        # --- Re-calculate in Python using precise mathematical definitions ---
        
        # 1. ALIGN_T0 check
        cond_t0 = False
        if history_days >= 250 and ma5 is not None and ma10 is not None and ma20 is not None and ma60 is not None and ma120 is not None and ma250 is not None:
            if (ma5 > ma10) and (ma10 > ma20) and (ma20 > ma60) and (ma60 > ma120) and (ma120 > ma250):
                cond_t0 = True

        align_t0_py = 1 if cond_t0 else 0

        # 2. ALIGN_T1 check
        cond_t1 = False
        if history_days >= 250 and p_ma5 is not None and p_ma10 is not None and p_ma20 is not None and p_ma60 is not None and p_ma120 is not None and p_ma250 is not None:
            if (p_ma5 > p_ma10) and (p_ma10 > p_ma20) and (p_ma20 > p_ma60) and (p_ma60 > p_ma120) and (p_ma120 > p_ma250):
                cond_t1 = True

        align_t1_py = 1 if cond_t1 else 0

        # 3. ALL_UP check (Slope > 0 for all 6 MAs)
        cond_up = False
        if history_days >= 250 and all(x is not None for x in [ma5, ma10, ma20, ma60, ma120, ma250, p_ma5, p_ma10, p_ma20, p_ma60, p_ma120, p_ma250]):
            if (ma5 > p_ma5) and (ma10 > p_ma10) and (ma20 > p_ma20) and (ma60 > p_ma60) and (ma120 > p_ma120) and (ma250 > p_ma250):
                cond_up = True

        all_up_py = 1 if cond_up else 0

        # 4. Comprehensive LABEL check
        cond_label = cond_t0 and cond_t1 and cond_up and (day_gap <= 7) and (history_days >= 250)
        label_py = 1 if cond_label else 0

        # --- Compare SQL output vs Python recalculated values ---
        if align_t0_sql != align_t0_py:
            align_t0_mismatch += 1
            print(f"  [MISMATCH ALIGN_T0] {code} {name}: SQL={align_t0_sql}, PY={align_t0_py}")

        if align_t1_sql != align_t1_py:
            align_t1_mismatch += 1
            print(f"  [MISMATCH ALIGN_T1] {code} {name}: SQL={align_t1_sql}, PY={align_t1_py}")

        if all_up_sql != all_up_py:
            all_up_mismatch += 1
            print(f"  [MISMATCH ALL_UP] {code} {name}: SQL={all_up_sql}, PY={all_up_py}")

        if label_sql != label_py:
            label_mismatch += 1
            if label_sql == 1 and label_py == 0:
                fp_count += 1
                print(f"  [FALSE POSITIVE LABEL=1] {code} {name}: SQL=1, PY=0 (gap={day_gap}, days={history_days})")
            elif label_sql == 0 and label_py == 1:
                fn_count += 1
                print(f"  [FALSE NEGATIVE LABEL=0] {code} {name}: SQL=0, PY=1 (gap={day_gap}, days={history_days})")

        if label_sql == 1:
            label1_stocks.append({
                "code": code, "name": name, "t0": t0, "prev_day": prev_day,
                "days": history_days, "gap": day_gap,
                "ma5": ma5, "ma10": ma10, "ma20": ma20, "ma60": ma60, "ma120": ma120, "ma250": ma250,
                "p_ma5": p_ma5, "p_ma10": p_ma10, "p_ma20": p_ma20, "p_ma60": p_ma60, "p_ma120": p_ma120, "p_ma250": p_ma250
            })

    print(f"\n--- {dataset_name} 校验逻辑汇总结果 ---")
    print(f"  样本总行数: {total_count}")
    print(f"  ALIGN_T0 匹配不一致数: {align_t0_mismatch}")
    print(f"  ALIGN_T1 匹配不一致数: {align_t1_mismatch}")
    print(f"  ALL_UP   匹配不一致数: {all_up_mismatch}")
    print(f"  LABEL    匹配不一致数: {label_mismatch} (假阳性={fp_count}, 假阴性={fn_count})")
    
    if label_mismatch == 0 and align_t0_mismatch == 0 and align_t1_mismatch == 0 and all_up_mismatch == 0:
        print(f"  ✅【完美通过】数据集 {dataset_name} 的 17 项多头排列与斜率规则 100% 精确无误！")
    else:
        print(f"  ❌【警告】数据集 {dataset_name} 存在规则不一致，请核查以上打印!")

    print(f"\n--- LABEL=1 (多头排列命中股票审计, 共 {len(label1_stocks)} 只) ---")
    for idx, s in enumerate(label1_stocks, 1):
        print(f"{idx:2d}. {s['code']} {s['name']:14s} | 上市{s['days']}天 Gap={s['gap']} | "
              f"T0均线: {s['ma5']:.2f}>{s['ma10']:.2f}>{s['ma20']:.2f}>{s['ma60']:.2f}>{s['ma120']:.2f}>{s['ma250']:.2f} | "
              f"斜率: MA5({s['ma5']:.2f}>{s['p_ma5']:.2f}), MA250({s['ma250']:.2f}>{s['p_ma250']:.2f})")

def main():
    base_dir = os.path.dirname(__file__)
    full_csv = os.path.join(base_dir, "ma_features_full.csv")
    adj_csv = os.path.join(base_dir, "ma_features_adj.csv")

    verify_dataset(full_csv, "未复权矩阵 (ma_features_full.csv)")
    verify_dataset(adj_csv, "比例复权矩阵 (ma_features_adj.csv)")

if __name__ == "__main__":
    main()
