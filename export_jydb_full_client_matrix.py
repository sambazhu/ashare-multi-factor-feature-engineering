#!/usr/bin/env python3
"""
export_jydb_full_client_matrix.py (极速深度关联版)
将全市场 5,568 只 A 股上市公司的 7 大核心要素与 28,000+ 条客户明细进行全量深度关联：
1. 宽表: data/jydb_stock_clients_matrix.csv (每只股票一行，横向展开前 1~5 大客户的名称、金额、占比与合计)
2. 长表: data/jydb_client_details_long.csv (每个客户一行，共 2.8 万+ 条，适合客户网络穿透与产业链分析)
3. 结构化 JSON: data/jydb_stock_clients_matrix.json
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True)

import time
import json
import csv
from datetime import datetime

import oracle_jydb_helper


def export_full_client_matrix():
    t0 = time.time()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 正在连接聚源 Oracle 数据库并抽取客户明细与公司画像...", flush=True)

    conn = oracle_jydb_helper.get_connection()
    cur = conn.cursor()

    # 1. 抽取申万 2021 版 1/2/3 级行业分类
    print("  ├─ [1/4] 读取申万行业分类 (LC_EXGINDUSTRY)...", flush=True)
    sql_sw = """
    WITH ranked_ind AS (
        SELECT 
            COMPANYCODE,
            FIRSTINDUSTRYNAME as SW_IND1,
            SECONDINDUSTRYNAME as SW_IND2,
            THIRDINDUSTRYNAME as SW_IND3,
            ROW_NUMBER() OVER (PARTITION BY COMPANYCODE ORDER BY INFOPUBLDATE DESC, ID DESC) as rn
        FROM ZBJYDB.LC_EXGINDUSTRY
        WHERE STANDARD = 38
    )
    SELECT COMPANYCODE, SW_IND1, SW_IND2, SW_IND3 FROM ranked_ind WHERE rn = 1
    """
    cur.execute(sql_sw)
    sw_map = {r[0]: (f"{r[1]} - {r[2]} - {r[3]}", r[1], r[2], r[3]) for r in cur.fetchall()}

    # 2. 抽取公司主营业务与简介 (LC_STOCKARCHIVES - 使用 TO_CHAR 极速切片)
    print("  ├─ [2/4] 读取公司主营业务与主要产品 (LC_STOCKARCHIVES)...", flush=True)
    sql_arch = """
    WITH latest_arch_ids AS (
        SELECT ID FROM (
            SELECT ID, ROW_NUMBER() OVER (PARTITION BY COMPANYCODE ORDER BY XGRQ DESC, ID DESC) rn
            FROM ZBJYDB.LC_STOCKARCHIVES
        ) WHERE rn = 1
    )
    SELECT A.COMPANYCODE, 
           TO_CHAR(SUBSTR(A.BUSINESSMAJOR, 1, 800)) as BUSINESSMAJOR,
           TO_CHAR(SUBSTR(A.BRIEFINTROTEXT, 1, 800)) as BRIEFINTROTEXT
    FROM ZBJYDB.LC_STOCKARCHIVES A JOIN latest_arch_ids L ON A.ID = L.ID
    """
    cur.execute(sql_arch)
    arch_map = {}
    for comp_code, maj_str, intro_str in cur.fetchall():
        arch_map[comp_code] = {"major": (maj_str or "").strip(), "intro": (intro_str or "").strip()}

    # 3. 抽取 A 股主表证券信息 (SECUMAIN)
    print("  ├─ [3/4] 读取全市场 A 股证券主表 (SECUMAIN)...", flush=True)
    sql_main = """
    SELECT COMPANYCODE, SECUCODE, SECUABBR, CHINAME
    FROM ZBJYDB.SECUMAIN
    WHERE SUBSTR(SECUCODE, 1, 2) IN ('60', '68', '00', '30')
      AND SECUCATEGORY = 1
    ORDER BY SECUCODE ASC
    """
    cur.execute(sql_main)
    secu_list = cur.fetchall()
    secu_map = {r[0]: {"code": r[1], "name": r[2], "company_name": r[3]} for r in secu_list}

    # 4. 抽取最新一期年报的所有客户明细 (LC_SUPPCUSTDETAIL)
    print("  └─ [4/4] 关联抽取全市场最新期 28,000+ 条客户明细 (LC_SUPPCUSTDETAIL)...", flush=True)
    sql_cust = """
    WITH latest_cust_period AS (
        SELECT COMPANYCODE, MAX(ENDDATE) as MAX_ENDDATE
        FROM ZBJYDB.LC_SUPPCUSTDETAIL
        WHERE RELATIONTYPE = 4
        GROUP BY COMPANYCODE
    ),
    ranked_cust AS (
        SELECT 
            C.COMPANYCODE,
            TO_CHAR(C.ENDDATE, 'YYYY') as REPORT_YEAR,
            C.SERIALNUMBER,
            C.RELATEDPARTYNAME,
            C.TARGETNAME,
            C.TRADINGVALUE,
            C.RATIO,
            C.REMARK
        FROM ZBJYDB.LC_SUPPCUSTDETAIL C
        JOIN latest_cust_period P 
          ON C.COMPANYCODE = P.COMPANYCODE AND C.ENDDATE = P.MAX_ENDDATE
        WHERE C.RELATIONTYPE = 4
    )
    SELECT 
        COMPANYCODE,
        REPORT_YEAR,
        SERIALNUMBER,
        RELATEDPARTYNAME,
        TARGETNAME,
        TRADINGVALUE,
        RATIO,
        REMARK
    FROM ranked_cust
    ORDER BY COMPANYCODE ASC, SERIALNUMBER ASC
    """
    cur.execute(sql_cust)
    cust_rows = cur.fetchall()
    conn.close()

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 数据库查询完成 (耗时: {time.time()-t0:.2f}s)！正在构建宽表与明细长表...", flush=True)

    # 聚合客户数据 (按 companycode 分组)
    stock_clients_dict = {}
    long_records = []

    for r in cust_rows:
        comp_code, yr, seq, client_name, target, val, ratio, remark = r
        if comp_code not in secu_map:
            continue

        s_info = secu_map[comp_code]
        sw_full = sw_map.get(comp_code, ("未分类", "", "", ""))[0]

        client_clean_name = (client_name or "").strip()
        val_yi = round(val / 1e8, 4) if val is not None else None
        ratio_val = round(ratio, 2) if ratio is not None else None

        # 构建长表明细
        long_records.append({
            "股票代码": s_info["code"],
            "股票名称": s_info["name"] or "",
            "公司名称": s_info["company_name"] or "",
            "所属行业": sw_full,
            "报告年份": yr or "",
            "客户排名序号": seq if seq != 999 else "前五大合计",
            "客户名称": client_clean_name,
            "交易标的": (target or "").strip(),
            "销售金额(元)": val if val is not None else "",
            "销售金额(亿元)": val_yi if val_yi is not None else "",
            "销售占比(%)": ratio_val if ratio_val is not None else "",
            "备注说明": (remark or "").strip()
        })

        if comp_code not in stock_clients_dict:
            stock_clients_dict[comp_code] = {"year": yr, "clients": {}, "top5_total": {}}

        if seq == 999:
            stock_clients_dict[comp_code]["top5_total"] = {"val": val_yi, "ratio": ratio_val}
        elif 1 <= seq <= 5:
            stock_clients_dict[comp_code]["clients"][seq] = {
                "name": client_clean_name,
                "val": val_yi,
                "ratio": ratio_val
            }

    # 构建宽表 (包含全市场 5568 只 A 股)
    wide_records = []
    matrix_json = []

    for comp_code, s_info in secu_map.items():
        code = s_info["code"]
        abbr = s_info["name"]
        full_name = s_info["company_name"]
        sw_full, sw1, sw2, sw3 = sw_map.get(comp_code, ("未分类", "未分类", "未分类", "未分类"))
        arch_info = arch_map.get(comp_code, {})

        maj_text = arch_info.get("major", "")
        intro_text = arch_info.get("intro", "")
        major_business = maj_text if maj_text else (intro_text[:200] if intro_text else "详见公司主营业务定期报告披露")
        primary_products = maj_text if maj_text else "详见定期报告主要产品列表"

        c_data = stock_clients_dict.get(comp_code, {"year": "", "clients": {}, "top5_total": {}})
        yr = c_data.get("year", "")
        clients = c_data.get("clients", {})
        top5_tot = c_data.get("top5_total", {})

        def get_client(seq):
            c = clients.get(seq, {})
            return c.get("name", ""), c.get("val", ""), c.get("ratio", "")

        c1_name, c1_val, c1_ratio = get_client(1)
        c2_name, c2_val, c2_ratio = get_client(2)
        c3_name, c3_val, c3_ratio = get_client(3)
        c4_name, c4_val, c4_ratio = get_client(4)
        c5_name, c5_val, c5_ratio = get_client(5)

        tot_val = top5_tot.get("val", "")
        tot_ratio = top5_tot.get("ratio", "")

        row = {
            "股票代码": code,
            "股票名称": abbr or "",
            "公司名称": full_name or abbr or "",
            "所属行业": sw_full,
            "主要业务": major_business,
            "主要产品": primary_products,
            "报告年份": yr,
            "第一大客户名称": c1_name,
            "第一大客户金额(亿元)": c1_val,
            "第一大客户占比(%)": c1_ratio,
            "第二大客户名称": c2_name,
            "第二大客户金额(亿元)": c2_val,
            "第二大客户占比(%)": c2_ratio,
            "第三大客户名称": c3_name,
            "第三大客户金额(亿元)": c3_val,
            "第三大客户占比(%)": c3_ratio,
            "第四大客户名称": c4_name,
            "第四大客户金额(亿元)": c4_val,
            "第四大客户占比(%)": c4_ratio,
            "第五大客户名称": c5_name,
            "第五大客户金额(亿元)": c5_val,
            "第五大客户占比(%)": c5_ratio,
            "前五大客户合计金额(亿元)": tot_val,
            "前五大客户合计占比(%)": tot_ratio
        }
        wide_records.append(row)

        matrix_json.append({
            "secu_code": code,
            "secu_name": abbr or "",
            "company_name": full_name or "",
            "industry": sw_full,
            "major_business": major_business,
            "primary_products": primary_products,
            "report_year": yr,
            "top_clients": [
                {"rank": 1, "name": c1_name, "amount_yi": c1_val, "ratio_pct": c1_ratio},
                {"rank": 2, "name": c2_name, "amount_yi": c2_val, "ratio_pct": c2_ratio},
                {"rank": 3, "name": c3_name, "amount_yi": c3_val, "ratio_pct": c3_ratio},
                {"rank": 4, "name": c4_name, "amount_yi": c4_val, "ratio_pct": c4_ratio},
                {"rank": 5, "name": c5_name, "amount_yi": c5_val, "ratio_pct": c5_ratio},
            ],
            "top5_total": {"amount_yi": tot_val, "ratio_pct": tot_ratio}
        })

    base_dir = os.path.dirname(__file__)
    data_dir = os.path.join(base_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    wide_csv = os.path.join(data_dir, "jydb_stock_clients_matrix.csv")
    long_csv = os.path.join(data_dir, "jydb_client_details_long.csv")
    matrix_json_file = os.path.join(data_dir, "jydb_stock_clients_matrix.json")

    # 1. 导出宽表 CSV
    wide_fieldnames = list(wide_records[0].keys())
    with open(wide_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=wide_fieldnames)
        writer.writeheader()
        writer.writerows(wide_records)

    # 2. 导出长表明细 CSV
    long_fieldnames = list(long_records[0].keys())
    with open(long_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=long_fieldnames)
        writer.writeheader()
        writer.writerows(long_records)

    # 3. 导出 JSON
    with open(matrix_json_file, "w", encoding="utf-8") as f:
        json.dump(matrix_json, f, ensure_ascii=False, indent=2)

    total_time = time.time() - t0
    print(f"\n==================================================", flush=True)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎉 全市场客户明细深度关联导出全部完成！", flush=True)
    print(f"  - 覆盖上市公司: {len(wide_records)} 只 A 股 (100% 全覆盖)")
    print(f"  - 导出客户明细: {len(long_records)} 条记录")
    print(f"  - 全流程耗时: {total_time:.2f} 秒")
    print(f"  - 【宽表】前五大客户矩阵: {wide_csv}")
    print(f"  - 【长表】客户关系明细表: {long_csv}")
    print(f"  - 【JSON】结构化矩阵字典: {matrix_json_file}")
    print(f"==================================================\n", flush=True)


if __name__ == "__main__":
    export_full_client_matrix()
