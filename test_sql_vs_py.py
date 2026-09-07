#!/usr/bin/env python3
"""
测试 SQL 实现与 Python 参考实现的交叉对比验证
"""
import os
import oracledb
from test_factor_calc import compute_factors_py, get_db_conn

def test_compare():
    conn = get_db_conn()
    cur = conn.cursor()

    # 测试样本股：600519 茅台, 000001 平安, 000333 美的, 601318 中国平安, 002594 比亚迪
    test_codes = ['600519', '000001', '000333', '601318', '002594']
    print(f"Comparing SQL vs Python for stocks: {test_codes}")

    test_sql = """
    WITH ashares AS (
        SELECT INNERCODE, SECUCODE, COALESCE(SECUABBR, CHINAME) AS SECNAME
        FROM ZBJYDB.SECUMAIN
        WHERE SECUCODE IN ('600519', '000001', '000333', '601318', '002594')
          AND SECUCATEGORY = 1
    ),
    init_fac AS (
        SELECT INNERCODE, RATIOADJUSTINGFACTOR, ADJUSTINGFACTOR, ADJUSTINGCONST
        FROM (
            SELECT AF.INNERCODE, AF.RATIOADJUSTINGFACTOR, AF.ADJUSTINGFACTOR, AF.ADJUSTINGCONST,
                   ROW_NUMBER() OVER (PARTITION BY AF.INNERCODE ORDER BY AF.EXDIVIDATE DESC) AS rk
            FROM ZBJYDB.QT_ADJUSTINGFACTOR AF
            JOIN ashares S ON AF.INNERCODE = S.INNERCODE
            WHERE AF.EXDIVIDATE < (SYSDATE - 600)
        ) WHERE rk = 1
    ),
    daily_raw AS (
        SELECT 
            D.INNERCODE,
            S.SECUCODE,
            S.SECNAME,
            D.TRADINGDAY,
            D.OPENPRICE,
            D.HIGHPRICE,
            D.LOWPRICE,
            D.CLOSEPRICE,
            D.TURNOVERVALUE,
            AF.RATIOADJUSTINGFACTOR,
            AF.ADJUSTINGFACTOR,
            AF.ADJUSTINGCONST
        FROM ZBJYDB.QT_DAILYQUOTE D
        JOIN ashares S ON D.INNERCODE = S.INNERCODE
        LEFT JOIN ZBJYDB.QT_ADJUSTINGFACTOR AF 
          ON D.INNERCODE = AF.INNERCODE AND D.TRADINGDAY = AF.EXDIVIDATE
        WHERE D.CLOSEPRICE IS NOT NULL
          AND D.TRADINGDAY >= (SYSDATE - 600)
    ),
    daily_adj AS (
        SELECT
            r.INNERCODE,
            r.SECUCODE,
            r.SECNAME,
            r.TRADINGDAY,
            r.OPENPRICE,
            r.HIGHPRICE,
            r.LOWPRICE,
            r.CLOSEPRICE,
            r.TURNOVERVALUE,
            -- 比例复权因子与价格
            COALESCE(
                LAST_VALUE(r.RATIOADJUSTINGFACTOR IGNORE NULLS) OVER (
                    PARTITION BY r.INNERCODE ORDER BY r.TRADINGDAY
                ),
                f.RATIOADJUSTINGFACTOR,
                1.0
            ) AS RATIO_FAC,
            r.OPENPRICE * COALESCE(
                LAST_VALUE(r.RATIOADJUSTINGFACTOR IGNORE NULLS) OVER (
                    PARTITION BY r.INNERCODE ORDER BY r.TRADINGDAY
                ),
                f.RATIOADJUSTINGFACTOR,
                1.0
            ) AS RATIO_OPEN,
            r.HIGHPRICE * COALESCE(
                LAST_VALUE(r.RATIOADJUSTINGFACTOR IGNORE NULLS) OVER (
                    PARTITION BY r.INNERCODE ORDER BY r.TRADINGDAY
                ),
                f.RATIOADJUSTINGFACTOR,
                1.0
            ) AS RATIO_HIGH,
            r.LOWPRICE * COALESCE(
                LAST_VALUE(r.RATIOADJUSTINGFACTOR IGNORE NULLS) OVER (
                    PARTITION BY r.INNERCODE ORDER BY r.TRADINGDAY
                ),
                f.RATIOADJUSTINGFACTOR,
                1.0
            ) AS RATIO_LOW,
            r.CLOSEPRICE * COALESCE(
                LAST_VALUE(r.RATIOADJUSTINGFACTOR IGNORE NULLS) OVER (
                    PARTITION BY r.INNERCODE ORDER BY r.TRADINGDAY
                ),
                f.RATIOADJUSTINGFACTOR,
                1.0
            ) AS ADJ_CLOSE,
            -- 精确复权
            r.CLOSEPRICE * COALESCE(
                LAST_VALUE(r.ADJUSTINGFACTOR IGNORE NULLS) OVER (
                    PARTITION BY r.INNERCODE ORDER BY r.TRADINGDAY
                ),
                f.ADJUSTINGFACTOR,
                1.0
            ) + COALESCE(
                LAST_VALUE(r.ADJUSTINGCONST IGNORE NULLS) OVER (
                    PARTITION BY r.INNERCODE ORDER BY r.TRADINGDAY
                ),
                f.ADJUSTINGCONST,
                0.0
            ) AS EXACT_CLOSE,
            -- 红绿
            CASE WHEN r.CLOSEPRICE > r.OPENPRICE THEN 1 ELSE 0 END AS IS_RED,
            CASE WHEN r.CLOSEPRICE < r.OPENPRICE THEN 1 ELSE 0 END AS IS_GREEN
        FROM daily_raw r
        LEFT JOIN init_fac f ON r.INNERCODE = f.INNERCODE
    ),
    window_stats AS (
        SELECT
            d.*,
            ROW_NUMBER() OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS rn,
            -- 均线
            AVG(ADJ_CLOSE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN   4 PRECEDING AND CURRENT ROW) AS MA5,
            AVG(ADJ_CLOSE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN   9 PRECEDING AND CURRENT ROW) AS MA10,
            AVG(ADJ_CLOSE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN  19 PRECEDING AND CURRENT ROW) AS MA20,
            AVG(ADJ_CLOSE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN  59 PRECEDING AND CURRENT ROW) AS MA60,
            AVG(ADJ_CLOSE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 119 PRECEDING AND CURRENT ROW) AS MA120,
            AVG(ADJ_CLOSE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 249 PRECEDING AND CURRENT ROW) AS MA250,
            -- 未复权均线
            AVG(CLOSEPRICE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN   4 PRECEDING AND CURRENT ROW) AS RAW_MA5,
            AVG(CLOSEPRICE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN   9 PRECEDING AND CURRENT ROW) AS RAW_MA10,
            AVG(CLOSEPRICE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN  19 PRECEDING AND CURRENT ROW) AS RAW_MA20,
            AVG(CLOSEPRICE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN  59 PRECEDING AND CURRENT ROW) AS RAW_MA60,
            AVG(CLOSEPRICE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 119 PRECEDING AND CURRENT ROW) AS RAW_MA120,
            AVG(CLOSEPRICE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 249 PRECEDING AND CURRENT ROW) AS RAW_MA250,
            -- HL+5R 窗口:
            MIN(RATIO_LOW)  OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 9 PRECEDING AND CURRENT ROW) AS RECENT_LOW_10,
            MAX(RATIO_HIGH) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 169 PRECEDING AND CURRENT ROW) AS WIN_HIGH_170,
            MIN(RATIO_LOW)  OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) AS WIN_LOW_30,
            -- HL+AMO 窗口:
            MAX(RATIO_HIGH) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 179 PRECEDING AND CURRENT ROW) AS WIN_HIGH_180,
            -- AMO 窗口:
            MAX(TURNOVERVALUE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 14 PRECEDING AND CURRENT ROW) AS WIN_MAX_15,
            AVG(TURNOVERVALUE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 4 PRECEDING AND CURRENT ROW)  AS WIN_AVG_5,
            AVG(TURNOVERVALUE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 9 PRECEDING AND CURRENT ROW)  AS WIN_AVG_10,
            AVG(TURNOVERVALUE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 14 PRECEDING AND CURRENT ROW) AS WIN_AVG_15
        FROM daily_adj d
    ),
    lagged AS (
        SELECT
            w.*,
            -- 均线 LAG
            LAG(MA5)   OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_MA5,
            LAG(MA10)  OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_MA10,
            LAG(MA20)  OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_MA20,
            LAG(MA60)  OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_MA60,
            LAG(MA120) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_MA120,
            LAG(MA250) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_MA250,
            LAG(RAW_MA5)   OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_RAW_MA5,
            LAG(RAW_MA10)  OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_RAW_MA10,
            LAG(RAW_MA20)  OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_RAW_MA20,
            LAG(RAW_MA60)  OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_RAW_MA60,
            LAG(RAW_MA120) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_RAW_MA120,
            LAG(RAW_MA250) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_RAW_MA250,
            LAG(TRADINGDAY) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_DAY,
            -- 红绿 LAG
            LAG(IS_RED, 1) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS RED_T1,
            LAG(IS_RED, 2) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS RED_T2,
            LAG(IS_RED, 3) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS RED_T3,
            LAG(IS_RED, 4) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS RED_T4,
            LAG(IS_GREEN, 5) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS GREEN_T5,
            -- HL+5R LAGs
            LAG(RATIO_OPEN, 4) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS RATIO_OPEN_T4,
            LAG(WIN_HIGH_170, 10) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PRIOR_HIGH_170,
            LAG(WIN_LOW_30, 10) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PRIOR_LOW_30,
            -- AMO LAGs
            LAG(TURNOVERVALUE, 1) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS AMT_1,
            LAG(WIN_MAX_15, 1) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS MAX_15,
            LAG(WIN_AVG_5, 1)  OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS AVG_5,
            LAG(WIN_AVG_10, 1) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS AVG_10,
            LAG(WIN_AVG_15, 1) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS AVG_15,
            LAG(ADJ_CLOSE, 10) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS ADJ_CLOSE_T10,
            -- HL+AMO LAGs
            LAG(ADJ_CLOSE, 1) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS ADJ_CLOSE_T1,
            LAG(WIN_HIGH_180, 2) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PRIOR_HIGH_180
        FROM window_stats w
    ),
    calculated AS (
        SELECT
            l.*,
            -- 5日连红标记
            CASE WHEN IS_RED = 1 AND RED_T1 = 1 AND RED_T2 = 1 AND RED_T3 = 1 AND RED_T4 = 1 THEN 1 ELSE 0 END AS RED_5,
            -- HL+5R 中间指标
            CASE WHEN PRIOR_HIGH_170 > 0 THEN 1.0 - RECENT_LOW_10 / PRIOR_HIGH_170 ELSE 0 END AS DRAWDOWN_180,
            CASE WHEN PRIOR_LOW_30 > 0 THEN RECENT_LOW_10 / PRIOR_LOW_30 - 1.0 ELSE 0 END AS LOW_REBOUND_30,
            CASE WHEN RATIO_OPEN_T4 > 0 THEN ADJ_CLOSE / RATIO_OPEN_T4 - 1.0 ELSE 0 END AS FIVE_DAY_GAIN,
            -- AMO 中间指标
            CASE WHEN ADJ_CLOSE_T10 > 0 THEN ADJ_CLOSE / ADJ_CLOSE_T10 - 1.0 ELSE 0 END AS RETURN_10,
            -- HL+AMO 中间指标
            CASE WHEN PRIOR_HIGH_180 > 0 THEN 1.0 - ADJ_CLOSE_T1 / PRIOR_HIGH_180 ELSE 0 END AS PREV_DRAWDOWN_180
        FROM lagged l
    )
    SELECT
        SECUCODE,
        SECNAME,
        TO_CHAR(TRADINGDAY, 'YYYY-MM-DD') AS T0,
        rn AS HISTORY_DAYS,
        ROUND(CLOSEPRICE, 3) AS CLOSEPRICE,
        ROUND(ADJ_CLOSE, 3) AS ADJ_CLOSE,
        ROUND(TURNOVERVALUE, 0) AS TURNOVERVALUE,
        -- 均线 LABEL
        CASE WHEN rn>=250 AND (TRADINGDAY - PREV_DAY) <= 7
                  AND MA5>MA10 AND MA10>MA20 AND MA20>MA60 AND MA60>MA120 AND MA120>MA250
                  AND PREV_MA5>PREV_MA10 AND PREV_MA10>PREV_MA20 AND PREV_MA20>PREV_MA60 AND PREV_MA60>PREV_MA120 AND PREV_MA120>PREV_MA250
                  AND MA5>PREV_MA5 AND MA10>PREV_MA10 AND MA20>PREV_MA20 AND MA60>PREV_MA60 AND MA120>PREV_MA120 AND MA250>PREV_MA250
             THEN 1 ELSE 0 END AS LABEL,
        -- HL+5R 标签 (严格要求 T-5 为阴线)
        CASE WHEN rn >= 180
                  AND DRAWDOWN_180 > 0.25
                  AND LOW_REBOUND_30 < 0.10
                  AND RED_5 = 1
                  AND GREEN_T5 = 1
                  AND FIVE_DAY_GAIN < 0.13
             THEN 1 ELSE 0 END AS FACTOR_HL_5R,
        -- 5R 标签 (排除 HL+5R)
        CASE WHEN rn >= 6
                  AND RED_5 = 1
                  AND GREEN_T5 = 1
                  AND NOT (
                      rn >= 180
                      AND DRAWDOWN_180 > 0.25
                      AND LOW_REBOUND_30 < 0.10
                      AND RED_5 = 1
                      AND GREEN_T5 = 1
                      AND FIVE_DAY_GAIN < 0.13
                  )
             THEN 1 ELSE 0 END AS FACTOR_5R,
        -- AMO 标签
        CASE WHEN rn >= 16
                  AND TURNOVERVALUE > 100000000.0
                  AND TURNOVERVALUE > 1.2 * MAX_15
                  AND TURNOVERVALUE > 1.8 * AMT_1
                  AND TURNOVERVALUE > 1.8 * AVG_5
                  AND TURNOVERVALUE > 1.8 * AVG_10
                  AND TURNOVERVALUE > 1.8 * AVG_15
                  AND IS_RED = 1
                  AND RETURN_10 < 0.50
             THEN 1 ELSE 0 END AS FACTOR_AMO,
        -- HL+AMO 标签
        CASE WHEN rn >= 182
                  AND TURNOVERVALUE > 100000000.0
                  AND TURNOVERVALUE > 1.2 * MAX_15
                  AND TURNOVERVALUE > 1.8 * AMT_1
                  AND TURNOVERVALUE > 1.8 * AVG_5
                  AND TURNOVERVALUE > 1.8 * AVG_10
                  AND TURNOVERVALUE > 1.8 * AVG_15
                  AND IS_RED = 1
                  AND RETURN_10 < 0.50
                  AND PREV_DRAWDOWN_180 > 0.25
             THEN 1 ELSE 0 END AS FACTOR_HL_AMO
    FROM calculated
    ORDER BY TRADINGDAY ASC
    """

    print("Executing SQL test query...")
    cur.execute(test_sql)
    sql_cols = [c[0] for c in cur.description]
    sql_rows = [dict(zip(sql_cols, r)) for r in cur.fetchall()]
    print(f"SQL returned {len(sql_rows)} rows across test stocks.")

    # 逐只股票与 Python 结果逐日逐字段比对
    from collections import defaultdict
    by_stock_sql = defaultdict(list)
    for r in sql_rows:
        by_stock_sql[r["SECUCODE"]].append(r)

    total_compared = 0
    mismatch_count = 0

    for code in test_codes:
        if code not in by_stock_sql:
            continue
        cur.execute("""
            SELECT RATIOADJUSTINGFACTOR, ADJUSTINGFACTOR, ADJUSTINGCONST
            FROM (
                SELECT AF.RATIOADJUSTINGFACTOR, AF.ADJUSTINGFACTOR, AF.ADJUSTINGCONST
                FROM ZBJYDB.QT_ADJUSTINGFACTOR AF
                JOIN ZBJYDB.SECUMAIN S ON AF.INNERCODE = S.INNERCODE
                WHERE S.SECUCODE = :code AND S.SECUCATEGORY = 1
                  AND AF.EXDIVIDATE < (SYSDATE - 600)
                ORDER BY AF.EXDIVIDATE DESC
            ) WHERE ROWNUM = 1
        """, code=code)
        init_row = cur.fetchone()
        init_ratio = float(init_row[0]) if (init_row and init_row[0] is not None) else 1.0
        init_adj_f = float(init_row[1]) if (init_row and init_row[1] is not None) else 1.0
        init_adj_c = float(init_row[2]) if (init_row and init_row[2] is not None) else 0.0

        cur.execute("""
            SELECT 
                D.TRADINGDAY,
                D.OPENPRICE,
                D.HIGHPRICE,
                D.LOWPRICE,
                D.CLOSEPRICE,
                D.TURNOVERVALUE,
                AF.RATIOADJUSTINGFACTOR,
                AF.ADJUSTINGFACTOR,
                AF.ADJUSTINGCONST
            FROM ZBJYDB.QT_DAILYQUOTE D
            JOIN ZBJYDB.SECUMAIN S ON D.INNERCODE = S.INNERCODE
            LEFT JOIN ZBJYDB.QT_ADJUSTINGFACTOR AF
              ON D.INNERCODE = AF.INNERCODE AND D.TRADINGDAY = AF.EXDIVIDATE
            WHERE S.SECUCODE = :code
              AND S.SECUCATEGORY = 1
              AND D.CLOSEPRICE IS NOT NULL
              AND D.TRADINGDAY >= (SYSDATE - 600)
            ORDER BY D.TRADINGDAY ASC
        """, code=code)
        raw_cols = [c[0] for c in cur.description]
        py_raw_rows = [dict(zip(raw_cols, r)) for r in cur.fetchall()]
        py_res = compute_factors_py(py_raw_rows, init_ratio=init_ratio, init_adj_f=init_adj_f, init_adj_c=init_adj_c)

        sql_data = by_stock_sql[code]
        assert len(sql_data) == len(py_res), f"Row count mismatch for {code}: SQL {len(sql_data)} vs Py {len(py_res)}"

        for s_row, p_row in zip(sql_data, py_res):
            total_compared += 1
            date_s = s_row["T0"]
            date_p = p_row["date"]
            assert date_s == date_p, f"Date mismatch: {date_s} vs {date_p}"

            # 校验 5R
            if s_row["FACTOR_5R"] != p_row["factor_5r"]:
                print(f"MISMATCH 5R for {code} on {date_s}: SQL={s_row['FACTOR_5R']} Py={p_row['factor_5r']}")
                mismatch_count += 1
            # 校验 HL+5R
            if s_row["FACTOR_HL_5R"] != p_row["factor_hl_5r"]:
                print(f"MISMATCH HL+5R for {code} on {date_s}: SQL={s_row['FACTOR_HL_5R']} Py={p_row['factor_hl_5r']}")
                mismatch_count += 1
            # 校验 AMO
            if s_row["FACTOR_AMO"] != p_row["factor_amo"]:
                print(f"MISMATCH AMO for {code} on {date_s}: SQL={s_row['FACTOR_AMO']} Py={p_row['factor_amo']}")
                mismatch_count += 1
            # 校验 HL+AMO
            if s_row["FACTOR_HL_AMO"] != p_row["factor_hl_amo"]:
                print(f"MISMATCH HL+AMO for {code} on {date_s}: SQL={s_row['FACTOR_HL_AMO']} Py={p_row['factor_hl_amo']}")
                mismatch_count += 1

    print(f"\n[Comparison Completed] Total compared: {total_compared} rows. Mismatches: {mismatch_count}")
    assert mismatch_count == 0, f"Found {mismatch_count} mismatches between SQL and Python reference!"
    print("[PERFECT MATCH] SQL and Python factor calculations are 100% identical!")
    conn.close()

if __name__ == "__main__":
    test_compare()
