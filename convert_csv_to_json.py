#!/usr/bin/env python3
"""
融合 ma_features_adj.csv (比例复权) 和 ma_features_full.csv (未复权) 
导出包含双口径特征的 stock_features_data.js 数据包。
"""
import os
import csv
import json

def load_csv(filepath):
    data = []
    if not os.path.exists(filepath):
        return data
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        str_fields = {"SECUCODE", "SECNAME", "SW_IND1", "SW_IND2", "T0", "PREV_DAY"}
        int_fields = {"DAY_GAP", "HISTORY_DAYS", "ALIGN_T0", "ALIGN_T1", "ALL_UP", "LABEL"}
        for row in reader:
            parsed = {}
            for k, v in row.items():
                if v == "" or v is None:
                    parsed[k] = None
                elif k in str_fields:
                    parsed[k] = v
                elif k in int_fields:
                    parsed[k] = int(float(v)) if v else 0
                else:
                    try:
                        parsed[k] = float(v)
                    except (ValueError, TypeError):
                        parsed[k] = v
            data.append(parsed)
    return data

def main():
    base_dir = os.path.dirname(__file__)
    full_csv = os.path.join(base_dir, "ma_features_full.csv")
    adj_csv = os.path.join(base_dir, "ma_features_adj.csv")

    full_data = load_csv(full_csv)
    adj_data = load_csv(adj_csv)

    full_map = {item["SECUCODE"]: item for item in full_data}
    adj_map = {item["SECUCODE"]: item for item in adj_data}

    all_codes = sorted(list(set(list(full_map.keys()) + list(adj_map.keys()))))
    combined = []

    for code in all_codes:
        f_item = full_map.get(code, {})
        a_item = adj_map.get(code, {})
        item = a_item if a_item else f_item

        entry = {
            "code": code,
            "name": item.get("SECNAME", ""),
            "sw_ind1": item.get("SW_IND1", "未分类"),
            "sw_ind2": item.get("SW_IND2", "未分类"),
            "t0": item.get("T0", ""),
            "prev_day": item.get("PREV_DAY", ""),
            "day_gap": item.get("DAY_GAP", 0),
            "history_days": item.get("HISTORY_DAYS", 0),
            
            # Dual Mode Features: adj (比例复权) vs raw (未复权)
            # adj 模式: close = ADJ_CLOSE (复权后收盘价), 均线也是复权均线
            # raw 模式: close = CLOSEPRICE (未复权原始收盘价), 均线是未复权均线
            "adj": {
                "close": a_item.get("ADJ_CLOSE") or a_item.get("CLOSEPRICE"),
                "raw_close": a_item.get("CLOSEPRICE"),
                "adj_close": a_item.get("ADJ_CLOSE"),
                "ma5": a_item.get("MA5"), "ma10": a_item.get("MA10"), "ma20": a_item.get("MA20"),
                "ma60": a_item.get("MA60"), "ma120": a_item.get("MA120"), "ma250": a_item.get("MA250"),
                "prev_ma5": a_item.get("PREV_MA5"), "prev_ma10": a_item.get("PREV_MA10"), "prev_ma20": a_item.get("PREV_MA20"),
                "prev_ma60": a_item.get("PREV_MA60"), "prev_ma120": a_item.get("PREV_MA120"), "prev_ma250": a_item.get("PREV_MA250"),
                "align_t0": a_item.get("ALIGN_T0", 0),
                "align_t1": a_item.get("ALIGN_T1", 0),
                "all_up": a_item.get("ALL_UP", 0),
                "label": a_item.get("LABEL", 0)
            },
            "raw": {
                "close": a_item.get("CLOSEPRICE") or f_item.get("CLOSEPRICE"),
                "raw_close": a_item.get("CLOSEPRICE") or f_item.get("CLOSEPRICE"),
                "adj_close": a_item.get("ADJ_CLOSE"),
                "ma5": f_item.get("MA5"), "ma10": f_item.get("MA10"), "ma20": f_item.get("MA20"),
                "ma60": f_item.get("MA60"), "ma120": f_item.get("MA120"), "ma250": f_item.get("MA250"),
                "prev_ma5": f_item.get("PREV_MA5"), "prev_ma10": f_item.get("PREV_MA10"), "prev_ma20": f_item.get("PREV_MA20"),
                "prev_ma60": f_item.get("PREV_MA60"), "prev_ma120": f_item.get("PREV_MA120"), "prev_ma250": f_item.get("PREV_MA250"),
                "align_t0": f_item.get("ALIGN_T0", 0),
                "align_t1": f_item.get("ALIGN_T1", 0),
                "all_up": f_item.get("ALL_UP", 0),
                "label": f_item.get("LABEL", 0)
            }
        }
        combined.append(entry)

    js_file = os.path.join(base_dir, "stock_features_data.js")
    with open(js_file, "w", encoding="utf-8") as f:
        f.write("// Dual-Mode A-Share Features Data (Adjusted vs Unadjusted)\n")
        f.write("window.STOCK_MA_DATA = ")
        json.dump(combined, f, ensure_ascii=False, indent=2)
        f.write(";\n")

    print(f"Successfully generated {js_file} with {len(combined)} dual-mode stock records.")

if __name__ == "__main__":
    main()
