#!/usr/bin/env python3
"""
从 Oracle 抽取全市场 A 股（主板/创业板/科创板）申万 2021 版 1/2/3 级行业分类 (STANDARD = 38)
数据源: LC_EXGINDUSTRY (主板/创业板) UNION ALL LC_STIBEXGINDUSTRY (科创板)
产出: sw_industry_map.json (包含 sw_ind1, sw_ind2, sw_ind3)
"""
import os
import json
import oracledb

import oracle_jydb_helper

def main():
    print("[1/2] 从 Oracle ZBJYDB 拉取全市场 A 股申万 2021 1/2/3 级行业 (含主板与科创板 LC_STIBEXGINDUSTRY)...")
    conn = oracle_jydb_helper.get_connection()
    cur = conn.cursor()

    cur.execute("""
        WITH ashares AS (
            SELECT COMPANYCODE, SECUCODE
            FROM ZBJYDB.SECUMAIN
            WHERE SUBSTR(SECUCODE,1,2) IN ('60','68','00','30') AND SECUCATEGORY = 1
        ),
        all_sw_ind AS (
            SELECT COMPANYCODE, FIRSTINDUSTRYNAME, SECONDINDUSTRYNAME, THIRDINDUSTRYNAME, INFOPUBLDATE, ID
            FROM ZBJYDB.LC_EXGINDUSTRY
            WHERE STANDARD = 38 AND CANCELDATE IS NULL
            UNION ALL
            SELECT COMPANYCODE, FIRSTINDUSTRYNAME, SECONDINDUSTRYNAME, THIRDINDUSTRYNAME, INFOPUBLDATE, ID
            FROM ZBJYDB.LC_STIBEXGINDUSTRY
            WHERE STANDARD = 38 AND CANCELDATE IS NULL
        ),
        sw_ranked AS (
            SELECT COMPANYCODE, FIRSTINDUSTRYNAME, SECONDINDUSTRYNAME, THIRDINDUSTRYNAME,
                   ROW_NUMBER() OVER (PARTITION BY COMPANYCODE ORDER BY INFOPUBLDATE DESC, ID DESC) AS rk
            FROM all_sw_ind
        )
        SELECT S.SECUCODE, 
               COALESCE(I.FIRSTINDUSTRYNAME, N'未分类') AS SW_IND1,
               COALESCE(I.SECONDINDUSTRYNAME, N'未分类') AS SW_IND2,
               COALESCE(I.THIRDINDUSTRYNAME, N'未分类') AS SW_IND3
        FROM ashares S
        LEFT JOIN (SELECT * FROM sw_ranked WHERE rk = 1) I ON S.COMPANYCODE = I.COMPANYCODE
    """)
    sw_map = {
        row[0]: {
            "sw_ind1": row[1],
            "sw_ind2": row[2],
            "sw_ind3": row[3]
        }
        for row in cur.fetchall()
    }
    conn.close()

    out_json = os.path.join(os.path.dirname(__file__), "sw_industry_map.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(sw_map, f, ensure_ascii=False, indent=2)

    kcb_count = sum(1 for c, v in sw_map.items() if c.startswith("68") and v["sw_ind1"] != "未分类")
    print(f"[2/2] 成功导出 {len(sw_map):,} 只 A 股 1/2/3 级行业映射至 {out_json} (其中科创板有效分类: {kcb_count} 只)!")

if __name__ == "__main__":
    main()
