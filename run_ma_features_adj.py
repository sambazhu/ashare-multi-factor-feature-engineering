#!/usr/bin/env python3
"""
执行 ma_features_adj.sql (基于聚源复权价格)，导出全市场 A 股均线特征矩阵与标签 CSV。
产物: ma_features_adj.csv
"""
import os
import time
import csv
import oracledb

import oracle_jydb_helper

def main():
    t_start = time.time()
    print("[1/3] 初始化 Oracle Instant Client 与数据库连接...")
    conn = oracle_jydb_helper.get_connection()
    cur = conn.cursor()

    sql_file = os.path.join(os.path.dirname(__file__), "ma_features_adj.sql")
    with open(sql_file, "r", encoding="utf-8") as f:
        sql = f.read().strip()
    if sql.endswith(";"):
        sql = sql[:-1]

    print("[2/3] 执行复权均线特征工程 SQL Query (包含 4591 只 A 股全市场)...")
    cur.execute(sql)
    headers = [col[0] for col in cur.description]
    rows = cur.fetchall()

    out_csv = os.path.join(os.path.dirname(__file__), "ma_features_adj.csv")
    print(f"[3/3] 写入 CSV 产物: {out_csv} (共 {len(rows)} 行, {len(headers)} 列)...")
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

    label1_cnt = sum(1 for r in rows if r[-1] == 1)
    t_cost = time.time() - t_start
    print("\n=================== 结果汇总 ===================")
    print(f"执行耗时: {t_cost:.2f} 秒")
    print(f"总标的数: {len(rows)} 只 A 股")
    print(f"LABEL=1 命中数: {label1_cnt} 只")
    print("Hit Stock Samples (LABEL=1):")
    for r in rows:
        if r[-1] == 1:
            print(f" - {r[0]} {r[1]}: 收盘={r[6]}, 复权={r[7]}, MA5={r[8]}, MA10={r[9]}, MA20={r[10]}, MA60={r[11]}, MA120={r[12]}, MA250={r[13]}")

    conn.close()

if __name__ == "__main__":
    main()
