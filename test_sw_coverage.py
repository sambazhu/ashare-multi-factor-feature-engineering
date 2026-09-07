#!/usr/bin/env python3
"""
验证 STANDARD = 38 (申万 2021 最新版) 在全市场 4591 只 A 股上的覆盖率与分布
"""
import os
import oracledb

IC_DIR = "/opt/oracle/instantclient"

def main():
    oracledb.init_oracle_client(lib_dir=IC_DIR)
    conn = oracledb.connect(
        user=os.getenv("JYDB_USER", "jydb"),
        password=os.environ["JYDB_PASSWORD"],
        host=os.getenv("JYDB_HOST", "127.0.0.1"),
        port=int(os.getenv("JYDB_PORT", "1521")),
        service_name=os.getenv("JYDB_SERVICE", "JYDBTEST")
    )
    cur = conn.cursor()

    print("=== [1] 检查 STANDARD = 38 (申万 2021) 在 A 股主表 SECUMAIN 中的覆盖率 ===")
    cur.execute("""
        WITH ashares AS (
            SELECT COMPANYCODE, SECUCODE, SECUABBR
            FROM ZBJYDB.SECUMAIN
            WHERE SUBSTR(SECUCODE,1,2) IN ('60','68','00','30') AND SECUCATEGORY = 1
        ),
        sw_ind AS (
            SELECT COMPANYCODE, FIRSTINDUSTRYNAME, SECONDINDUSTRYNAME
            FROM (
                SELECT COMPANYCODE, FIRSTINDUSTRYNAME, SECONDINDUSTRYNAME,
                       ROW_NUMBER() OVER (PARTITION BY COMPANYCODE ORDER BY INFOPUBLDATE DESC, ID DESC) AS rk
                FROM ZBJYDB.LC_EXGINDUSTRY
                WHERE STANDARD = 38 AND CANCELDATE IS NULL
            ) WHERE rk = 1
        )
        SELECT 
            COUNT(*) AS TOTAL_STOCKS,
            COUNT(I.FIRSTINDUSTRYNAME) AS SW_MAPPED_STOCKS,
            COUNT(*) - COUNT(I.FIRSTINDUSTRYNAME) AS UNMAPPED_STOCKS
        FROM ashares S
        LEFT JOIN sw_ind I ON S.COMPANYCODE = I.COMPANYCODE
    """)
    total, mapped, unmapped = cur.fetchone()
    print(f"A 股总数: {total} | 申万一级行业映射成功数: {mapped} ({mapped/total*100:.2f}%) | 未映射数: {unmapped}")

    print("\n=== [2] 申万一级行业分布 (31 个申万一级行业) ===")
    cur.execute("""
        WITH ashares AS (
            SELECT COMPANYCODE, SECUCODE
            FROM ZBJYDB.SECUMAIN
            WHERE SUBSTR(SECUCODE,1,2) IN ('60','68','00','30') AND SECUCATEGORY = 1
        ),
        sw_ind AS (
            SELECT COMPANYCODE, FIRSTINDUSTRYNAME
            FROM (
                SELECT COMPANYCODE, FIRSTINDUSTRYNAME,
                       ROW_NUMBER() OVER (PARTITION BY COMPANYCODE ORDER BY INFOPUBLDATE DESC, ID DESC) AS rk
                FROM ZBJYDB.LC_EXGINDUSTRY
                WHERE STANDARD = 38 AND CANCELDATE IS NULL
            ) WHERE rk = 1
        )
        SELECT COALESCE(I.FIRSTINDUSTRYNAME, N'未分类') AS IND_NAME, COUNT(*) AS CNT
        FROM ashares S
        LEFT JOIN sw_ind I ON S.COMPANYCODE = I.COMPANYCODE
        GROUP BY COALESCE(I.FIRSTINDUSTRYNAME, N'未分类')
        ORDER BY CNT DESC
    """)
    for ind, cnt in cur.fetchall():
        print(f" 行业: {ind:12s} | 股票只数: {cnt}")

    conn.close()

if __name__ == "__main__":
    main()
