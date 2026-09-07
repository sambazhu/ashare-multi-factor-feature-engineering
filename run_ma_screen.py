#!/usr/bin/env python3
# 执行 ma_bullish_alignment.sql, 导出结果 CSV 并打印汇总
import oracledb, csv, os

SQL_PATH = os.path.join(os.path.dirname(__file__), "ma_bullish_alignment.sql")
OUT_CSV = os.path.join(os.path.dirname(__file__), "ma_bullish_result.csv")

import oracle_jydb_helper

conn = oracle_jydb_helper.get_connection()
cur = conn.cursor()

with open(SQL_PATH, "r", encoding="utf-8") as f:
    sql = f.read()

cur.execute(sql.rstrip().rstrip(";"))
cols = [d[0] for d in cur.description]
rows = cur.fetchall()
print(f"命中股票数: {len(rows)}")
print("列:", cols)
print("样例(前15):")
hdr = cols
print("  " + " | ".join(str(c) for c in hdr))
for r in rows[:15]:
    print("  " + " | ".join(str(x) for x in r))

with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(cols)
    w.writerows(rows)
print(f"\nCSV 已写出: {OUT_CSV}")
cur.close(); conn.close()
