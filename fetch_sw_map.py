#!/usr/bin/env python3
"""
生成全市场 A 股聚源最新 2021 版申万行业字典 (STANDARD = 38) JSON 文件 sw_industry_map.json
"""
import os
import json
import oracledb

import oracle_jydb_helper

def main():
    print("[1/2] 连接 Oracle 数据库获取全市场申万 2021 行业分类 (STANDARD=38)...")
    conn = oracle_jydb_helper.get_connection()
    cur = conn.cursor()

    sql = """
    WITH sw_ind AS (
        SELECT COMPANYCODE, FIRSTINDUSTRYNAME AS SW_IND1, SECONDINDUSTRYNAME AS SW_IND2,
               ROW_NUMBER() OVER (PARTITION BY COMPANYCODE ORDER BY INFOPUBLDATE DESC, ID DESC) AS rk
        FROM ZBJYDB.LC_EXGINDUSTRY
        WHERE STANDARD = 38 AND CANCELDATE IS NULL
    )
    SELECT S.SECUCODE, COALESCE(I.SW_IND1, N'未分类') AS SW_IND1, COALESCE(I.SW_IND2, N'未分类') AS SW_IND2
    FROM ZBJYDB.SECUMAIN S
    LEFT JOIN sw_ind I ON S.COMPANYCODE = I.COMPANYCODE AND I.rk = 1
    WHERE SUBSTR(S.SECUCODE,1,2) IN ('60','68','00','30')
      AND S.SECUCATEGORY = 1
    """
    cur.execute(sql)
    rows = cur.fetchall()
    sw_map = {}
    for code, ind1, ind2 in rows:
        sw_map[code] = {"sw_ind1": ind1, "sw_ind2": ind2}

    print(f"[2/2] 获取到 {len(sw_map)} 只 A 股申万行业分类，保存至 sw_industry_map.json...")
    with open("sw_industry_map.json", "w", encoding="utf-8") as f:
        json.dump(sw_map, f, ensure_ascii=False, indent=2)

    conn.close()
    print("完成！")

if __name__ == "__main__":
    main()
