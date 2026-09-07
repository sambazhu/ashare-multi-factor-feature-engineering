#!/usr/bin/env python3
"""
验证合并 LC_STIBDAILYQUOTE 后科创板成交额与 AMO 因子
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

    print("=== 1. 验证合并后科创板股票成交额 ===")
    cur.execute("""
        WITH all_quotes AS (
            SELECT INNERCODE, TRADINGDAY, CLOSEPRICE, TURNOVERVALUE FROM ZBJYDB.QT_DAILYQUOTE
            UNION ALL
            SELECT INNERCODE, TRADINGDAY, CLOSEPRICE, TURNOVERVALUE FROM ZBJYDB.LC_STIBDAILYQUOTE
        )
        SELECT S.SECUCODE, COALESCE(S.SECUABBR, S.CHINAME), 
               COUNT(Q.TRADINGDAY), 
               AVG(Q.TURNOVERVALUE), 
               MAX(Q.TURNOVERVALUE)
        FROM ZBJYDB.SECUMAIN S
        JOIN all_quotes Q ON S.INNERCODE = Q.INNERCODE
        WHERE S.SECUCODE IN ('688981', '688012', '688111', '688008', '688036', '688396')
        GROUP BY S.SECUCODE, COALESCE(S.SECUABBR, S.CHINAME)
    """)
    for r in cur.fetchall():
        print(f"  {r[0]} ({r[1]}): 行情行数={r[2]}, 平均成交额={r[3]/1e8:.2f}亿, 最大成交额={r[4]/1e8:.2f}亿")

    conn.close()

if __name__ == "__main__":
    main()
