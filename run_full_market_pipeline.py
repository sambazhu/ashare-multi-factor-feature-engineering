#!/usr/bin/env python3
"""
run_full_market_pipeline.py
全市场 A 股（5300+ 家上市公司）年报/半年报《第三节 管理层讨论与分析》抽取
与大模型 7 大核心要素深度精准提炼一站式全量流水线。

全流程：
1. [阶段一] 批量抓取最新定期报告官方 PDF 直链，并发下载并提取万字级 MD&A 纯文本 -> data/reports_text/
2. [阶段二] 启动大模型长文档语义解析流水线，提取 7 大核心要素（含三层精准核心客户与申万行业） -> data/pdf_stock_business_tags.csv / .json
3. [阶段三] 构建前端看板秒级快查索引 -> data/stock_profiles_summary.json
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True)

import time
import subprocess
from datetime import datetime

import fetch_pdf_reports
import extract_tags_from_pdf_llm
import integrate_business_tags


def main():
    print(f"==================================================", flush=True)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 启动全市场 A 股定期报告 7 大核心要素全量流水线", flush=True)
    print(f"==================================================\n", flush=True)

    start_total = time.time()

    # 1. 阶段一：全量报告章节提取
    print(f"[{datetime.now().strftime('%H:%M:%S')}] >>> 正在执行【阶段一】：全市场最新年报/半年报《管理层讨论与分析》核心章节抽取...", flush=True)
    t1 = time.time()
    fetch_pdf_reports.run_full_extraction(concurrency=10)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 【阶段一】执行完毕！耗时: {time.time()-t1:.2f}s\n", flush=True)

    # 2. 阶段二：大模型 7 大核心要素深度提取
    print(f"[{datetime.now().strftime('%H:%M:%S')}] >>> 正在执行【阶段二】：大模型 7 大核心要素深度提炼 (含精准核心客户与申万行业)...", flush=True)
    t2 = time.time()
    extract_tags_from_pdf_llm.run_pipeline(mode="all", concurrency=3)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 【阶段二】执行完毕！耗时: {time.time()-t2:.2f}s\n", flush=True)

    # 3. 阶段三：构建看板快查索引
    print(f"[{datetime.now().strftime('%H:%M:%S')}] >>> 正在执行【阶段三】：构建前端 Web 看板秒级索引与量化接口...", flush=True)
    integrate_business_tags.build_web_summary_dict()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 【阶段三】构建完毕！\n", flush=True)

    total_cost = time.time() - start_total
    print(f"==================================================", flush=True)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎉 全市场全量流水线全部圆满完成！总耗时: {total_cost:.2f}s", flush=True)
    print(f"==================================================", flush=True)


if __name__ == "__main__":
    main()
