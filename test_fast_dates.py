#!/usr/bin/env python3
import os
import time
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

    print("=== Testing Fast 200 Days Query ===")
    t0 = time.time()
    cur.execute("""
        SELECT TRADINGDAY FROM (
            SELECT TRADINGDAY FROM ZBJYDB.QT_DAILYQUOTE 
            WHERE INNERCODE = 3 AND CLOSEPRICE IS NOT NULL
            ORDER BY TRADINGDAY DESC
        ) WHERE ROWNUM <= 200
    """)
    dates = [r[0] for r in cur.fetchall()]
    t1 = time.time()
    print(f"Fast 200 Trading Days fetched in {t1-t0:.3f}s! Count: {len(dates)}")
    print(f"Max Date: {dates[0].strftime('%Y-%m-%d')}, Min Date: {dates[-1].strftime('%Y-%m-%d')}")

    conn.close()

if __name__ == "__main__":
    main()
