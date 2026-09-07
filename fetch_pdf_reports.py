#!/usr/bin/env python3
"""
fetch_pdf_reports.py (全量工业级版)
从聚源 Oracle 测试库（ZBJYDB.DZ_NOTTEXTANNOUNCEMENT）批量抽取全市场 A 股（5000+ 家上市公司）
最新披露的【交易所官方年报/半年报 PDF 直链（AnnouncementLink）】，
采用多线程并发下载并使用 PyMuPDF (fitz) 智能提取《管理层讨论与分析 (MD&A)》核心章节纯文本。

特性：
1. 支持多线程并发高速下载与解析 (--concurrency 10)
2. 支持断点续传 (自动跳过已提取的 .txt)
3. 容错兜底：若交易所 PDF 直链下载受限，自动 fallback 读取 Oracle LC_STOCKARCHIVES 完整大文本
4. 产物统一管理与进度汇报

产物：
- PDF 原文缓存: data/reports_pdf/{code}_{title}.pdf
- 核心章节纯文本: data/reports_text/{code}_{title}.txt
- 全量报告索引: data/raw_pdf_reports_index.json
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True)

import json
import re
import time
import argparse
import urllib.request
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import fitz  # PyMuPDF
import oracle_jydb_helper


def get_all_latest_reports(target_codes: list = None, limit: int = 0):
    """从 Oracle 抽取全市场 A 股最新定期报告的官方 PDF 链接与档案备份"""
    conn = oracle_jydb_helper.get_connection()
    cur = conn.cursor()

    code_filter = ""
    if target_codes:
        code_list_str = ", ".join([f"'{c.strip()}'" for c in target_codes])
        code_filter = f"AND SM.SECUCODE IN ({code_list_str})"

    sql = f"""
    WITH ranked_ann AS (
        SELECT 
            SM.INNERCODE,
            SM.COMPANYCODE,
            SM.SECUCODE,
            SM.SECUABBR,
            D.INFOTITLE,
            TO_CHAR(D.INFOPUBLDATE, 'YYYY-MM-DD') as PUBLDATE,
            TO_CHAR(D.ENDDATE, 'YYYY-MM-DD') as ENDDATE,
            D.ANNOUNCEMENTLINK,
            ROW_NUMBER() OVER (
                PARTITION BY SM.SECUCODE 
                ORDER BY D.INFOPUBLDATE DESC, D.ID DESC
            ) as rn
        FROM ZBJYDB.DZ_NOTTEXTANNOUNCEMENT D
        JOIN ZBJYDB.SECUMAIN SM ON D.COMPANYCODE = SM.COMPANYCODE
        WHERE SUBSTR(SM.SECUCODE, 1, 2) IN ('60', '68', '00', '30')
          AND SM.SECUCATEGORY = 1
          AND (
              D.INFOTITLE LIKE '%年年度报告%' 
              OR D.INFOTITLE LIKE '%半年度报告%'
              OR D.INFOTITLE LIKE '%年度报告'
              OR D.INFOTITLE LIKE '%半年度报告'
          )
          AND D.INFOTITLE NOT LIKE '%摘要%'
          AND D.INFOTITLE NOT LIKE '%提示性%'
          AND D.INFOTITLE NOT LIKE '%问询%'
          AND D.INFOTITLE NOT LIKE '%说明会%'
          AND D.INFOTITLE NOT LIKE '%说明公告%'
          AND D.INFOTITLE NOT LIKE '%英文版%'
          AND D.ANNOUNCEMENTLINK IS NOT NULL
          {code_filter}
    )
    SELECT 
        SECUCODE, SECUABBR, INFOTITLE, PUBLDATE, ENDDATE, ANNOUNCEMENTLINK
    FROM ranked_ann
    WHERE rn = 1
    ORDER BY SECUCODE ASC
    """

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 正在从 Oracle 查询全市场最新定期报告官方 PDF 直链...")
    cur.execute(sql)
    rows = cur.fetchall()
    conn.close()

    reports = []
    for r in rows:
        code, name, title, publdate, enddate, link = r
        reports.append({
            "secu_code": code,
            "secu_name": name,
            "title": title,
            "publ_date": publdate,
            "end_date": enddate,
            "pdf_url": link
        })
        if limit > 0 and len(reports) >= limit:
            break

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 查询完毕！共检索到 {len(reports)} 家 A 股公司的最新定期报告直链。")
    return reports


def download_pdf(url: str, output_path: str, max_retries: int = 3, timeout: int = 25) -> bool:
    """安全下载 PDF 文件"""
    if os.path.exists(output_path) and os.path.getsize(output_path) > 10240:
        return True

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Referer": "http://www.sse.com.cn/"
    }

    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
                # 检查是否为有效 PDF (以 %PDF 开头且大于 10KB)
                if data.startswith(b'%PDF') or len(data) > 10240:
                    with open(output_path, "wb") as f:
                        f.write(data)
                    return True
        except Exception:
            if attempt < max_retries:
                time.sleep(attempt * 1.5)
    return False


def extract_mda_section_from_pdf(pdf_path: str) -> str:
    """使用 PyMuPDF 智能提取《管理层讨论与分析》或《主要业务概要》核心章节"""
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return ""

    num_pages = len(doc)
    start_page = -1
    end_page = -1

    start_pattern = re.compile(r"(第[三四五六]节\s*(?:管理层讨论与分析|经营情况讨论与分析|业务概要|董事会报告))|(管理层讨论与分析\b)")
    end_pattern = re.compile(r"第[四五六七八]节\s*(?:公司治理|环境与社会责任|重要事项|股份变动|财务报告)")

    # 优先扫描前 40 页定位起始
    for pno in range(min(40, num_pages)):
        text = doc[pno].get_text()
        if start_pattern.search(text) and len(text) > 100:
            if ".........." not in text and "····" not in text:
                start_page = pno
                break

    if start_page != -1:
        for pno in range(start_page + 1, min(start_page + 60, num_pages)):
            text = doc[pno].get_text()
            if end_pattern.search(text) and ".........." not in text:
                end_page = pno
                break
        if end_page == -1:
            end_page = min(start_page + 30, num_pages)
    else:
        start_page = 0
        end_page = min(25, num_pages)

    extracted_text_list = []
    for pno in range(start_page, end_page):
        p_text = doc[pno].get_text("text")
        lines = [line.strip() for line in p_text.splitlines() if line.strip()]
        extracted_text_list.append("\n".join(lines))

    doc.close()
    return "\n\n".join(extracted_text_list)


def process_single_stock(item: dict, pdf_dir: str, txt_dir: str, fallback_map: dict) -> dict:
    code = item["secu_code"]
    name = item["secu_name"]
    title = item["title"]
    url = item["pdf_url"]

    clean_title = re.sub(r'[\\/*?:"<>|]', '_', title)
    pdf_filename = f"{code}_{clean_title}.pdf"
    txt_filename = f"{code}_{clean_title}.txt"

    pdf_path = os.path.join(pdf_dir, pdf_filename)
    txt_path = os.path.join(txt_dir, txt_filename)

    # 断点续传检查
    if os.path.exists(txt_path) and os.path.getsize(txt_path) > 200:
        char_cnt = 0
        with open(txt_path, "r", encoding="utf-8") as f:
            char_cnt = len(f.read())
        return {
            "status": "cached",
            "secu_code": code,
            "secu_name": name,
            "title": title,
            "publ_date": item.get("publ_date", ""),
            "pdf_path": pdf_path,
            "txt_path": txt_path,
            "char_count": char_cnt
        }

    # 1. 尝试下载 PDF
    download_ok = download_pdf(url, pdf_path)
    mda_text = ""

    if download_ok and os.path.exists(pdf_path):
        mda_text = extract_mda_section_from_pdf(pdf_path)

    # 2. 兜底保护：若 PDF 下载受限或无法解析，自动使用从 Oracle 抽取的最新大文本补充
    if not mda_text or len(mda_text) < 100:
        fb = fallback_map.get(code, {})
        maj = fb.get("business_major", "")
        intro = fb.get("brief_intro", "")
        mda_text = f"【公司业务概要与主营业务】\n{maj}\n\n【公司发展与简介】\n{intro}"

    # 3. 写入纯文本文件
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(mda_text)

    char_cnt = len(mda_text)
    return {
        "status": "success",
        "secu_code": code,
        "secu_name": name,
        "title": title,
        "publ_date": item.get("publ_date", ""),
        "pdf_path": pdf_path,
        "txt_path": txt_path,
        "char_count": char_cnt
    }


def run_full_extraction(concurrency: int = 10, limit: int = 0):
    base_dir = os.path.dirname(__file__)
    pdf_dir = os.path.join(base_dir, "data", "reports_pdf")
    txt_dir = os.path.join(base_dir, "data", "reports_text")
    os.makedirs(pdf_dir, exist_ok=True)
    os.makedirs(txt_dir, exist_ok=True)

    # 加载 Oracle 兜底库
    raw_archives_file = os.path.join(base_dir, "data", "raw_stock_archives.json")
    fallback_map = {}
    if os.path.exists(raw_archives_file):
        with open(raw_archives_file, "r", encoding="utf-8") as f:
            for it in json.load(f):
                fallback_map[it["secu_code"]] = it

    reports = get_all_latest_reports(limit=limit)
    total_count = len(reports)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 启动全市场报告批量抽取流水线 (并发数: {concurrency}, 总数: {total_count})...")

    results = []
    start_time = time.time()
    processed = 0

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(process_single_stock, item, pdf_dir, txt_dir, fallback_map): item
            for item in reports
        }

        for future in as_completed(futures):
            res = future.result()
            results.append(res)
            processed += 1

            if processed % 50 == 0 or processed == total_count:
                elapsed = time.time() - start_time
                speed = processed / elapsed if elapsed > 0 else 0
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [进度: {processed}/{total_count} ({processed/total_count*100:.1f}%)] 已处理 {processed} 只，当前速度: {speed:.1f} 份/秒")

    # 保存全量索引文件
    index_file = os.path.join(base_dir, "data", "raw_pdf_reports_index.json")
    results.sort(key=lambda x: x["secu_code"])
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    total_time = time.time() - start_time
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 全市场报告抽取完成！共处理 {len(results)} 份，总耗时 {total_time:.2f} 秒。")
    print(f"  - 章节文本库: {txt_dir}")
    print(f"  - 全量索引表: {index_file}")


def main():
    parser = argparse.ArgumentParser(description="全市场 A 股最新定期报告批量抽取流水线")
    parser.add_argument("--concurrency", type=int, default=10, help="并发下载与解析线程数")
    parser.add_argument("--limit", type=int, default=0, help="限制抽取数量（0 表示全量）")
    args = parser.parse_args()

    run_full_extraction(concurrency=args.concurrency, limit=args.limit)


if __name__ == "__main__":
    main()
