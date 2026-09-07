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

    # Find Innercode for 000333 (美的集团) or 000001 (平安银行)
    cur.execute("""
        SELECT INNERCODE, SECUCODE, CHINAME 
        FROM ZBJYDB.SECUMAIN 
        WHERE SECUCODE IN ('000333', '000001', '600519') AND SECUCATEGORY = 1
    """)
    stocks = cur.fetchall()
    print("Stocks:", stocks)

    for innercode, secucode, chiname in stocks:
        print(f"\n--- Checking QT_ADJUSTINGFACTOR for {secucode} {chiname} (INNERCODE={innercode}) ---")
        cur.execute("""
            SELECT EXDIVIDATE, ADJUSTINGFACTOR, RATIOADJUSTINGFACTOR, ADJUSTINGCONST
            FROM ZBJYDB.QT_ADJUSTINGFACTOR
            WHERE INNERCODE = :1
            ORDER BY EXDIVIDATE DESC
        """, [innercode])
        factors = cur.fetchall()
        print(f"Total factor records: {len(factors)}")
        for f in factors[:10]:
            print(f)

    conn.close()

if __name__ == "__main__":
    main()
