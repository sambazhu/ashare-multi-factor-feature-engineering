#!/usr/bin/env python3
"""
生成演示用的近 15 交易日双口径切片数据与索引 (adj 比例复权 vs raw 未复权)
修补 raw 模式下 close 价格字段缺失的问题。
"""
import os
import csv
import json
import copy
from datetime import datetime, timedelta

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
    adj_csv = os.path.join(base_dir, "ma_features_adj.csv")
    full_csv = os.path.join(base_dir, "ma_features_full.csv")

    adj_rows = {r["SECUCODE"]: r for r in load_csv(adj_csv)}
    full_rows = {r["SECUCODE"]: r for r in load_csv(full_csv)}

    data_dir = os.path.join(base_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    all_codes = sorted(list(set(list(adj_rows.keys()) + list(full_rows.keys()))))
    combined_rows = []

    for code in all_codes:
        a_item = adj_rows.get(code, {})
        f_item = full_rows.get(code, {})
        item = a_item if a_item else f_item

        # Raw Close Price is in a_item["CLOSEPRICE"] or f_item["CLOSEPRICE"]
        raw_close_val = a_item.get("CLOSEPRICE") or f_item.get("CLOSEPRICE")
        adj_close_val = a_item.get("ADJ_CLOSE") or raw_close_val

        adj_mode = {
            "close": adj_close_val,
            "raw_close": raw_close_val,
            "adj_close": adj_close_val,
            "ma5": a_item.get("MA5"), "ma10": a_item.get("MA10"), "ma20": a_item.get("MA20"),
            "ma60": a_item.get("MA60"), "ma120": a_item.get("MA120"), "ma250": a_item.get("MA250"),
            "prev_ma5": a_item.get("PREV_MA5"), "prev_ma10": a_item.get("PREV_MA10"), "prev_ma20": a_item.get("PREV_MA20"),
            "prev_ma60": a_item.get("PREV_MA60"), "prev_ma120": a_item.get("PREV_MA120"), "prev_ma250": a_item.get("PREV_MA250"),
            "align_t0": a_item.get("ALIGN_T0", 0),
            "align_t1": a_item.get("ALIGN_T1", 0),
            "all_up": a_item.get("ALL_UP", 0),
            "label": a_item.get("LABEL", 0)
        }

        raw_mode = {
            "close": raw_close_val,
            "raw_close": raw_close_val,
            "adj_close": adj_close_val,
            "ma5": f_item.get("MA5"), "ma10": f_item.get("MA10"), "ma20": f_item.get("MA20"),
            "ma60": f_item.get("MA60"), "ma120": f_item.get("MA120"), "ma250": f_item.get("MA250"),
            "prev_ma5": f_item.get("PREV_MA5"), "prev_ma10": f_item.get("PREV_MA10"), "prev_ma20": f_item.get("PREV_MA20"),
            "prev_ma60": f_item.get("PREV_MA60"), "prev_ma120": f_item.get("PREV_MA120"), "prev_ma250": f_item.get("PREV_MA250"),
            "align_t0": f_item.get("ALIGN_T0", 0),
            "align_t1": f_item.get("ALIGN_T1", 0),
            "all_up": f_item.get("ALL_UP", 0),
            "label": f_item.get("LABEL", 0)
        }

        entry = {
            "code": code,
            "name": item.get("SECNAME", ""),
            "sw_ind1": item.get("SW_IND1", "未分类"),
            "sw_ind2": item.get("SW_IND2", "未分类"),
            "t0": item.get("T0", "2026-07-31"),
            "prev_day": item.get("PREV_DAY", "2026-07-30"),
            "day_gap": item.get("DAY_GAP", 1),
            "history_days": item.get("HISTORY_DAYS", 268),
            "adj": adj_mode,
            "raw": raw_mode
        }
        combined_rows.append(entry)

    # Dates
    base_date = datetime.strptime("2026-07-31", "%Y-%m-%d")
    dates = []
    curr = base_date
    while len(dates) < 15:
        if curr.weekday() < 5: dates.append(curr.strftime("%Y-%m-%d"))
        curr -= timedelta(days=1)

    dates_index = []
    stock_summary = {}

    for d in dates:
        slice_rows = copy.deepcopy(combined_rows)
        for item in slice_rows: item["t0"] = d
        
        file_path = os.path.join(data_dir, f"data_{d}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(slice_rows, f, ensure_ascii=False)

        lbl1_adj = sum(1 for item in slice_rows if item["adj"].get("label") == 1)
        lbl1_raw = sum(1 for item in slice_rows if item["raw"].get("label") == 1)
        
        dates_index.append({
            "date": d,
            "total": len(slice_rows),
            "adj_label1_count": lbl1_adj,
            "raw_label1_count": lbl1_raw,
            "label1_count": lbl1_adj, # default
        })

    for r in combined_rows:
        code = r["code"]
        lbl_adj = r["adj"].get("label", 0)
        lbl_raw = r["raw"].get("label", 0)
        stock_summary[code] = {
            "adj_streak": 8 if lbl_adj == 1 else 0,
            "raw_streak": 8 if lbl_raw == 1 else 0,
            "streak": 8 if lbl_adj == 1 else 0
        }

    with open(os.path.join(data_dir, "dates_index.json"), "w", encoding="utf-8") as f:
        json.dump(dates_index, f, ensure_ascii=False, indent=2)

    with open(os.path.join(data_dir, "stock_200d_summary.json"), "w", encoding="utf-8") as f:
        json.dump(stock_summary, f, ensure_ascii=False)

    print("[Done] 双口径演示数据切片与索引补全成功！")

if __name__ == "__main__":
    main()
