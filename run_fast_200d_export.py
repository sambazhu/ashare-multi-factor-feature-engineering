#!/usr/bin/env python3
"""
高效率 200 交易日「全量 9 大核心策略因子 + 均线系统」全量面板导出
基于 CS_StockAdjPerformance(1,1) 前复权精确复权主口径，包含 60/68/00/30 全市场 A 股
产物: ma_features_200d_adj.csv
"""
import os
import time
import csv
import oracledb

import oracle_jydb_helper

def main():
    t_start = time.time()
    print("=" * 75)
    print("A 股 200 交易日「全量 9 大核心策略因子 + 均线系统」全市场面板导出 (CS_StockAdjPerformance)")
    print("=" * 75)

    print("[1/4] 初始化 Oracle 连接并读取 SQL 模板...")
    conn = oracle_jydb_helper.get_connection()
    cur = conn.cursor()
    cur.arraysize = 5000
    cur.prefetchrows = 5000

    sql_file = os.path.join(os.path.dirname(__file__), "ma_features_200d_adj.sql")
    with open(sql_file, "r", encoding="utf-8") as f:
        sql = f.read()

    print("[2/4] 执行 Oracle 全量 9 大因子特征抽取 Query...")
    cur.execute(sql)
    headers = [col[0] for col in cur.description]

    out_csv = os.path.join(os.path.dirname(__file__), "ma_features_200d_adj.csv")
    out_csv_tmp = os.path.join(os.path.dirname(__file__), "ma_features_200d_adj_tmp.csv")
    print(f"[3/4] 流式写入 200 天全量面板临时 CSV: {out_csv_tmp} ...")

    row_count = 0
    kcb_count = 0
    stat_counts = {
        "LABEL": 0,
        "FACTOR_HL_5R": 0,
        "FACTOR_5R": 0,
        "FACTOR_HIGH_ALL": 0,
        "FACTOR_HIGH_500": 0,
        "FACTOR_HIGH_250": 0,
        "FACTOR_HL_AMO": 0,
        "FACTOR_AMO": 0,
        "FACTOR_MA377_SUPPORT": 0,
        "FACTOR_MA250_SUPPORT": 0
    }

    try:
        with open(out_csv_tmp, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(headers)

            while True:
                rows = cur.fetchmany(10000)
                if not rows:
                    break
                row_count += len(rows)
                for row in rows:
                    writer.writerow(row)
                    d = dict(zip(headers, row))
                    if str(d.get("SECUCODE", "")).startswith("68"):
                        kcb_count += 1
                    for k in stat_counts:
                        if d.get(k) == 1:
                            stat_counts[k] += 1

                if row_count % 100000 == 0:
                    print(f"    ... 已流式写入 {row_count:,} 行 (科创板: {kcb_count:,} 行)")

            f.flush()
            os.fsync(f.fileno())
    finally:
        conn.close()

    # 严格校验导出完整性
    if row_count < 1000000 or kcb_count < 100000:
        if os.path.exists(out_csv_tmp):
            os.remove(out_csv_tmp)
        raise RuntimeError(f"导出数据行数不足 (实际 {row_count:,} 行, 科创板 {kcb_count:,} 行)! 拒绝覆盖正式产物!")

    # 原子替换落盘 (POSIX os.replace)
    os.replace(out_csv_tmp, out_csv)
    t_total = time.time() - t_start

    print("[4/4] 导出与原子替换完成!")
    print("-" * 75)
    print(f"总行数: {row_count:,} 行面板数据 (其中科创板 68xxx: {kcb_count:,} 行)")
    print(f"总耗时: {t_total:.2f} 秒 (SQL+网络+落盘)")
    print(f"产物大小: {os.path.getsize(out_csv) / (1024*1024):.2f} MB")
    print("全量 200 日 9 大核心因子命中汇总统计:")
    print(f"  - 均线多头超级排列 (LABEL=1): {stat_counts['LABEL']:,}")
    print(f"  - 1. HL+5R 底部五阳 (FACTOR_HL_5R=1): {stat_counts['FACTOR_HL_5R']:,}")
    print(f"  - 2. 5R 五连阳 (FACTOR_5R=1): {stat_counts['FACTOR_5R']:,}")
    print(f"  - 3. 覆盖期新高 (FACTOR_HIGH_ALL=1): {stat_counts['FACTOR_HIGH_ALL']:,}")
    print(f"  - 4. 500日新高 (FACTOR_HIGH_500=1): {stat_counts['FACTOR_HIGH_500']:,}")
    print(f"  - 5. 250日新高 (FACTOR_HIGH_250=1): {stat_counts['FACTOR_HIGH_250']:,}")
    print(f"  - 6. HL+AMO 底部放量 (FACTOR_HL_AMO=1): {stat_counts['FACTOR_HL_AMO']:,}")
    print(f"  - 7. AMO 放量突破 (FACTOR_AMO=1): {stat_counts['FACTOR_AMO']:,}")
    print(f"  - 8. MA377 均线支撑 (FACTOR_MA377_SUPPORT=1): {stat_counts['FACTOR_MA377_SUPPORT']:,}")
    print(f"  - 9. MA250 均线支撑 (FACTOR_MA250_SUPPORT=1): {stat_counts['FACTOR_MA250_SUPPORT']:,}")
    print("=" * 75)

if __name__ == "__main__":
    main()
