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

    print("=== Testing Ultra-Fast 200D SQL with Index Pushdown ===")
    t0 = time.time()
    
    # 1. Fetch exact min_t and max_t for recent 200 trading days
    cur.execute("""
        SELECT MIN(TRADINGDAY), MAX(TRADINGDAY) FROM (
            SELECT TRADINGDAY FROM ZBJYDB.QT_DAILYQUOTE 
            WHERE INNERCODE = 3 AND CLOSEPRICE IS NOT NULL
            ORDER BY TRADINGDAY DESC
        ) WHERE ROWNUM <= 200
    """)
    min_t, max_t = cur.fetchone()
    print(f"Date range: min_t={min_t.strftime('%Y-%m-%d')}, max_t={max_t.strftime('%Y-%m-%d')}")
    
    # min_t - 400 days lower bound as literal string for Oracle Index Pushdown
    min_bound_str = "2024-08-01"
    min_t_str = min_t.strftime('%Y-%m-%d')
    max_t_str = max_t.strftime('%Y-%m-%d')

    fast_sql = f"""
    WITH ashares AS (
        SELECT INNERCODE, SECUCODE, COALESCE(SECUABBR, CHINAME) AS SECNAME
        FROM ZBJYDB.SECUMAIN
        WHERE SUBSTR(SECUCODE,1,2) IN ('60','68','00','30')
          AND SECUCATEGORY = 1
    ),
    init_fac AS (
        SELECT INNERCODE, RATIOADJUSTINGFACTOR AS INIT_FACTOR
        FROM (
            SELECT AF.INNERCODE, AF.RATIOADJUSTINGFACTOR,
                   ROW_NUMBER() OVER (PARTITION BY AF.INNERCODE ORDER BY AF.EXDIVIDATE DESC) AS rk
            FROM ZBJYDB.QT_ADJUSTINGFACTOR AF
            JOIN ashares S ON AF.INNERCODE = S.INNERCODE
            WHERE AF.EXDIVIDATE < TO_DATE('{min_bound_str}', 'YYYY-MM-DD')
        ) WHERE rk = 1
    ),
    daily_raw AS (
        SELECT 
            D.INNERCODE,
            S.SECUCODE,
            S.SECNAME,
            D.TRADINGDAY,
            D.CLOSEPRICE,
            AF.RATIOADJUSTINGFACTOR
        FROM ZBJYDB.QT_DAILYQUOTE D
        JOIN ashares S ON D.INNERCODE = S.INNERCODE
        LEFT JOIN ZBJYDB.QT_ADJUSTINGFACTOR AF 
          ON D.INNERCODE = AF.INNERCODE AND D.TRADINGDAY = AF.EXDIVIDATE
        WHERE D.CLOSEPRICE IS NOT NULL
          AND D.TRADINGDAY <= TO_DATE('{max_t_str}', 'YYYY-MM-DD')
          AND D.TRADINGDAY >= TO_DATE('{min_bound_str}', 'YYYY-MM-DD')
    ),
    daily_adj AS (
        SELECT
            r.INNERCODE,
            r.SECUCODE,
            r.SECNAME,
            r.TRADINGDAY,
            r.CLOSEPRICE,
            r.CLOSEPRICE * COALESCE(
                LAST_VALUE(r.RATIOADJUSTINGFACTOR IGNORE NULLS) OVER (
                    PARTITION BY r.INNERCODE ORDER BY r.TRADINGDAY
                ),
                f.INIT_FACTOR,
                1.0
            ) AS ADJ_CLOSE
        FROM daily_raw r
        LEFT JOIN init_fac f ON r.INNERCODE = f.INNERCODE
    ),
    ma AS (
        SELECT
            INNERCODE,
            SECUCODE,
            SECNAME,
            TRADINGDAY,
            CLOSEPRICE,
            ADJ_CLOSE,
            ROW_NUMBER() OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS rn,
            AVG(ADJ_CLOSE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN   4 PRECEDING AND CURRENT ROW) AS MA5,
            AVG(ADJ_CLOSE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN   9 PRECEDING AND CURRENT ROW) AS MA10,
            AVG(ADJ_CLOSE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN  19 PRECEDING AND CURRENT ROW) AS MA20,
            AVG(ADJ_CLOSE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN  59 PRECEDING AND CURRENT ROW) AS MA60,
            AVG(ADJ_CLOSE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 119 PRECEDING AND CURRENT ROW) AS MA120,
            AVG(ADJ_CLOSE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 249 PRECEDING AND CURRENT ROW) AS MA250
        FROM daily_adj
    ),
    lagged AS (
        SELECT
            m.*,
            LAG(MA5)   OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_MA5,
            LAG(MA10)  OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_MA10,
            LAG(MA20)  OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_MA20,
            LAG(MA60)  OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_MA60,
            LAG(MA120) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_MA120,
            LAG(MA250) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_MA250,
            LAG(TRADINGDAY) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_DAY
        FROM ma m
    )
    SELECT
        SECUCODE,
        SECNAME,
        TO_CHAR(TRADINGDAY,'YYYY-MM-DD') AS T0,
        TO_CHAR(PREV_DAY,'YYYY-MM-DD')    AS PREV_DAY,
        (TRADINGDAY - PREV_DAY)          AS DAY_GAP,
        rn                              AS HISTORY_DAYS,
        ROUND(CLOSEPRICE, 3)            AS CLOSEPRICE,
        ROUND(ADJ_CLOSE, 3)             AS ADJ_CLOSE,
        ROUND(CASE WHEN rn>=5   THEN MA5   END, 3) AS MA5,
        ROUND(CASE WHEN rn>=10  THEN MA10  END, 3) AS MA10,
        ROUND(CASE WHEN rn>=20  THEN MA20  END, 3) AS MA20,
        ROUND(CASE WHEN rn>=60  THEN MA60  END, 3) AS MA60,
        ROUND(CASE WHEN rn>=120 THEN MA120 END, 3) AS MA120,
        ROUND(CASE WHEN rn>=250 THEN MA250 END, 3) AS MA250,
        ROUND(CASE WHEN rn>=5   THEN PREV_MA5   END, 3) AS PREV_MA5,
        ROUND(CASE WHEN rn>=10  THEN PREV_MA10  END, 3) AS PREV_MA10,
        ROUND(CASE WHEN rn>=20  THEN PREV_MA20  END, 3) AS PREV_MA20,
        ROUND(CASE WHEN rn>=60  THEN PREV_MA60  END, 3) AS PREV_MA60,
        ROUND(CASE WHEN rn>=120 THEN PREV_MA120 END, 3) AS PREV_MA120,
        ROUND(CASE WHEN rn>=250 THEN PREV_MA250 END, 3) AS PREV_MA250,
        CASE WHEN rn>=250 AND MA5>MA10 AND MA10>MA20 AND MA20>MA60 AND MA60>MA120 AND MA120>MA250 THEN 1 ELSE 0 END AS ALIGN_T0,
        CASE WHEN rn>=250 AND PREV_MA5>PREV_MA10 AND PREV_MA10>PREV_MA20 AND PREV_MA20>PREV_MA60 AND PREV_MA60>PREV_MA120 AND PREV_MA120>PREV_MA250 THEN 1 ELSE 0 END AS ALIGN_T1,
        CASE WHEN rn>=250 AND MA5>PREV_MA5 AND MA10>PREV_MA10 AND MA20>PREV_MA20 AND MA60>PREV_MA60 AND MA120>PREV_MA120 AND MA250>PREV_MA250 THEN 1 ELSE 0 END AS ALL_UP,
        CASE WHEN rn>=250
                  AND (TRADINGDAY - PREV_DAY) <= 7
                  AND MA5>MA10 AND MA10>MA20 AND MA20>MA60 AND MA60>MA120 AND MA120>MA250
                  AND PREV_MA5>PREV_MA10 AND PREV_MA10>PREV_MA20 AND PREV_MA20>PREV_MA60
                  AND PREV_MA60>PREV_MA120 AND PREV_MA120>PREV_MA250
                  AND MA5>PREV_MA5 AND MA10>PREV_MA10 AND MA20>PREV_MA20
                  AND MA60>PREV_MA60 AND MA120>PREV_MA120 AND MA250>PREV_MA250
             THEN 1 ELSE 0 END AS LABEL
    FROM lagged
    WHERE TRADINGDAY >= TO_DATE('{min_t_str}', 'YYYY-MM-DD')
    ORDER BY TRADINGDAY DESC, SECUCODE ASC
    """

    print("Executing Index-Pushdown SQL Query...")
    cur.execute(fast_sql)
    first_batch = cur.fetchmany(100)
    t1 = time.time()
    print(f"First 100 rows fetched in {t1-t0:.2f} seconds!")
    print(f"Sample row 1: Code={first_batch[0][0]}, Name={first_batch[0][1]}, Date={first_batch[0][2]}, Label={first_batch[0][-1]}")

    conn.close()

if __name__ == "__main__":
    main()
