#!/usr/bin/env python3
"""
执行 ma_features_200d_adj.sql，抽取全市场 A 股最近 200 个交易日的面板特征与标签，并导出 CSV。
产物: ma_features_200d_adj.csv (约 91.8 万行)
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

    sql_file = os.path.join(os.path.dirname(__file__), "ma_features_200d_adj.sql")
    with open(sql_file, "r", encoding="utf-8") as f:
        sql = f.read().strip()
    if sql.endswith(";"):
        sql = sql[:-1]

    print("[2/3] 执行 200 交易日复权均线特征工程 SQL (面板数据量约 90 万行)...")
    cur.execute(sql)
    headers = [col[0] for col in cur.description]
    
    out_csv = os.path.join(os.path.dirname(__file__), "ma_features_200d_adj.csv")
    print(f"[3/3] 流式写入 CSV 产物: {out_csv} ...")

    row_count = 0
    label1_count = 0
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        
        while True:
            rows = cur.fetchmany(10000)
            if not rows:
                break
            row_count += len(rows)
            for r in rows:
                if r[-1] == 1:
                    label1_count += 1
            writer.writerows(rows)
            print(f"  已导出 {row_count} 行面板特征记录...")

    t_cost = time.time() - t_start
    print("\n=================== 200 交易日面板导出汇总 ===================")
    print(f"执行耗时: {t_cost:.2f} 秒")
    print(f"总快照行数: {row_count} 条记录")
    print(f"LABEL=1 多头快照总数: {label1_count} 条记录")

    conn.close()

if __name__ == "__main__":
    main()
