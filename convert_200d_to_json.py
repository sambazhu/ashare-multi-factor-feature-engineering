import os
import sys
import json
import csv
import time
from collections import defaultdict

# -------------------------------------------------------------
# 申万行业映射加载
# -------------------------------------------------------------
def load_sw_map(map_file):
    if not os.path.exists(map_file):
        return {}
    with open(map_file, "r", encoding="utf-8") as f:
        return json.load(f)

def load_custom_groups(custom_file):
    if not os.path.exists(custom_file):
        return {"groups": [], "mapping": {}}
    with open(custom_file, "r", encoding="utf-8") as f:
        return json.load(f)

# -------------------------------------------------------------
# 读取 200 交易日全量面板 CSV
# -------------------------------------------------------------
def load_csv_rows(csv_path):
    rows = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    return rows

def parse_float(val):
    if val is None or val == "" or val == "None" or val == "null":
        return None
    try:
        return round(float(val), 4)
    except:
        return None

def build_entry(row, sw_info, custom_mapping):
    code = row["SECUCODE"]
    name = row.get("SECUNAME", "")
    
    sw_1 = sw_info.get("sw_ind1") or row.get("SW_IND1") or "未分类"
    sw_2 = sw_info.get("sw_ind2") or row.get("SW_IND2") or "未分类"
    sw_3 = sw_info.get("sw_ind3") or row.get("SW_IND3") or "未分类"
    
    custom_grp = custom_mapping.get(sw_1, "其他") if sw_1 != "未分类" else "未分类"

    raw_close = parse_float(row.get("RAW_CLOSEPRICE") or row.get("CLOSEPRICE"))
    adj_close = parse_float(row.get("ADJ_CLOSE") or row.get("CLOSEPRICE"))
    turnover = parse_float(row.get("TURNOVERVALUE"))

    # 9 大核心策略因子布尔标记
    f_hl_5r = int(row.get("FACTOR_HL_5R") or 0)
    f_5r = int(row.get("FACTOR_5R") or 0)
    f_high_all = int(row.get("FACTOR_HIGH_ALL") or 0)
    f_high_500 = int(row.get("FACTOR_HIGH_500") or 0)
    f_high_250 = int(row.get("FACTOR_HIGH_250") or 0)
    f_hl_amo = int(row.get("FACTOR_HL_AMO") or 0)
    f_amo = int(row.get("FACTOR_AMO") or 0)
    f_ma377 = int(row.get("FACTOR_MA377_SUPPORT") or 0)
    f_ma250 = int(row.get("FACTOR_MA250_SUPPORT") or 0)
    adj_label = int(row.get("LABEL") or 0)

    primary = row.get("PRIMARY_FACTOR") or "NONE"
    high_type = row.get("HIGH_TYPE") or "NONE"
    ma_support_type = row.get("MA_SUPPORT_TYPE") or "NONE"

    active_factors = []
    if f_hl_5r == 1: active_factors.append("HL_5R")
    elif f_5r == 1: active_factors.append("5R")

    if f_high_all == 1: active_factors.append("HIGH_ALL")
    if f_high_500 == 1: active_factors.append("HIGH_500")
    if f_high_250 == 1: active_factors.append("HIGH_250")

    if f_hl_amo == 1: active_factors.append("HL_AMO")
    if f_amo == 1: active_factors.append("AMO")

    if f_ma377 == 1: active_factors.append("MA377_SUPPORT")
    if f_ma250 == 1: active_factors.append("MA250_SUPPORT")

    if adj_label == 1: active_factors.append("MA_BULLISH")

    # Bitmask 多因子位掩码编码（同类精简 + 异类完全并行）
    # Bit 0 (1): HL+5R
    # Bit 1 (2): 5R
    # Bit 2 (4): HIGH_ALL
    # Bit 3 (8): HIGH_500
    # Bit 4 (16): HIGH_250
    # Bit 5 (32): HL_AMO
    # Bit 6 (64): AMO (仅当非 HL_AMO 时)
    # Bit 7 (128): MA377
    # Bit 8 (256): MA250
    # Bit 9 (512): MA_BULLISH
    tag_mask = 0
    if f_hl_5r == 1:
        tag_mask |= 1
    elif f_5r == 1:
        tag_mask |= 2

    if f_high_all == 1:
        tag_mask |= 4
    if f_high_500 == 1:
        tag_mask |= 8
    if f_high_250 == 1:
        tag_mask |= 16

    if f_hl_amo == 1:
        tag_mask |= 32
    elif f_amo == 1:
        tag_mask |= 64

    if f_ma377 == 1:
        tag_mask |= 128
    if f_ma250 == 1:
        tag_mask |= 256

    if adj_label == 1:
        tag_mask |= 512

    return {
        "code": code,
        "name": name,
        "sw_ind1": sw_1,
        "sw_ind2": sw_2,
        "sw_ind3": sw_3,
        "custom_group": custom_grp,
        "t0": row.get("T0", ""),
        "prev_day": row.get("PREV_DAY", ""),
        "day_gap": row.get("DAY_GAP", 0),
        "history_days": row.get("HISTORY_DAYS", 0),
        "turnover": turnover,
        "adj_factor": row.get("ADJUSTINGFACTOR"),
        "tag_id": tag_mask,
        "tag_mask": tag_mask,

        "factors": {
            "primary": primary,
            "high_type": high_type,
            "ma_support_type": ma_support_type,
            "active": active_factors,
            "factor_hl_5r": f_hl_5r,
            "factor_5r": f_5r,
            "factor_high_all": f_high_all,
            "factor_high_500": f_high_500,
            "factor_high_250": f_high_250,
            "factor_hl_amo": f_hl_amo,
            "factor_amo": f_amo,
            "factor_ma377_support": f_ma377,
            "factor_ma250_support": f_ma250,
            "details": {
                "drawdown_180_pct": row.get("DRAWDOWN_180_PCT"),
                "low_rebound_30_pct": row.get("LOW_REBOUND_30_PCT"),
                "five_day_gain_pct": row.get("FIVE_DAY_GAIN_PCT"),
                "return_10_pct": row.get("RETURN_10_PCT"),
                "prev_drawdown_180_pct": row.get("PREV_DRAWDOWN_180_PCT"),
                "amt_ratio_prev": row.get("AMT_RATIO_PREV"),
                "amt_ratio_ma5": row.get("AMT_RATIO_MA5"),
                "amt_ratio_ma10": row.get("AMT_RATIO_MA10"),
                "amt_ratio_ma15": row.get("AMT_RATIO_MA15"),
                "amt_ratio_max15": row.get("AMT_RATIO_MAX15"),
                "dist_ma250_pct": row.get("DIST_MA250_PCT"),
                "dist_ma377_pct": row.get("DIST_MA377_PCT")
            }
        },

        "adj": {
            "close": adj_close,
            "raw_close": raw_close,
            "adj_close": adj_close,
            "ma5": row.get("MA5"), "ma10": row.get("MA10"), "ma20": row.get("MA20"),
            "ma60": row.get("MA60"), "ma120": row.get("MA120"), "ma250": row.get("MA250"), "ma377": row.get("MA377"),
            "prev_ma5": row.get("PREV_MA5"), "prev_ma10": row.get("PREV_MA10"), "prev_ma20": row.get("PREV_MA20"),
            "prev_ma60": row.get("PREV_MA60"), "prev_ma120": row.get("PREV_MA120"), "prev_ma250": row.get("PREV_MA250"), "prev_ma377": row.get("PREV_MA377"),
            "align_t0": int(row.get("ALIGN_T0") or 0),
            "align_t1": int(row.get("ALIGN_T1") or 0),
            "all_up": int(row.get("ALL_UP") or 0),
            "label": adj_label
        },

        "raw": {
            "close": raw_close,
            "raw_close": raw_close,
            "adj_close": adj_close,
            "label": adj_label
        }
    }

def main():
    base_dir = '/data1/wkzq/ashare'
    sw_map_file = os.path.join(base_dir, "sw_industry_map.json")
    custom_group_file = os.path.join(base_dir, "sw_custom_group.json")
    adj_200d_csv = os.path.join(base_dir, "ma_features_200d_adj.csv")
    versions_root = os.path.join(base_dir, "data_versions")
    data_target = os.path.join(base_dir, "data")

    ver_tag = time.strftime("%Y%m%d_%H%M%S")
    ver_dir = os.path.join(versions_root, f"ver_{ver_tag}")
    os.makedirs(ver_dir, exist_ok=True)

    print(f"[1/6] 加载申万行业字典与自定义宏观大类配置...")
    sw_map = load_sw_map(sw_map_file)
    custom_groups_data = load_custom_groups(custom_group_file)
    custom_mapping = custom_groups_data.get("mapping", {})
    print(f"  加载申万映射 A 股数: {len(sw_map):,}, 自定义大类覆盖行业: {len(custom_mapping)}")

    with open(os.path.join(ver_dir, "sw_custom_group.json"), "w", encoding="utf-8") as f:
        json.dump(custom_groups_data, f, ensure_ascii=False, indent=2)

    # 自动继承全量 A 股基础证券字典与产业链全景画像数据，防止每日切片覆盖
    import shutil
    for static_file in ["stock_basic_index.json", "stock_profiles_summary.json"]:
        master_src = os.path.join(base_dir, static_file)
        if os.path.exists(master_src):
            shutil.copy2(master_src, os.path.join(ver_dir, static_file))
            print(f"  [继承归档] 成功同步 {static_file} 到新版本目录")
        else:
            # 兜底：尝试从前一个版本继承
            data_link = os.path.join(base_dir, "data")
            if os.path.exists(data_link):
                prev_src = os.path.join(data_link, static_file)
                if os.path.exists(prev_src):
                    shutil.copy2(prev_src, os.path.join(ver_dir, static_file))
                    print(f"  [继承归档] 从上一版本继承 {static_file}")

    print(f"[2/6] 加载 200 交易日全量面板数据 (ma_features_200d_adj.csv)...")
    adj_rows = load_csv_rows(adj_200d_csv)
    print(f"  加载 {len(adj_rows):,} 行面板数据")

    by_date = defaultdict(list)
    for row in adj_rows:
        date = row.get("T0")
        if date:
            by_date[date].append(row)

    dates_sorted = sorted(by_date.keys(), reverse=True)
    print(f"  共提取 {len(dates_sorted)} 个 A 股交易日: {dates_sorted[0]} ~ {dates_sorted[-1]}")

    if len(dates_sorted) != 200:
        print(f"[FATAL] 交易日数不等于 200 (实际 {len(dates_sorted)})! 中止生成!")
        sys.exit(1)

    print(f"[3/6] 写入独立版本目录 ({ver_dir}) 每日 9 大核心因子 JSON 切片...")
    dates_index = []
    date_code_entry = {}

    for date in dates_sorted:
        day_rows = by_date[date]
        entries = []
        code_map = {}
        kcb_in_day = 0
        kcb_turnover_day = 0
        for row in day_rows:
            code = row["SECUCODE"]
            if code.startswith("68"):
                kcb_in_day += 1
                t_val = parse_float(row.get("TURNOVERVALUE")) or 0
                if t_val > 0:
                    kcb_turnover_day += 1
            sw_info = sw_map.get(code, {})
            entry = build_entry(row, sw_info, custom_mapping)
            entries.append(entry)
            code_map[code] = entry

        date_code_entry[date] = code_map

        file_path = os.path.join(ver_dir, f"data_{date}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False)

        adj_label1 = sum(1 for e in entries if e["adj"]["label"] == 1)

        dates_index.append({
            "date": date,
            "total": len(entries),
            "kcb_count": kcb_in_day,
            "kcb_with_turnover": kcb_turnover_day,
            "label1_count": adj_label1,
            "factor_hl_5r_count": sum(1 for e in entries if e["factors"]["factor_hl_5r"] == 1),
            "factor_5r_count": sum(1 for e in entries if e["factors"]["factor_5r"] == 1),
            "factor_high_all_count": sum(1 for e in entries if e["factors"]["factor_high_all"] == 1),
            "factor_high_500_count": sum(1 for e in entries if e["factors"]["factor_high_500"] == 1),
            "factor_high_250_count": sum(1 for e in entries if e["factors"]["factor_high_250"] == 1),
            "factor_hl_amo_count": sum(1 for e in entries if e["factors"]["factor_hl_amo"] == 1),
            "factor_amo_count": sum(1 for e in entries if e["factors"]["factor_amo"] == 1),
            "factor_ma377_count": sum(1 for e in entries if e["factors"]["factor_ma377_support"] == 1),
            "factor_ma250_count": sum(1 for e in entries if e["factors"]["factor_ma250_support"] == 1)
        })

    print(f"[4/6] 构建 90 交易日 Bitmask 轻量化历史矩阵 history_matrix.json ...")
    matrix_dates = dates_sorted[:90]
    all_codes = sorted(list(set(r["SECUCODE"] for r in adj_rows)))
    matrix_data = {}
    multi_factor_count = 0
    for code in all_codes:
        row_tags = []
        for d in matrix_dates:
            entry = date_code_entry[d].get(code)
            if entry is None:
                row_tags.append(-1)
            else:
                mask = entry.get("tag_mask", 0)
                row_tags.append(mask)
                if bin(mask).count('1') >= 2:
                    multi_factor_count += 1
        matrix_data[code] = row_tags

    history_matrix_payload = {
        "dates": matrix_dates,
        "span": len(matrix_dates),
        "tag_legend": {
            "-1": "未上市/停牌",
            "0": "-",
            "1": "HL+5R",
            "2": "5R",
            "4": "新高",
            "8": "500高",
            "16": "250高",
            "32": "HL+AMO",
            "64": "AMO",
            "128": "MA377",
            "256": "MA250",
            "512": "多头"
        },
        "matrix": matrix_data
    }
    with open(os.path.join(ver_dir, "history_matrix.json"), "w", encoding="utf-8") as f:
        json.dump(history_matrix_payload, f, ensure_ascii=False)
    print(f"  已生成 90 交易日 Bitmask 矩阵, 股票数: {len(matrix_data):,}, 多因子并存单元格数: {multi_factor_count:,}, 体积: {os.path.getsize(os.path.join(ver_dir, 'history_matrix.json')) / 1024:.1f} KB")

    print(f"[5/6] 计算连续多头并生成 stock_200d_summary.json ...")
    stock_summary = {}
    for code in all_codes:
        streak = 0
        for date in dates_sorted:
            entry = date_code_entry[date].get(code)
            if entry and entry["adj"]["label"] == 1:
                streak += 1
            else:
                break
        stock_summary[code] = {
            "streak": streak,
            "adj_streak": streak,
            "raw_streak": streak
        }

    with open(os.path.join(ver_dir, "dates_index.json"), "w", encoding="utf-8") as f:
        json.dump(dates_index, f, ensure_ascii=False, indent=2)

    with open(os.path.join(ver_dir, "stock_200d_summary.json"), "w", encoding="utf-8") as f:
        json.dump(stock_summary, f, ensure_ascii=False)

    base_preceding_tdays = 316
    total_cov_days = base_preceding_tdays + len(dates_sorted)
    
    meta_info = {
        "coverage_start": "2024-07-10",
        "coverage_end": dates_sorted[0],
        "total_coverage_days": total_cov_days,
        "snapshot_count": len(dates_sorted),
        "total_stocks_latest": len(date_code_entry[dates_sorted[0]]),
        "default_span": 90
    }
    with open(os.path.join(ver_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta_info, f, ensure_ascii=False, indent=2)

    print(f"[6/6] 执行原子软链接切换 (POSIX os.replace) -> {data_target}...")
    tmp_symlink = os.path.join(base_dir, f"data_symlink_tmp_{ver_tag}")
    os.symlink(ver_dir, tmp_symlink)
    os.replace(tmp_symlink, data_target)
    print(f"  原子切换成功! 当前 data -> {ver_dir}")

    # 清理多余历史版本，保留最近 5 个
    all_vers = sorted([d for d in os.listdir(versions_root) if d.startswith("ver_")])
    if len(all_vers) > 5:
        import shutil
        for old_v in all_vers[:-5]:
            old_p = os.path.join(versions_root, old_v)
            shutil.rmtree(old_p)
            print(f"  清理历史版本: {old_v}")

    print("\n" + "=" * 60)
    print(f"✅ 全量 200 日多因子 JSON 与 90 交易日 Bitmask 轻量矩阵切片生成完毕!")
    print("=" * 60)

if __name__ == "__main__":
    main()
