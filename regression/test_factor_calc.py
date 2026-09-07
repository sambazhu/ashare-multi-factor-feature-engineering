#!/usr/bin/env python3
"""
Python 独立因子计算参考模型 (Pure Python / Ground Truth - 原始需求严格 LISTING_TDAYS > 500 版)
1. 基于 CS_StockAdjPerformance(1,1) 前复权精确复权主口径
2. 合并 QT_DAILYQUOTE + LC_STIBDAILYQUOTE 真实成交额
3. 停牌行情行强约束:
   - IS_TRADING = 1 if TURNOVERVALUE > 0 else 0
   - 各时间窗口内 SUM(IS_TRADING) 必须严格等于窗口总天数（无任何 1 天停牌占位行）
4. 新高严格基于【有效正常交易行情日】计算 + 原始需求 LISTING_TDAYS 严格门槛:
   - HIGH_ALL: LISTING_TDAYS > 500 且突破覆盖期所有前序有效交易日最高价
   - HIGH_500: LISTING_TDAYS > 500 且有效交易日 >= 501 且突破过去 500 个有效交易日最高价 (未破全量前高)
   - HIGH_250: LISTING_TDAYS > 250 且有效交易日 >= 251 且突破过去 250 个有效交易日最高价 (未破前二者)
   - 次新股 (如上市 300 天) 突破所有前高时: HIGH_ALL=0, 成功降级命中 HIGH_250=1 (D250)
"""
import os
import sys
import datetime
import oracledb

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"))
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(BASE_DIR))
import oracle_jydb_helper

def get_db_conn():
    return oracle_jydb_helper.get_connection()

def compute_factors_py(rows, market_td_seq_map=None, listing_tdays_map=None):
    if market_td_seq_map is None: market_td_seq_map = {}
    if listing_tdays_map is None: listing_tdays_map = {}

    enriched = []
    valid_trading_cum = 0

    for r in rows:
        d_val = r["TRADINGDAY"]
        d_str = d_val.strftime("%Y-%m-%d") if hasattr(d_val, "strftime") else str(d_val)

        adj_o = float(r["ADJOPENPRICE"])
        adj_h = float(r["ADJHIGHPRICE"])
        adj_l = float(r["ADJLOWPRICE"])
        adj_c = float(r["ADJCLOSEPRICE"])
        raw_c = float(r.get("RAW_CLOSEPRICE") or r.get("CLOSEPRICE") or adj_c)
        turnover = float(r.get("TURNOVERVALUE") or 0.0)

        td_seq = market_td_seq_map.get(d_str, 0)
        listing_tdays = listing_tdays_map.get(d_str, 9999)

        is_trading = 1 if turnover > 0.0 else 0
        if is_trading == 1:
            valid_trading_cum += 1
            valid_trading_rn = valid_trading_cum
        else:
            valid_trading_rn = valid_trading_cum

        is_red = 1 if (adj_c > adj_o and is_trading == 1) else 0
        is_green = 1 if (adj_c < adj_o and is_trading == 1) else 0

        enriched.append({
            "date": d_val,
            "date_str": d_str,
            "td_seq": td_seq,
            "listing_tdays": listing_tdays,
            "adj_o": adj_o, "adj_h": adj_h, "adj_l": adj_l, "adj_c": adj_c,
            "raw_c": raw_c,
            "turnover": turnover,
            "is_trading": is_trading,
            "valid_trading_rn": valid_trading_rn,
            "is_red": is_red,
            "is_green": is_green
        })

    results = []
    n = len(enriched)

    for i in range(n):
        cur = enriched[i]
        date_str = cur["date_str"]
        history_bars = i + 1
        listing_tdays = cur["listing_tdays"]
        is_trading = cur["is_trading"]
        valid_rn = cur["valid_trading_rn"]

        # 双重无停牌连续性校验 (序号等差 + 窗口内无任何停牌日)
        def is_valid_trading_window(k_bars):
            if i < k_bars:
                return False
            seq_curr = enriched[i]["td_seq"]
            seq_start = enriched[i - k_bars]["td_seq"]
            if (seq_curr - seq_start) != k_bars:
                return False
            window_trading_sum = sum(enriched[i - k]["is_trading"] for k in range(k_bars + 1))
            if window_trading_sum != (k_bars + 1):
                return False
            return True

        # 1. HL+5R (180 根 K 线完整无停牌，且严格 5 连红 + T-5 为阴线)
        def eval_hl_5r():
            if history_bars < 180 or not is_valid_trading_window(179) or not is_valid_trading_window(5):
                return 0, {}
            red_5 = all(enriched[i - k]["is_red"] == 1 for k in range(5))
            green_t5 = enriched[i - 5]["is_green"] == 1
            if not (red_5 and green_t5):
                return 0, {}

            lows_10 = [enriched[i - k]["adj_l"] for k in range(10)]
            recent_low_10 = min(lows_10)

            highs_170 = [enriched[i - k]["adj_h"] for k in range(10, 180)]
            prior_high_170 = max(highs_170)

            lows_30 = [enriched[i - k]["adj_l"] for k in range(10, 40)]
            prior_low_30 = min(lows_30)

            drawdown_180 = 1.0 - recent_low_10 / prior_high_170 if prior_high_170 > 0 else 0.0
            low_rebound_30 = recent_low_10 / prior_low_30 - 1.0 if prior_low_30 > 0 else 0.0

            open_t4 = enriched[i - 4]["adj_o"]
            close_t0 = enriched[i]["adj_c"]
            five_day_gain = close_t0 / open_t4 - 1.0 if open_t4 > 0 else 0.0

            c1 = drawdown_180 > 0.25
            c2 = low_rebound_30 < 0.10
            c3 = red_5
            c4 = five_day_gain < 0.13

            label = 1 if (c1 and c2 and c3 and c4) else 0
            details = {
                "recent_low_10": recent_low_10, "prior_high_170": prior_high_170,
                "prior_low_30": prior_low_30, "drawdown_180": drawdown_180,
                "low_rebound_30": low_rebound_30, "five_day_gain": five_day_gain
            }
            return label, details

        # 2. 5R (需要至少 6 根 K 线且 6 日连续无停牌，排除 HL+5R)
        def eval_5r(hl_5r_label):
            if history_bars < 6 or not is_valid_trading_window(5):
                return 0
            red_5 = all(enriched[i - k]["is_red"] == 1 for k in range(5))
            green_t5 = enriched[i - 5]["is_green"] == 1
            if red_5 and green_t5 and (hl_5r_label == 0):
                return 1
            return 0

        # 3. 创新高系列 (包含口径: 突破长周期前高亦属于短周期新高)
        def eval_highs():
            high_t0 = cur["adj_h"]
            is_ath = 0
            is_h500 = 0
            is_h250 = 0
            high_type = "NONE"

            if is_trading == 1 and valid_rn >= 2:
                # 提取截止 T-1 为止的所有前序有效交易日最高价
                prior_trading_highs = [
                    enriched[k]["adj_h"] 
                    for k in range(i) 
                    if enriched[k]["is_trading"] == 1
                ]
                
                if prior_trading_highs:
                    max_all_prior = max(prior_trading_highs)
                    
                    # 1. 覆盖期新高: LISTING_TDAYS > 500 且 突破覆盖期所有前序有效交易日前高
                    if listing_tdays > 500 and high_t0 > max_all_prior:
                        is_ath = 1

                    # 2. 500日新高 (包含口径: 破全高亦属500日新高)
                    if listing_tdays > 500 and ((len(prior_trading_highs) >= 500 and high_t0 > max(prior_trading_highs[-500:])) or is_ath == 1):
                        is_h500 = 1

                    # 3. 250日新高 (包含口径: 破全高亦属250日新高)
                    if listing_tdays > 250 and ((len(prior_trading_highs) >= 250 and high_t0 > max(prior_trading_highs[-250:])) or is_ath == 1):
                        is_h250 = 1

                    if is_ath == 1:
                        high_type = "ALL_TIME"
                    elif is_h500 == 1:
                        high_type = "D500"
                    elif is_h250 == 1:
                        high_type = "D250"

            return is_ath, is_h500, is_h250, high_type

        # 4. AMO (16 根 K 线连续且无停牌日)
        def eval_amo():
            if history_bars < 16 or not is_valid_trading_window(15):
                return 0, {}
            t0_amt = cur["turnover"]
            if t0_amt <= 100000000.0:
                return 0, {}

            amt_1 = enriched[i - 1]["turnover"]
            amts_15 = [enriched[i - k]["turnover"] for k in range(1, 16)]
            max_15 = max(amts_15)
            avg_5 = sum(amts_15[:5]) / 5.0
            avg_10 = sum(amts_15[:10]) / 10.0
            avg_15 = sum(amts_15) / 15.0

            close_t0 = cur["adj_c"]
            close_t10 = enriched[i - 10]["adj_c"]
            return_10 = close_t0 / close_t10 - 1.0 if close_t10 > 0 else 0.0

            c1 = t0_amt > 100000000.0
            c2 = t0_amt > 1.2 * max_15
            c3 = t0_amt > 1.8 * amt_1
            c4 = t0_amt > 1.8 * avg_5
            c5 = t0_amt > 1.8 * avg_10
            c6 = t0_amt > 1.8 * avg_15
            c7 = cur["is_red"] == 1
            c8 = return_10 < 0.50

            label = 1 if (c1 and c2 and c3 and c4 and c5 and c6 and c7 and c8) else 0
            details = {
                "t0_amt": t0_amt, "amt_1": amt_1, "max_15": max_15,
                "avg_5": avg_5, "avg_10": avg_10, "avg_15": avg_15, "return_10": return_10
            }
            return label, details

        # 5. HL+AMO (182 根 K 线连续无停牌日)
        def eval_hl_amo(amo_label):
            if amo_label == 0 or history_bars < 182 or not is_valid_trading_window(181):
                return 0, {}

            highs_180 = [enriched[i - k]["adj_h"] for k in range(2, 182)]
            prior_high_180 = max(highs_180)
            close_t1 = enriched[i - 1]["adj_c"]

            prev_drawdown_180 = 1.0 - close_t1 / prior_high_180 if prior_high_180 > 0 else 0.0
            label = 1 if prev_drawdown_180 > 0.25 else 0
            details = {
                "prior_high_180": prior_high_180, "close_t1": close_t1, "prev_drawdown_180": prev_drawdown_180
            }
            return label, details

        # 6. MA250 与 MA377 支撑 (4 交易日连续无停牌日)
        def eval_ma_support():
            f_ma250 = 0
            f_ma377 = 0

            if history_bars >= 4 and is_valid_trading_window(3):
                has_red = any(enriched[i - k]["is_red"] == 1 for k in range(4))
                if has_red:
                    if history_bars >= 253:
                        valid_250 = True
                        for k in range(4):
                            idx = i - k
                            c_k = enriched[idx]["adj_c"]
                            vals_250 = [enriched[idx - m]["adj_c"] for m in range(250)]
                            ma_250_k = sum(vals_250) / 250.0
                            d = c_k / ma_250_k - 1.0
                            if not (-0.02 <= d <= 0.07):
                                valid_250 = False
                                break
                        if valid_250:
                            f_ma250 = 1

                    if history_bars >= 380:
                        valid_377 = True
                        for k in range(4):
                            idx = i - k
                            c_k = enriched[idx]["adj_c"]
                            vals_377 = [enriched[idx - m]["adj_c"] for m in range(377)]
                            ma_377_k = sum(vals_377) / 377.0
                            d = c_k / ma_377_k - 1.0
                            if not (-0.02 <= d <= 0.07):
                                valid_377 = False
                                break
                        if valid_377:
                            f_ma377 = 1

            ma_supp_type = "BOTH" if (f_ma250 == 1 and f_ma377 == 1) else ("MA377" if f_ma377 == 1 else ("MA250" if f_ma250 == 1 else "NONE"))
            return f_ma250, f_ma377, ma_supp_type

        # 7. 均线超级多头排列 (LABEL: 必须为正常交易日 IS_TRADING=1 且满足双日六线排列与上升，杜绝停牌复牌首日均线冻结误判)
        def eval_label():
            if history_bars < 250 or is_trading != 1:
                return 0, 0, 0, 0

            def calc_ma(idx, window):
                return sum(enriched[idx - m]["adj_c"] for m in range(window)) / float(window)

            ma5 = calc_ma(i, 5)
            ma10 = calc_ma(i, 10)
            ma20 = calc_ma(i, 20)
            ma60 = calc_ma(i, 60)
            ma120 = calc_ma(i, 120)
            ma250 = calc_ma(i, 250)

            align_t0 = 1 if (ma5 > ma10 > ma20 > ma60 > ma120 > ma250 and is_trading == 1) else 0

            if history_bars < 251 or i < 1:
                return 0, align_t0, 0, 0

            # 必须前一日也是有效正常交易日 (TRADING_CNT_2 = 2) 且日历等差无停牌
            trading_cnt_2_ok = (enriched[i - 1]["is_trading"] == 1 and is_trading == 1)
            consec_day_ok = ((cur["td_seq"] - enriched[i - 1]["td_seq"]) == 1)

            p_ma5 = calc_ma(i - 1, 5)
            p_ma10 = calc_ma(i - 1, 10)
            p_ma20 = calc_ma(i - 1, 20)
            p_ma60 = calc_ma(i - 1, 60)
            p_ma120 = calc_ma(i - 1, 120)
            p_ma250 = calc_ma(i - 1, 250)

            align_t1 = 1 if (p_ma5 > p_ma10 > p_ma20 > p_ma60 > p_ma120 > p_ma250) else 0
            all_up = 1 if (ma5 > p_ma5 and ma10 > p_ma10 and ma20 > p_ma20 and ma60 > p_ma60 and ma120 > p_ma120 and ma250 > p_ma250) else 0

            label = 1 if (align_t0 == 1 and align_t1 == 1 and all_up == 1 and trading_cnt_2_ok and consec_day_ok) else 0
            return label, align_t0, align_t1, all_up

        hl_5r_lbl, hl_5r_dt = eval_hl_5r()
        f_5r_lbl = eval_5r(hl_5r_lbl)
        ath_lbl, h500_lbl, h250_lbl, htype = eval_highs()
        amo_lbl, amo_dt = eval_amo()
        hl_amo_lbl, hl_amo_dt = eval_hl_amo(amo_lbl)
        ma250_lbl, ma377_lbl, ma_type = eval_ma_support()
        label_lbl, a_t0, a_t1, a_up = eval_label()

        if hl_5r_lbl == 1: primary_factor = "HL_5R"
        elif f_5r_lbl == 1: primary_factor = "5R"
        elif ath_lbl == 1: primary_factor = "HIGH_ALL"
        elif h500_lbl == 1: primary_factor = "HIGH_500"
        elif h250_lbl == 1: primary_factor = "HIGH_250"
        elif hl_amo_lbl == 1: primary_factor = "HL_AMO"
        elif amo_lbl == 1: primary_factor = "AMO"
        elif ma377_lbl == 1: primary_factor = "MA377_SUPPORT"
        elif ma250_lbl == 1: primary_factor = "MA250_SUPPORT"
        else: primary_factor = "NONE"

        results.append({
            "date": date_str,
            "history_bars": history_bars,
            "listing_tdays": listing_tdays,
            "valid_trading_rn": valid_rn,
            "close": cur["raw_c"],
            "adj_close": cur["adj_c"],
            "raw_close": cur["raw_c"],
            "turnover": cur["turnover"],
            "is_trading": cur["is_trading"],
            
            "primary_factor": primary_factor,
            "high_type": htype,
            "ma_support_type": ma_type,
            "factor_hl_5r": hl_5r_lbl,
            "factor_5r": f_5r_lbl,
            "factor_high_all": ath_lbl,
            "factor_high_500": h500_lbl,
            "factor_high_250": h250_lbl,
            "factor_hl_amo": hl_amo_lbl,
            "factor_amo": amo_lbl,
            "factor_ma377_support": ma377_lbl,
            "factor_ma250_support": ma250_lbl,
            "label": label_lbl,
            "align_t0": a_t0,
            "align_t1": a_t1,
            "all_up": a_up
        })

    return results
