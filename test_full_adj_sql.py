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

    sql = """
    WITH vd AS (
        SELECT MAX(TRADINGDAY) AS t0 FROM ZBJYDB.QT_DAILYQUOTE
    ),
    base_factors AS (
        SELECT INNERCODE, RATIOADJUSTINGFACTOR AS INIT_FACTOR
        FROM (
            SELECT INNERCODE, RATIOADJUSTINGFACTOR,
                   ROW_NUMBER() OVER (PARTITION BY INNERCODE ORDER BY EXDIVIDATE DESC) AS rk
            FROM ZBJYDB.QT_ADJUSTINGFACTOR, vd
            WHERE EXDIVIDATE < (vd.t0 - 400)
        ) WHERE rk = 1
    ),
    daily_raw AS (
        SELECT 
            D.INNERCODE,
            SM.SECUCODE,
            SM.CHINAME AS SECNAME,
            D.TRADINGDAY,
            D.CLOSEPRICE,
            AF.RATIOADJUSTINGFACTOR
        FROM ZBJYDB.QT_DAILYQUOTE D
        JOIN ZBJYDB.SECUMAIN SM ON D.INNERCODE = SM.INNERCODE
        LEFT JOIN ZBJYDB.QT_ADJUSTINGFACTOR AF 
          ON D.INNERCODE = AF.INNERCODE AND D.TRADINGDAY = AF.EXDIVIDATE
        , vd
        WHERE SUBSTR(SM.SECUCODE,1,2) IN ('60','68','00','30')
          AND SM.SECUCATEGORY = 1
          AND D.CLOSEPRICE IS NOT NULL
          AND D.TRADINGDAY <= vd.t0
          AND D.TRADINGDAY >= vd.t0 - 400
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
                bf.INIT_FACTOR,
                1.0
            ) AS ADJ_CLOSE
        FROM daily_raw r
        LEFT JOIN base_factors bf ON r.INNERCODE = bf.INNERCODE
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
        (vd.t0 - PREV_DAY)               AS DAY_GAP,
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
                  AND (vd.t0 - PREV_DAY) <= 7
                  AND MA5>MA10 AND MA10>MA20 AND MA20>MA60 AND MA60>MA120 AND MA120>MA250
                  AND PREV_MA5>PREV_MA10 AND PREV_MA10>PREV_MA20 AND PREV_MA20>PREV_MA60
                  AND PREV_MA60>PREV_MA120 AND PREV_MA120>PREV_MA250
                  AND MA5>PREV_MA5 AND MA10>PREV_MA10 AND MA20>PREV_MA20
                  AND MA60>PREV_MA60 AND MA120>PREV_MA120 AND MA250>PREV_MA250
             THEN 1 ELSE 0 END AS LABEL
    FROM lagged, vd
    WHERE TRADINGDAY = vd.t0
    ORDER BY SECUCODE
    """

    print("Running adjusted MA query...")
    t_start = time.time()
    cur.execute(sql)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    t_cost = time.time() - t_start
    print(f"Executed in {t_cost:.2f}s, returned {len(rows)} rows.")

    label1_rows = [r for r in rows if r[-1] == 1]
    print(f"\nTotal LABEL=1 count: {len(label1_rows)}")
    print("Hit stocks (LABEL=1):")
    for r in label1_rows:
        print(f"Code: {r[0]}, Name: {r[1]}, Close: {r[6]}, AdjClose: {r[7]}, MA5: {r[8]}, MA10: {r[9]}, MA20: {r[10]}, MA60: {r[11]}, MA120: {r[12]}, MA250: {r[13]}")

    conn.close()

if __name__ == "__main__":
    main()
