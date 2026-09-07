#!/usr/bin/env python3
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

    # Query for 000333 (美的集团) around a split/dividend date to verify adjusted price
    test_sql = """
    WITH daily_raw AS (
        SELECT 
            D.INNERCODE,
            D.TRADINGDAY,
            D.CLOSEPRICE,
            AF.RATIOADJUSTINGFACTOR
        FROM ZBJYDB.QT_DAILYQUOTE D
        LEFT JOIN ZBJYDB.QT_ADJUSTINGFACTOR AF 
          ON D.INNERCODE = AF.INNERCODE AND D.TRADINGDAY = AF.EXDIVIDATE
        WHERE D.INNERCODE = 30181
          AND D.TRADINGDAY >= TO_DATE('2026-06-01', 'YYYY-MM-DD')
    ),
    daily_adj AS (
        SELECT
            INNERCODE,
            TRADINGDAY,
            CLOSEPRICE,
            LAST_VALUE(RATIOADJUSTINGFACTOR IGNORE NULLS) OVER (
                PARTITION BY INNERCODE ORDER BY TRADINGDAY
            ) AS FACTOR
        FROM daily_raw
    )
    SELECT 
        TRADINGDAY, 
        CLOSEPRICE, 
        FACTOR, 
        CLOSEPRICE * COALESCE(FACTOR, 1.0) AS ADJ_CLOSE
    FROM daily_adj
    ORDER BY TRADINGDAY
    """

    cur.execute(test_sql)
    rows = cur.fetchall()
    print("TRADINGDAY | CLOSEPRICE | FACTOR | ADJ_CLOSE")
    for r in rows[:15]:
        print(f"{r[0].strftime('%Y-%m-%d')} | {r[1]:10.2f} | {r[2]} | {r[3]:10.2f}")

    conn.close()

if __name__ == "__main__":
    main()
