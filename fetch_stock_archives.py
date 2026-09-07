#!/usr/bin/env python3
"""
fetch_stock_archives.py
从聚源 Oracle 测试库（ZBJYDB.LC_STOCKARCHIVES）抽取全市场 A 股上市公司最新的
【主营业务（BusinessMajor）、兼营业务（BusinessMinor）、公司简介（BriefIntroText）】大文本，
并自动合并申万 2021 版 1/2/3 级行业分类（sw_industry_map.json）。

产物落盘: data/raw_stock_archives.json
"""

import os
import sys
import json
import argparse
import time
from datetime import datetime

import oracle_jydb_helper


def load_sw_industry_map():
    map_file = os.path.join(os.path.dirname(__file__), "sw_industry_map.json")
    if os.path.exists(map_file):
        with open(map_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def fetch_stock_archives(limit: int = 0):
    """
    从 Oracle 抽取上市公司最新的大文本档案并合并行业分类
    """
    output_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "raw_stock_archives.json")

    sw_map = load_sw_industry_map()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 已加载申万行业分类映射库 (共 {len(sw_map)} 条)")

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 正在连接 Oracle 数据库...")
    conn = oracle_jydb_helper.get_connection()
    cur = conn.cursor()

    # 查询最新档案记录（按 XGRQ DESC, ID DESC 取每家公司最新一条）
    sql = """
    WITH latest_sa AS (
        SELECT 
            COMPANYCODE,
            ID,
            ROW_NUMBER() OVER (PARTITION BY COMPANYCODE ORDER BY XGRQ DESC, ID DESC) as rn
        FROM ZBJYDB.LC_STOCKARCHIVES
    ),
    filtered_sa AS (
        SELECT COMPANYCODE, ID
        FROM latest_sa
        WHERE rn = 1
    )
    SELECT 
        SM.INNERCODE,
        SM.COMPANYCODE,
        SM.SECUCODE,
        SM.SECUABBR,
        SA.BUSINESSMAJOR,
        SA.BUSINESSMINOR,
        SA.BRIEFINTROTEXT,
        TO_CHAR(SA.XGRQ, 'YYYY-MM-DD HH24:MI:SS') as XGRQ
    FROM ZBJYDB.SECUMAIN SM
    JOIN filtered_sa f ON SM.COMPANYCODE = f.COMPANYCODE
    JOIN ZBJYDB.LC_STOCKARCHIVES SA ON f.ID = SA.ID
    WHERE SUBSTR(SM.SECUCODE, 1, 2) IN ('60', '68', '00', '30')
      AND SM.SECUCATEGORY = 1
    ORDER BY SM.SECUCODE ASC
    """

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 正在执行全市场上市公司大文本 SQL 查询...")
    start_t = time.time()
    cur.execute(sql)

    records = []
    total_fetched = 0

    print(f"[{datetime.now().strftime('%H:%M:%S')}] SQL 执行完毕，开始读取并反序列化 NCLOB 大文本...")

    while True:
        rows = cur.fetchmany(500)
        if not rows:
            break
        for row in rows:
            inner_code, comp_code, secu_code, secu_abbr, b_maj, b_min, intro, xgrq = row
            
            # 读取 NCLOB 转 str
            s_maj = b_maj.read() if hasattr(b_maj, 'read') else str(b_maj or '')
            s_min = b_min.read() if hasattr(b_min, 'read') else str(b_min or '')
            s_intro = intro.read() if hasattr(intro, 'read') else str(intro or '')

            # 获取申万行业
            sw_info = sw_map.get(secu_code, {})
            sw_ind1 = sw_info.get("sw_ind1", "未分类")
            sw_ind2 = sw_info.get("sw_ind2", "未分类")
            sw_ind3 = sw_info.get("sw_ind3", "未分类")
            sw_full = f"{sw_ind1} - {sw_ind2} - {sw_ind3}" if sw_ind1 != "未分类" else "未分类"

            item = {
                "inner_code": inner_code,
                "company_code": comp_code,
                "secu_code": secu_code,
                "secu_abbr": secu_abbr,
                "sw_ind1": sw_ind1,
                "sw_ind2": sw_ind2,
                "sw_ind3": sw_ind3,
                "industry_sw": sw_full,
                "business_major": s_maj.strip(),
                "business_minor": s_min.strip(),
                "brief_intro": s_intro.strip(),
                "update_time": xgrq or ""
            }
            records.append(item)
            total_fetched += 1

            if limit > 0 and total_fetched >= limit:
                break
        if limit > 0 and total_fetched >= limit:
            break

    conn.close()
    elapsed = time.time() - start_t
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 读取完成！共抽取 {len(records)} 家 A 股公司，耗时 {elapsed:.2f} 秒。")

    # 保存 JSON
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    file_size_mb = os.path.getsize(output_file) / (1024 * 1024)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 原始大文本档案已保存至: {output_file} (文件大小: {file_size_mb:.2f} MB)")

    return records


def main():
    parser = argparse.ArgumentParser(description="抽取全市场 A 股主营业务与简介大文本档案并合并行业")
    parser.add_argument("--limit", type=int, default=0, help="限制抽取数量（0 表示全量抽取）")
    args = parser.parse_args()

    fetch_stock_archives(limit=args.limit)


if __name__ == "__main__":
    main()
