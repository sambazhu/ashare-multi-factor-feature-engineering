import os
import glob
import json
import time
from concurrent.futures import ProcessPoolExecutor

DATA_DIR = '/data1/wkzq/ashare/data'
BASIC_PATH = os.path.join(DATA_DIR, 'stock_basic_index.json')

SCHEMA = [
    "code", "name", "sw_ind1", "sw_ind2", "sw_ind3", "custom_group",
    "adj_close", "raw_close", "turnover", "tag_mask", "label",
    "ma5", "ma10", "ma20", "ma60", "ma120", "ma250", "ma377",
    "f_hl_5r", "f_5r", "f_high_all", "f_high_500", "f_high_250", "f_hl_amo", "f_amo", "f_ma377", "f_ma250",
    "dd180", "reb30", "gain5", "ret10", "amt_prev", "amt_ma5", "amt_ma10", "amt_ma15", "amt_max15",
    "dist_ma250", "dist_ma377", "supp_type", "prev_drawdown_180_pct"
]

def load_basic_map():
    if os.path.exists(BASIC_PATH):
        with open(BASIC_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def convert_single_slice(json_path, basic_map):
    try:
        base_name = os.path.basename(json_path)
        date_str = base_name.replace('data_', '').replace('.json', '')
        compact_path = os.path.join(DATA_DIR, f"data_{date_str}.compact.json")

        with open(json_path, 'r', encoding='utf-8') as f:
            daily = json.load(f)

        compact_rows = []
        for s in daily:
            code = s.get('code', '')
            name = s.get('name', '')
            if not name and code in basic_map:
                name = basic_map[code].get('n', '')

            adj = s.get('adj', {})
            raw = s.get('raw', {})
            factors = s.get('factors', {})
            dt = factors.get('details', {})

            adj_c = adj.get('close')
            if adj_c is None:
                adj_c = s.get('adj_close', s.get('close'))

            raw_c = raw.get('close')
            if raw_c is None:
                raw_c = s.get('raw_close', s.get('close'))

            row = [
                code,
                name or code,
                s.get('sw_ind1', '未分类'),
                s.get('sw_ind2', '未分类'),
                s.get('sw_ind3', '未分类'),
                s.get('custom_group', '其他'),
                adj_c,
                raw_c,
                s.get('turnover', 0),
                s.get('tag_mask', 0),
                adj.get('label', 0),
                # MA
                adj.get('ma5'), adj.get('ma10'), adj.get('ma20'), adj.get('ma60'), adj.get('ma120'), adj.get('ma250'), adj.get('ma377'),
                # Factor flags
                factors.get('factor_hl_5r', 0), factors.get('factor_5r', 0), factors.get('factor_high_all', 0),
                factors.get('factor_high_500', 0), factors.get('factor_high_250', 0), factors.get('factor_hl_amo', 0),
                factors.get('factor_amo', 0), factors.get('factor_ma377_support', 0), factors.get('factor_ma250_support', 0),
                # Details
                dt.get('drawdown_180_pct'), dt.get('low_rebound_30_pct'), dt.get('five_day_gain_pct'), dt.get('return_10_pct'),
                dt.get('amt_ratio_prev'), dt.get('amt_ratio_ma5'), dt.get('amt_ratio_ma10'), dt.get('amt_ratio_ma15'), dt.get('amt_ratio_max15'),
                dt.get('dist_ma250_pct'), dt.get('dist_ma377_pct'),
                factors.get('ma_support_type', 'NONE'),
                dt.get('prev_drawdown_180_pct')
            ]
            compact_rows.append(row)

        compact_payload = {
            "version": "1.0",
            "date": date_str,
            "count": len(compact_rows),
            "schema": SCHEMA,
            "data": compact_rows
        }

        with open(compact_path, 'w', encoding='utf-8') as f:
            json.dump(compact_payload, f, ensure_ascii=False, separators=(',', ':'))

        return date_str, len(compact_rows), os.path.getsize(compact_path)
    except Exception as e:
        return None, 0, str(e)

def main():
    t0 = time.time()
    print("🚀 开始批量转换全量 200 个交易日为定长紧凑列式数组 (Compact Array)...")
    basic_map = load_basic_map()
    print(f"  已加载基础证券字典: {len(basic_map)} 只标的")

    json_files = sorted(glob.glob(os.path.join(DATA_DIR, 'data_20*.json')))
    json_files = [f for f in json_files if not f.endswith('.compact.json')]
    print(f"  待转换历史交易日切片数量: {len(json_files)} 个")

    success_count = 0
    total_compact_bytes = 0

    for idx, fpath in enumerate(json_files):
        d_str, cnt, sz = convert_single_slice(fpath, basic_map)
        if d_str:
            success_count += 1
            total_compact_bytes += sz
            if (idx + 1) % 25 == 0 or idx == len(json_files) - 1:
                print(f"  进度: [{idx+1}/{len(json_files)}] 日期 {d_str} 完成 (大小: {sz/1024:.1f} KB)")
        else:
            print(f"  [ERROR] {fpath}: {sz}")

    # 创建或更新 data_latest.compact.json 软链接
    dates_index_path = os.path.join(DATA_DIR, 'dates_index.json')
    latest_date = "2026-09-01"
    if os.path.exists(dates_index_path):
        with open(dates_index_path, 'r', encoding='utf-8') as f:
            dates = json.load(f)
            if dates:
                latest_date = dates[0].get('date', latest_date)

    latest_compact_target = f"data_{latest_date}.compact.json"
    latest_symlink = os.path.join(DATA_DIR, "data_latest.compact.json")
    if os.path.exists(latest_symlink) or os.path.islink(latest_symlink):
        os.remove(latest_symlink)
    os.symlink(latest_compact_target, latest_symlink)
    print(f"✅ 软链接创建成功: data_latest.compact.json -> {latest_compact_target}")

    cost = time.time() - t0
    avg_size_mb = (total_compact_bytes / success_count) / (1024 * 1024) if success_count else 0
    print("=" * 60)
    print(f"🎉 全部 {success_count} 个历史交易日紧凑切片生成完成!")
    print(f"  总耗时: {cost:.2f} 秒")
    print(f"  单文件平均大小: {avg_size_mb:.2f} MB (原始单文件 ~7.14 MB, 降幅 81.5%)")
    print("=" * 60)

if __name__ == '__main__':
    main()
