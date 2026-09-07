#!/usr/bin/env python3
# 执行 ma_features_full.sql -> 导出 A股全市场特征矩阵 + 标签 CSV, 并打印汇总
import oracledb, csv, os

SQL_PATH = os.path.join(os.path.dirname(__file__), "ma_features_full.sql")
OUT_CSV  = os.path.join(os.path.dirname(__file__), "ma_features_full.csv")

import oracle_jydb_helper

conn = oracle_jydb_helper.get_connection()
cur = conn.cursor()

with open(SQL_PATH, "r", encoding="utf-8") as f:
    sql = f.read()

cur.execute(sql.rstrip().rstrip(";"))
cols = [d[0] for d in cur.description]
rows = cur.fetchall()
print(f"全市场A股行数: {len(rows)}")
print("列:", cols)

labeled = [r for r in rows if r[-1] == 1]   # LABEL 在最后一列
print(f"LABEL=1 (满足多头排列+全部向上) 数量: {len(labeled)}")
print(f"占比: {len(labeled)/max(len(rows),1)*100:.2f}%")

print("\n样例(前10行, 仅关键列):")
key_idx = [cols.index(c) for c in ("SECUCODE","SECNAME","T0","MA5","MA10","MA20","MA60","MA120","MA250","LABEL")]
print("  " + " | ".join(cols[i] for i in key_idx))
for r in rows[:10]:
    print("  " + " | ".join(str(r[i]) for i in key_idx))

print("\nLABEL=1 清单:")
for r in labeled:
    print("  ", r[0], r[1], "MA250=", r[cols.index("MA250")])

with open(OUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(cols)
    w.writerows(rows)
print(f"\nCSV 已写出: {OUT_CSV}  (行数={len(rows)}, 列数={len(cols)})")
cur.close(); conn.close()
