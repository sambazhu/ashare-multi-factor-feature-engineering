#!/usr/bin/env python3
"""
30 只跨板块股票全量 9 大核心策略因子 SQL vs Pure Python 交叉比对套件 (有效交易日新高与原始 500 天门槛严格闭环版)
1. 基于 CS_StockAdjPerformance(1,1) 前复权精确复权主口径
2. 合并 QT_DAILYQUOTE + LC_STIBDAILYQUOTE 科创板真实成交额
3. 严格等差 + SUM(IS_TRADING)=N 无停牌行强约束
4. 包含 688012 / 2026-01-05 真实停牌日回归断言
5. 包含严谨的停牌 AMO 对照单测 (无停牌命中=1 vs 插入停牌必定否决=0)
6. 包含有效交易日新高单测 (253物理行含1天停牌 -> 前序有效行情恰好251天，过去250有效日前高10.5 -> 命中250日新高HIGH_250=1)
7. 包含次新股新高单测 (上市300天次新股突破全部前高 -> 严格否决HIGH_ALL=0 且 成功降级命中HIGH_250=1 & D250)
8. 严格覆盖 30 只股票 x 200 交易日 = 6,000 行，0 mismatch!
"""
import os
import sys
import oracledb
from collections import defaultdict
from test_factor_calc import get_db_conn, compute_factors_py

SAMPLE_CODES = [
    # 沪市主板 (60 - 8只)
    '600519', '601398', '600036', '601857', '600900', '601166', '600276', '600030',
    # 深市主板 (00 - 8只)
    '000001', '000333', '000858', '002594', '002475', '000651', '000725', '002415',
    # 创业板 (30 - 8只)
    '300750', '300059', '300760', '300124', '300015', '300274', '300498', '300951',
    # 科创板 (68 - 6只)
    '688981', '688012', '688111', '688008', '688036', '688396'
]

def test_suspend_and_boundary_units():
    print("=== [单元测试 1] 停牌强约束 AMO A/B 对照测试 (无停牌必定命中 vs 插入停牌必定否决) ===")
    baseline_rows = []
    for i in range(15):
        baseline_rows.append({
            "TRADINGDAY": f"2026-01-{i+1:02d}",
            "ADJOPENPRICE": 10.0, "ADJHIGHPRICE": 10.5, "ADJLOWPRICE": 9.8, "ADJCLOSEPRICE": 10.2,
            "TURNOVERVALUE": 50000000.0
        })
    baseline_rows.append({
        "TRADINGDAY": "2026-01-16",
        "ADJOPENPRICE": 10.2, "ADJHIGHPRICE": 11.5, "ADJLOWPRICE": 10.1, "ADJCLOSEPRICE": 11.2,
        "TURNOVERVALUE": 200000000.0
    })
    seq_map_16 = {f"2026-01-{i+1:02d}": i + 1 for i in range(16)}
    
    res_base = compute_factors_py(baseline_rows, market_td_seq_map=seq_map_16, listing_tdays_map={})
    assert res_base[-1]["factor_amo"] == 1, "Baseline 序列在无停牌时必须命中 FACTOR_AMO=1!"
    print("  [PASS 1.1] 无停牌 Baseline 序列验证: 成功命中 FACTOR_AMO = 1")

    suspend_rows = [dict(r) for r in baseline_rows]
    suspend_rows[9]["TURNOVERVALUE"] = 0.0
    suspend_rows[9]["ADJOPENPRICE"] = suspend_rows[8]["ADJCLOSEPRICE"]
    suspend_rows[9]["ADJCLOSEPRICE"] = suspend_rows[8]["ADJCLOSEPRICE"]
    suspend_rows[9]["ADJHIGHPRICE"] = suspend_rows[8]["ADJCLOSEPRICE"]
    suspend_rows[9]["ADJLOWPRICE"] = suspend_rows[8]["ADJCLOSEPRICE"]

    res_suspend = compute_factors_py(suspend_rows, market_td_seq_map=seq_map_16, listing_tdays_map={})
    assert res_suspend[-1]["factor_amo"] == 0, "插入中间停牌日后，必须严格否决 FACTOR_AMO=0!"
    print("  [PASS 1.2] 插入停牌日对照序列验证: FACTOR_AMO 成功由 1 变为 0 (严格证明停牌强约束有效)!")

    print("\n=== [单元测试 2] 有效交易日新高跨停牌单测 (253物理行含1天停牌 -> 前序有效行情恰好251天 -> 命中250日新高) ===")
    mock_suspend_high = []
    # 第 1 天构造一个历史天价 15.0 (保证未破全量前高，排除 HIGH_ALL)
    mock_suspend_high.append({
        "TRADINGDAY": "2024-01-01",
        "ADJOPENPRICE": 10.0, "ADJHIGHPRICE": 15.0, "ADJLOWPRICE": 9.5, "ADJCLOSEPRICE": 10.0,
        "TURNOVERVALUE": 50000000.0
    })
    # 随后 251 天 (其中包含 1 天停牌，有效交易日 250 天)，最高价仅为 10.5
    for i in range(1, 252):
        mock_suspend_high.append({
            "TRADINGDAY": f"2025-01-01",
            "ADJOPENPRICE": 10.0, "ADJHIGHPRICE": 10.5, "ADJLOWPRICE": 9.5, "ADJCLOSEPRICE": 10.0,
            "TURNOVERVALUE": 0.0 if i == 100 else 50000000.0
        })
    # T0 (第253行) 突破前序 250 个有效交易日的最高价 (12.0 > 10.5)，但低于历史天价 15.0
    mock_suspend_high.append({
        "TRADINGDAY": "2026-08-18",
        "ADJOPENPRICE": 10.0, "ADJHIGHPRICE": 12.0, "ADJLOWPRICE": 9.5, "ADJCLOSEPRICE": 11.0,
        "TURNOVERVALUE": 50000000.0
    })
    res_sh = compute_factors_py(mock_suspend_high, market_td_seq_map={"2026-08-18": 253}, listing_tdays_map={"2026-08-18": 1000})
    assert res_sh[-1]["factor_high_all"] == 0, "低于历史天价，必须否决 FACTOR_HIGH_ALL=0!"
    assert res_sh[-1]["factor_high_250"] == 1, "跨停牌行但前序有效交易日满250天时，突破250有效日前高必须命中 FACTOR_HIGH_250=1!"
    assert res_sh[-1]["high_type"] == "D250", "high_type 必须为 D250!"
    print("  [PASS 2.1] 253物理行含1天停牌(前序有效日251天，过去250有效日前高10.5): 成功精准命中 FACTOR_HIGH_250 = 1 且 high_type = D250!")

    print("\n=== [单元测试 3] 次新股 LISTING_TDAYS > 500 约束单测 (上市300天突破所有前高 -> 否决HIGH_ALL 且 降级命中HIGH_250) ===")
    mock_ipo_rows = []
    for i in range(300):
        mock_ipo_rows.append({
            "TRADINGDAY": f"2025-01-01",
            "ADJOPENPRICE": 20.0, "ADJHIGHPRICE": 25.0, "ADJLOWPRICE": 18.0, "ADJCLOSEPRICE": 22.0,
            "TURNOVERVALUE": 50000000.0
        })
    # T0 突破上市以来所有前高 (30.0 > 25.0)，但上市只有 301 天
    mock_ipo_rows.append({
        "TRADINGDAY": "2026-08-18",
        "ADJOPENPRICE": 25.0, "ADJHIGHPRICE": 30.0, "ADJLOWPRICE": 24.0, "ADJCLOSEPRICE": 28.0,
        "TURNOVERVALUE": 50000000.0
    })
    res_ipo = compute_factors_py(mock_ipo_rows, market_td_seq_map={"2026-08-18": 301}, listing_tdays_map={"2026-08-18": 301})
    assert res_ipo[-1]["factor_high_all"] == 0, "上市仅301天未满500天，必须严格否决 FACTOR_HIGH_ALL=0!"
    assert res_ipo[-1]["factor_high_250"] == 1, "上市满250天且突破前高，必须成功降级命中 FACTOR_HIGH_250=1!"
    assert res_ipo[-1]["high_type"] == "D250", "high_type 必须为 D250!"
    print("  [PASS 3.1] 次新股 (上市301天) 突破前高: 严格否决 HIGH_ALL=0，成功降级命中 FACTOR_HIGH_250 = 1 且 high_type = D250!")

def main():
    print("=" * 75)
    print("全量 9 大核心策略因子: SQL vs Pure Python 30 只股票跨板块 6,000 行交叉验算")
    print("=" * 75)

    test_suspend_and_boundary_units()

    conn = get_db_conn()
    cur = conn.cursor()
    cur.arraysize = 5000
    cur.prefetchrows = 5000

    cur.execute("""
        SELECT TO_CHAR(TRADINGDATE, 'YYYY-MM-DD'), 
               ROW_NUMBER() OVER (ORDER BY TRADINGDATE ASC) AS MARKET_TD_SEQ
        FROM ZBJYDB.QT_TRADINGDAYNEW
        WHERE SECUMARKET = 83 AND IFTRADINGDAY = 1
    """)
    calendar_rows = cur.fetchall()
    market_seq_map = {r[0]: int(r[1]) for r in calendar_rows}
    print(f"\n[1/4] 加载市场交易日历天数: {len(market_seq_map):,} 天")

    # 抓取最近 200 个 A 股交易日集合
    cur.execute("""
        WITH ashare_stocks AS (
            SELECT INNERCODE FROM ZBJYDB.SECUMAIN
            WHERE SUBSTR(SECUCODE,1,2) IN ('60','68','00','30') AND SECUCATEGORY = 1
        ),
        ashare_dates AS (
            SELECT DISTINCT P.TRADINGDAY
            FROM ZBJYDB.CS_STOCKADJPERFORMANCE P
            JOIN ashare_stocks S ON P.INNERCODE = S.INNERCODE
            WHERE P.ADJUSTINGMETHOD = 1 AND P.ADJUSTINGSTANDARD = 1
            ORDER BY P.TRADINGDAY DESC
        )
        SELECT TO_CHAR(TRADINGDAY, 'YYYY-MM-DD') FROM (
            SELECT TRADINGDAY FROM ashare_dates
        ) WHERE ROWNUM <= 200
        ORDER BY 1 DESC
    """)
    recent_200_dates = [r[0] for r in cur.fetchall()]
    print(f"[2/4] 加载最近 200 个 A 股市场交易日: {len(recent_200_dates)} 天 ({recent_200_dates[0]} ~ {recent_200_dates[-1]})")

    dates_in_sql = ",".join(f"TO_DATE('{d}', 'YYYY-MM-DD')" for d in recent_200_dates)
    codes_in_sql = ",".join(f"'{c}'" for c in SAMPLE_CODES)

    # 一次性读取 30 只股票基础元数据
    cur.execute(f"""
        SELECT S.INNERCODE, S.SECUCODE, COALESCE(S.SECUABBR, S.CHINAME) AS SECNAME, S.LISTEDDATE
        FROM ZBJYDB.SECUMAIN S
        WHERE S.SECUCODE IN ({codes_in_sql}) AND S.SECUCATEGORY = 1
    """)
    stock_meta = {r[1]: {"innercode": r[0], "secucode": r[1], "secname": r[2], "listed_date": r[3]} for r in cur.fetchall()}

    in_codes_list = ",".join(str(v["innercode"]) for v in stock_meta.values())
    cur.execute(f"""
        WITH all_quotes AS (
            SELECT INNERCODE, TRADINGDAY, CLOSEPRICE, TURNOVERVALUE FROM ZBJYDB.QT_DAILYQUOTE WHERE INNERCODE IN ({in_codes_list})
            UNION ALL
            SELECT INNERCODE, TRADINGDAY, CLOSEPRICE, TURNOVERVALUE FROM ZBJYDB.LC_STIBDAILYQUOTE WHERE INNERCODE IN ({in_codes_list})
        )
        SELECT 
            P.INNERCODE,
            P.TRADINGDAY,
            P.ADJOPENPRICE,
            P.ADJHIGHPRICE,
            P.ADJLOWPRICE,
            P.ADJCLOSEPRICE,
            COALESCE(Q.CLOSEPRICE, P.ADJCLOSEPRICE) AS RAW_CLOSEPRICE,
            COALESCE(Q.TURNOVERVALUE, 0)           AS TURNOVERVALUE
        FROM ZBJYDB.CS_STOCKADJPERFORMANCE P
        LEFT JOIN all_quotes Q
          ON P.INNERCODE = Q.INNERCODE AND P.TRADINGDAY = Q.TRADINGDAY
        WHERE P.INNERCODE IN ({in_codes_list})
          AND P.ADJUSTINGMETHOD = 1 
          AND P.ADJUSTINGSTANDARD = 1
          AND P.ADJCLOSEPRICE IS NOT NULL
        ORDER BY P.INNERCODE, P.TRADINGDAY ASC
    """)
    cols = [c[0] for c in cur.description]
    all_stock_quotes = defaultdict(list)
    for r in cur.fetchall():
        row_dict = dict(zip(cols, r))
        all_stock_quotes[row_dict["INNERCODE"]].append(row_dict)

    # 一次性执行生产 SQL 批量抽取 30 只股票全部特征
    sql_batch = f"""
    WITH ashare_stocks AS (
        SELECT 
            INNERCODE, 
            SECUCODE, 
            COALESCE(SECUABBR, CHINAME) AS SECNAME,
            LISTEDDATE
        FROM ZBJYDB.SECUMAIN
        WHERE SECUCODE IN ({codes_in_sql}) AND SECUCATEGORY = 1
    ),
    market_calendar AS (
        SELECT 
            TRADINGDATE,
            ROW_NUMBER() OVER (ORDER BY TRADINGDATE ASC) AS MARKET_TD_SEQ
        FROM ZBJYDB.QT_TRADINGDAYNEW
        WHERE SECUMARKET = 83 AND IFTRADINGDAY = 1
    ),
    all_quotes AS (
        SELECT INNERCODE, TRADINGDAY, CLOSEPRICE, TURNOVERVALUE FROM ZBJYDB.QT_DAILYQUOTE WHERE INNERCODE IN ({in_codes_list})
        UNION ALL
        SELECT INNERCODE, TRADINGDAY, CLOSEPRICE, TURNOVERVALUE FROM ZBJYDB.LC_STIBDAILYQUOTE WHERE INNERCODE IN ({in_codes_list})
    ),
    raw_base AS (
        SELECT 
            P.INNERCODE,
            P.TRADINGDAY,
            P.ADJOPENPRICE,
            P.ADJHIGHPRICE,
            P.ADJLOWPRICE,
            P.ADJCLOSEPRICE,
            COALESCE(Q.CLOSEPRICE, P.ADJCLOSEPRICE) AS RAW_CLOSEPRICE,
            COALESCE(Q.TURNOVERVALUE, 0)           AS TURNOVERVALUE,
            CASE WHEN COALESCE(Q.TURNOVERVALUE, 0) > 0 THEN 1 ELSE 0 END AS IS_TRADING
        FROM ZBJYDB.CS_STOCKADJPERFORMANCE P
        JOIN ashare_stocks S ON P.INNERCODE = S.INNERCODE
        LEFT JOIN all_quotes Q
          ON P.INNERCODE = Q.INNERCODE AND P.TRADINGDAY = Q.TRADINGDAY
        WHERE P.ADJUSTINGMETHOD = 1 
          AND P.ADJUSTINGSTANDARD = 1
          AND P.ADJCLOSEPRICE IS NOT NULL
    ),
    trading_quotes_only AS (
        SELECT
            INNERCODE,
            TRADINGDAY,
            ROW_NUMBER() OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ASC) AS TRADING_DAY_RN,
            MAX(ADJHIGHPRICE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS MAX_ALL_PRIOR,
            MAX(ADJHIGHPRICE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 500 PRECEDING AND 1 PRECEDING)       AS WIN_HIGH_500,
            MAX(ADJHIGHPRICE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 250 PRECEDING AND 1 PRECEDING)       AS WIN_HIGH_250
        FROM raw_base
        WHERE IS_TRADING = 1
    ),
    enriched_base AS (
        SELECT 
            b.INNERCODE,
            s.SECUCODE,
            s.SECNAME,
            s.LISTEDDATE,
            b.TRADINGDAY,
            b.ADJOPENPRICE,
            b.ADJHIGHPRICE,
            b.ADJLOWPRICE,
            b.ADJCLOSEPRICE,
            b.RAW_CLOSEPRICE,
            b.TURNOVERVALUE,
            b.IS_TRADING,
            c.MARKET_TD_SEQ,
            (c.MARKET_TD_SEQ - COALESCE(cl.MARKET_TD_SEQ, 0) + 1) AS LISTING_TDAYS,
            CASE WHEN b.ADJCLOSEPRICE > b.ADJOPENPRICE AND b.IS_TRADING = 1 THEN 1 ELSE 0 END AS IS_RED,
            CASE WHEN b.ADJCLOSEPRICE < b.ADJOPENPRICE AND b.IS_TRADING = 1 THEN 1 ELSE 0 END AS IS_GREEN,
            t.TRADING_DAY_RN,
            t.MAX_ALL_PRIOR,
            t.WIN_HIGH_500,
            t.WIN_HIGH_250
        FROM raw_base b
        JOIN ashare_stocks s ON b.INNERCODE = s.INNERCODE
        JOIN market_calendar c ON b.TRADINGDAY = c.TRADINGDATE
        LEFT JOIN market_calendar cl ON s.LISTEDDATE = cl.TRADINGDATE
        LEFT JOIN trading_quotes_only t ON b.INNERCODE = t.INNERCODE AND b.TRADINGDAY = t.TRADINGDAY
    ),
    window_stats AS (
        SELECT
            d.*,
            ROW_NUMBER() OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS rn,
            AVG(ADJCLOSEPRICE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 249 PRECEDING AND CURRENT ROW) AS MA250,
            AVG(ADJCLOSEPRICE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 376 PRECEDING AND CURRENT ROW) AS MA377,

            SUM(IS_TRADING) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN   4 PRECEDING AND CURRENT ROW) AS TRADING_CNT_5,
            SUM(IS_TRADING) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN   5 PRECEDING AND CURRENT ROW) AS TRADING_CNT_6,
            SUM(IS_TRADING) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN   3 PRECEDING AND CURRENT ROW) AS TRADING_CNT_4,
            SUM(IS_TRADING) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN  15 PRECEDING AND CURRENT ROW) AS TRADING_CNT_16,
            SUM(IS_TRADING) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 179 PRECEDING AND CURRENT ROW) AS TRADING_CNT_180,
            SUM(IS_TRADING) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 181 PRECEDING AND CURRENT ROW) AS TRADING_CNT_182,

            MIN(ADJLOWPRICE)   OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 9 PRECEDING AND CURRENT ROW)   AS RECENT_LOW_10,
            MAX(ADJHIGHPRICE)  OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 169 PRECEDING AND CURRENT ROW) AS WIN_HIGH_170,
            MIN(ADJLOWPRICE)   OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 29 PRECEDING AND CURRENT ROW)  AS WIN_LOW_30,
            MAX(ADJHIGHPRICE)  OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 179 PRECEDING AND CURRENT ROW) AS WIN_HIGH_180,

            MAX(TURNOVERVALUE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 14 PRECEDING AND CURRENT ROW) AS WIN_MAX_15,
            AVG(TURNOVERVALUE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 4 PRECEDING AND CURRENT ROW)  AS WIN_AVG_5,
            AVG(TURNOVERVALUE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 9 PRECEDING AND CURRENT ROW)  AS WIN_AVG_10,
            AVG(TURNOVERVALUE) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY ROWS BETWEEN 14 PRECEDING AND CURRENT ROW) AS WIN_AVG_15
        FROM enriched_base d
    ),
    lagged AS (
        SELECT
            w.*,
            LAG(MARKET_TD_SEQ, 1)   OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_SEQ_1,
            LAG(MARKET_TD_SEQ, 3)   OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_SEQ_3,
            LAG(MARKET_TD_SEQ, 4)   OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_SEQ_4,
            LAG(MARKET_TD_SEQ, 5)   OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_SEQ_5,
            LAG(MARKET_TD_SEQ, 15)  OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_SEQ_15,
            LAG(MARKET_TD_SEQ, 179) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_SEQ_179,
            LAG(MARKET_TD_SEQ, 181) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PREV_SEQ_181,

            LAG(IS_RED, 1) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS RED_T1,
            LAG(IS_RED, 2) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS RED_T2,
            LAG(IS_RED, 3) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS RED_T3,
            LAG(IS_RED, 4) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS RED_T4,
            LAG(IS_GREEN, 5) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS GREEN_T5,

            LAG(ADJOPENPRICE, 4) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS ADJ_OPEN_T4,
            LAG(WIN_HIGH_170, 10) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PRIOR_HIGH_170,
            LAG(WIN_LOW_30, 10) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PRIOR_LOW_30,

            LAG(TURNOVERVALUE, 1) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS AMT_1,
            LAG(WIN_MAX_15, 1) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS MAX_15,
            LAG(WIN_AVG_5, 1)  OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS AVG_5,
            LAG(WIN_AVG_10, 1) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS AVG_10,
            LAG(WIN_AVG_15, 1) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS AVG_15,
            LAG(ADJCLOSEPRICE, 10) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS ADJ_CLOSE_T10,

            LAG(ADJCLOSEPRICE, 1) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS ADJ_CLOSE_T1,
            LAG(WIN_HIGH_180, 2) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) AS PRIOR_HIGH_180,

            CASE WHEN MA250 > 0 THEN (ADJCLOSEPRICE / MA250 - 1.0) END AS DIST_250_T0,
            CASE WHEN LAG(MA250, 1) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) > 0 
                 THEN (LAG(ADJCLOSEPRICE, 1) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) / LAG(MA250, 1) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) - 1.0) END AS DIST_250_T1,
            CASE WHEN LAG(MA250, 2) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) > 0 
                 THEN (LAG(ADJCLOSEPRICE, 2) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) / LAG(MA250, 2) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) - 1.0) END AS DIST_250_T2,
            CASE WHEN LAG(MA250, 3) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) > 0 
                 THEN (LAG(ADJCLOSEPRICE, 3) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) / LAG(MA250, 3) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) - 1.0) END AS DIST_250_T3,

            CASE WHEN MA377 > 0 THEN (ADJCLOSEPRICE / MA377 - 1.0) END AS DIST_377_T0,
            CASE WHEN LAG(MA377, 1) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) > 0 
                 THEN (LAG(ADJCLOSEPRICE, 1) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) / LAG(MA377, 1) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) - 1.0) END AS DIST_377_T1,
            CASE WHEN LAG(MA377, 2) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) > 0 
                 THEN (LAG(ADJCLOSEPRICE, 2) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) / LAG(MA377, 2) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) - 1.0) END AS DIST_377_T2,
            CASE WHEN LAG(MA377, 3) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) > 0 
                 THEN (LAG(ADJCLOSEPRICE, 3) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) / LAG(MA377, 3) OVER (PARTITION BY INNERCODE ORDER BY TRADINGDAY) - 1.0) END AS DIST_377_T3
        FROM window_stats w
    ),
    calculated AS (
        SELECT
            l.*,
            CASE WHEN IS_RED = 1 AND RED_T1 = 1 AND RED_T2 = 1 AND RED_T3 = 1 AND RED_T4 = 1 
                  AND (MARKET_TD_SEQ - PREV_SEQ_4) = 4 AND TRADING_CNT_5 = 5
                 THEN 1 ELSE 0 END AS RED_5_STRICT,
            CASE WHEN (MARKET_TD_SEQ - PREV_SEQ_5) = 5 AND TRADING_CNT_6 = 6 THEN 1 ELSE 0 END AS IS_CONSEC_6D,
            CASE WHEN (MARKET_TD_SEQ - PREV_SEQ_3) = 3 AND TRADING_CNT_4 = 4 THEN 1 ELSE 0 END AS IS_CONSEC_4D,

            CASE WHEN (MARKET_TD_SEQ - PREV_SEQ_15) = 15   AND TRADING_CNT_16 = 16   THEN 1 ELSE 0 END AS IS_CONSEC_16D,
            CASE WHEN (MARKET_TD_SEQ - PREV_SEQ_179) = 179 AND TRADING_CNT_180 = 180 THEN 1 ELSE 0 END AS IS_CONSEC_180D,
            CASE WHEN (MARKET_TD_SEQ - PREV_SEQ_181) = 181 AND TRADING_CNT_182 = 182 THEN 1 ELSE 0 END AS IS_CONSEC_182D,

            CASE WHEN PRIOR_HIGH_170 > 0 THEN 1.0 - RECENT_LOW_10 / PRIOR_HIGH_170 ELSE 0 END AS DRAWDOWN_180,
            CASE WHEN PRIOR_LOW_30 > 0 THEN RECENT_LOW_10 / PRIOR_LOW_30 - 1.0 ELSE 0 END AS LOW_REBOUND_30,
            CASE WHEN ADJ_OPEN_T4 > 0 THEN ADJCLOSEPRICE / ADJ_OPEN_T4 - 1.0 ELSE 0 END AS FIVE_DAY_GAIN,
            CASE WHEN ADJ_CLOSE_T10 > 0 THEN ADJCLOSEPRICE / ADJ_CLOSE_T10 - 1.0 ELSE 0 END AS RETURN_10,
            CASE WHEN PRIOR_HIGH_180 > 0 THEN 1.0 - ADJ_CLOSE_T1 / PRIOR_HIGH_180 ELSE 0 END AS PREV_DRAWDOWN_180,
            CASE WHEN (IS_RED = 1 OR RED_T1 = 1 OR RED_T2 = 1 OR RED_T3 = 1) THEN 1 ELSE 0 END AS HAS_RED_4D
        FROM lagged l
    ),
    factored AS (
        SELECT
            c.*,
            CASE WHEN rn >= 180 AND IS_CONSEC_180D = 1 AND DRAWDOWN_180 > 0.25 AND LOW_REBOUND_30 < 0.10 AND RED_5_STRICT = 1 AND GREEN_T5 = 1 AND FIVE_DAY_GAIN < 0.13 THEN 1 ELSE 0 END AS FACTOR_HL_5R,
            CASE WHEN rn >= 6 AND RED_5_STRICT = 1 AND GREEN_T5 = 1 AND IS_CONSEC_6D = 1
                  AND NOT (rn >= 180 AND IS_CONSEC_180D = 1 AND DRAWDOWN_180 > 0.25 AND LOW_REBOUND_30 < 0.10 AND RED_5_STRICT = 1 AND GREEN_T5 = 1 AND FIVE_DAY_GAIN < 0.13) 
                 THEN 1 ELSE 0 END AS FACTOR_5R,

            CASE WHEN IS_TRADING = 1 AND LISTING_TDAYS > 500 AND TRADING_DAY_RN >= 501 AND ADJHIGHPRICE > MAX_ALL_PRIOR THEN 1 ELSE 0 END AS FACTOR_HIGH_ALL,
            CASE WHEN IS_TRADING = 1 AND LISTING_TDAYS > 500 AND TRADING_DAY_RN >= 501 AND ADJHIGHPRICE > WIN_HIGH_500 THEN 1 ELSE 0 END AS FACTOR_HIGH_500,
            CASE WHEN IS_TRADING = 1 AND LISTING_TDAYS > 250 AND TRADING_DAY_RN >= 251 AND ADJHIGHPRICE > WIN_HIGH_250 THEN 1 ELSE 0 END AS FACTOR_HIGH_250,

            CASE WHEN rn >= 16 AND IS_CONSEC_16D = 1 AND TURNOVERVALUE > 100000000.0 AND TURNOVERVALUE > 1.2 * MAX_15 
                  AND TURNOVERVALUE > 1.8 * AMT_1 AND TURNOVERVALUE > 1.8 * AVG_5 
                  AND TURNOVERVALUE > 1.8 * AVG_10 AND TURNOVERVALUE > 1.8 * AVG_15 
                  AND IS_RED = 1 AND RETURN_10 < 0.50 THEN 1 ELSE 0 END AS FACTOR_AMO,

            CASE WHEN rn >= 182 AND IS_CONSEC_182D = 1 AND TURNOVERVALUE > 100000000.0 AND TURNOVERVALUE > 1.2 * MAX_15 
                  AND TURNOVERVALUE > 1.8 * AMT_1 AND TURNOVERVALUE > 1.8 * AVG_5 
                  AND TURNOVERVALUE > 1.8 * AVG_10 AND TURNOVERVALUE > 1.8 * AVG_15 
                  AND IS_RED = 1 AND RETURN_10 < 0.50 AND PREV_DRAWDOWN_180 > 0.25 THEN 1 ELSE 0 END AS FACTOR_HL_AMO,

            CASE WHEN rn >= 253 AND HAS_RED_4D = 1 AND IS_CONSEC_4D = 1
                  AND DIST_250_T0 BETWEEN -0.02 AND 0.07
                  AND DIST_250_T1 BETWEEN -0.02 AND 0.07
                  AND DIST_250_T2 BETWEEN -0.02 AND 0.07
                  AND DIST_250_T3 BETWEEN -0.02 AND 0.07
                 THEN 1 ELSE 0 END AS FACTOR_MA250_SUPPORT,

            CASE WHEN rn >= 380 AND HAS_RED_4D = 1 AND IS_CONSEC_4D = 1
                  AND DIST_377_T0 BETWEEN -0.02 AND 0.07
                  AND DIST_377_T1 BETWEEN -0.02 AND 0.07
                  AND DIST_377_T2 BETWEEN -0.02 AND 0.07
                  AND DIST_377_T3 BETWEEN -0.02 AND 0.07
                 THEN 1 ELSE 0 END AS FACTOR_MA377_SUPPORT
        FROM calculated c
    )
    SELECT
        SECUCODE,
        TO_CHAR(TRADINGDAY, 'YYYY-MM-DD') AS T0,
        FACTOR_HL_5R,
        FACTOR_5R,
        FACTOR_HIGH_ALL,
        FACTOR_HIGH_500,
        FACTOR_HIGH_250,
        FACTOR_HL_AMO,
        FACTOR_AMO,
        FACTOR_MA377_SUPPORT,
        FACTOR_MA250_SUPPORT
    FROM factored
    WHERE TRADINGDAY IN ({dates_in_sql})
    ORDER BY SECUCODE, TRADINGDAY ASC
    """
    cur.execute(sql_batch)
    sql_batch_cols = [c[0] for c in cur.description]
    all_sql_results = defaultdict(dict)
    for r in cur.fetchall():
        r_dict = dict(zip(sql_batch_cols, r))
        all_sql_results[r_dict["SECUCODE"]][r_dict["T0"]] = r_dict

    conn.close()

    total_rows = 0
    total_mismatches = 0
    kcb_amo_positives = 0
    factor_keys = [
        "factor_hl_5r", "factor_5r", "factor_high_all", "factor_high_500", "factor_high_250",
        "factor_hl_amo", "factor_amo", "factor_ma377_support", "factor_ma250_support"
    ]

    for code in SAMPLE_CODES:
        meta = stock_meta[code]
        innercode = meta["innercode"]
        scode = meta["secucode"]
        sname = meta["secname"]
        listed_date = meta["listed_date"]

        listed_d_str = listed_date.strftime("%Y-%m-%d") if listed_date else "1990-01-01"
        listed_seq = market_seq_map.get(listed_d_str, 0)

        quote_rows = all_stock_quotes[innercode]

        listing_tdays_map = {}
        for r in quote_rows:
            d_s = r["TRADINGDAY"].strftime("%Y-%m-%d")
            cur_seq = market_seq_map.get(d_s, 0)
            listing_tdays_map[d_s] = cur_seq - listed_seq + 1

        py_results = compute_factors_py(
            quote_rows, 
            market_td_seq_map=market_seq_map, 
            listing_tdays_map=listing_tdays_map
        )
        py_map = {r["date"]: r for r in py_results}

        if scode == '688012':
            val_0105 = py_map.get("2026-01-05")
            if val_0105:
                assert val_0105["factor_amo"] == 0, f"[FATAL REGRESSION] 688012 在 2026-01-05 误判命中 AMO! (实际={val_0105['factor_amo']})"
                print(f"  [REGRESSION ASSERTION PASS] 688012 在 2026-01-05 因停牌日约束严格判定 FACTOR_AMO=0!")

        sql_stock_map = all_sql_results[scode]

        mismatch_stock = 0
        for d_str in recent_200_dates:
            srow = sql_stock_map.get(d_str)
            py_row = py_map.get(d_str)
            if not srow or not py_row:
                print(f"[FATAL] 缺少 {scode} {d_str} 记录!")
                sys.exit(1)

            total_rows += 1
            if scode.startswith("68") and int(srow["FACTOR_AMO"]) == 1:
                kcb_amo_positives += 1
            for fk in factor_keys:
                sql_val = int(srow[fk.upper()])
                py_val = int(py_row[fk])
                if sql_val != py_val:
                    mismatch_stock += 1
                    total_mismatches += 1
                    print(f"  [MISMATCH] {scode} {d_str} {fk}: SQL={sql_val}, PY={py_val}")

        status = f"PASSED (200 rows checked, 0 mismatches)" if mismatch_stock == 0 else f"FAILED ({mismatch_stock} mismatches)"
        board_name = "科创板" if scode.startswith("68") else ("创业板" if scode.startswith("30") else ("深市主板" if scode.startswith("00") else "沪市主板"))
        print(f"[{board_name}] {scode} ({sname:6s}): {status}")

    print("-" * 75)
    print(f"总比对股票数: {len(SAMPLE_CODES)} 只 (含 6 只科创板)")
    print(f"总比对行数: {total_rows:,} 行 (严格等于 30 x 200 = 6,000 行)")
    print(f"科创板 AMO 正例命中数: {kcb_amo_positives} 次")
    print(f"总不一致数: {total_mismatches} (一致率: {100.0 * (1 - total_mismatches / max(total_rows, 1)):.2f}%)")
    print("=" * 75)

    if total_mismatches > 0 or total_rows != 6000:
        print("[FAIL] 校验未达到 100% 6,000 行通过标准!")
        sys.exit(1)
    else:
        print("[SUCCESS] 30 只股票 x 200 交易日 = 6,000 行 100% 零误差全部通过!")

if __name__ == "__main__":
    main()
