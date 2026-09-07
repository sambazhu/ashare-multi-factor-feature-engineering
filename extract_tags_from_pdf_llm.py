#!/usr/bin/env python3
"""
extract_tags_from_pdf_llm.py (高稳定性 + 黄金正文智能定位 + 股票/公司名区分版)
读取上市公司最新定期报告《管理层讨论与分析》长文本，
智能定位【报告期内公司从事的主要业务】核心段落（精炼 2500 字），
使用大模型提炼 7 大核心要素：
1. 股票代码 (secu_code)
2. 股票名称 (secu_name)
3. 公司名称 (company_name)
4. 所属行业 (industry: 申万+细分赛道)
5. 主要业务 (major_business)
6. 主要产品 (primary_products)
7. 下游市场 (downstream_market)
8. 核心客户 (core_clients)
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True)

import json
import time
import re
import argparse
import csv
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request

def load_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() not in os.environ:
                        os.environ[k.strip()] = v.strip().strip("'\"")

load_env()

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://10.99.100.129:62202/0d574b39/sync/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "Qwen3.8-27B")
DEFAULT_CONCURRENCY = int(os.getenv("LLM_CONCURRENCY", "4"))


def load_sw_map():
    map_file = os.path.join(os.path.dirname(__file__), "sw_industry_map.json")
    if os.path.exists(map_file):
        with open(map_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_names_map():
    names_file = os.path.join(os.path.dirname(__file__), "data", "stock_company_names.json")
    if os.path.exists(names_file):
        with open(names_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def locate_golden_business_text(content: str, max_chars: int = 2500) -> str:
    """智能定位年报中真正的主营业务与经营分析起始点，彻底跳过目录和释义"""
    if len(content) <= max_chars:
        return content

    patterns = [
        r'(?:一、\s*报告期内公司从事的主要业务|报告期内公司从事的主要业务|主要业务及经营模式|公司从事的主要业务|从事的主要业务)',
        r'(?:第三节\s*管理层讨论与分析|管理层讨论与分析|经营情况讨论与分析)',
        r'(?:业务概要|核心竞争力分析)'
    ]

    start_pos = 0
    for pat in patterns:
        for m in re.finditer(pat, content):
            p = m.start()
            surrounding = content[p:p+150]
            if ".........." not in surrounding and "····" not in surrounding and len(surrounding) > 30:
                start_pos = p
                break
        if start_pos > 0:
            break

    return content[start_pos : start_pos + max_chars]


SYSTEM_PROMPT = """你是一位顶级的 A 股资深行业分析师与量化研究专家。
你将阅读上市公司最新定期报告（年报/半年报）中《管理层讨论与分析》或《公司业务概要》核心章节。
请严格基于报告原文陈述进行深度提炼，严禁脱离原文主观臆造或捏造未经披露的客户与数据（严格遵循事实归因原则）。

请严格输出合法的 JSON 格式，结构定义如下：
{
  "secu_code": "股票代码",
  "secu_name": "股票名称(证券简称)",
  "company_name": "公司名称(上市公司官方全称)",
  "report_title": "报告期与公告标题",
  "industry": "所属行业(包含官方申万行业及提炼的细分赛道，如: 电子-半导体-集成电路制造 | 晶圆代工)",
  "major_business": "主要业务(50-80字精准概括公司从事的核心业务、行业地位及核心竞争壁垒)",
  "primary_products": ["主要产品或核心服务1", "主要产品2", "主要产品3", "主要产品4"],
  "downstream_market": ["主要下游应用领域1", "下游市场2", "终端应用场景3"],
  "core_clients": {
    "specific_named_clients": ["年报原文中明确点名提及的具体实体客户/知名品牌/战略合作品牌(若无则留空数组)"],
    "top5_client_info": "前五大客户销售占比与集中度特征(如: 前五名客户合计销售占比38.2%，第一大客户为某大型新能源车企；若未披露具体比例则简要说明)",
    "target_client_groups": ["核心目标客户群体类型与分销渠道(如: 电网央企、头部车企、公立医院、消费终端零售等)"]
  },
  "business_model": "详细商业与盈利模式(如: 研产销一体化、直销+经销、定制化开发、EPC总承包等)",
  "key_highlights": "报告期内核心业务亮点与重大经营进展"
}
"""

def clean_json_response(raw_text: str) -> dict:
    text = raw_text.strip()
    json_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_block:
        text = json_block.group(1).strip()
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end+1]
    return json.loads(text)


def analyze_pdf_report(item: dict, sw_map: dict, names_map: dict, max_retries: int = 3, timeout: int = 180) -> dict:
    code = item.get("secu_code", "")
    name_info = names_map.get(code, {})
    secu_abbr = name_info.get("secu_name") or item.get("secu_name", "")
    company_full_name = name_info.get("company_name") or secu_abbr
    title = item.get("title", "")
    txt_path = item.get("txt_path", "")

    if not os.path.exists(txt_path):
        return {"status": "error", "error": f"文本文件不存在: {txt_path}"}

    with open(txt_path, "r", encoding="utf-8") as f:
        full_content = f.read()

    truncated_content = locate_golden_business_text(full_content, max_chars=2500)

    sw_info = sw_map.get(code, {})
    sw_full = f"{sw_info.get('sw_ind1', '未分类')} - {sw_info.get('sw_ind2', '未分类')} - {sw_info.get('sw_ind3', '未分类')}" if sw_info.get('sw_ind1') != '未分类' else '未分类'

    user_content = f"""上市公司原始报告与基本信息如下：
- 股票代码: {code}
- 股票名称(简称): {secu_abbr}
- 公司名称(全称): {company_full_name}
- 官方申万行业分类: {sw_full}
- 最新定期报告标题: {title}

《管理层讨论与分析》核心章节摘录：
==================================================
{truncated_content}
==================================================

请根据上述报告原文，以严格事实归因原则，精准提炼该公司的核心要素（股票代码、股票名称、公司名称、所属行业、主要业务、主要产品、下游市场、核心客户），严格按 JSON 格式输出："""

    endpoint = f"{LLM_BASE_URL.rstrip('/')}/chat/completions"
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.1
    }

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}"
    }

    for attempt in range(1, max_retries + 1):
        try:
            t0 = time.time()
            req = urllib.request.Request(endpoint, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                raw_out = data["choices"][0]["message"]["content"]
                parsed_json = clean_json_response(raw_out)
                parsed_json["secu_code"] = code
                parsed_json["secu_name"] = secu_abbr
                parsed_json["company_name"] = company_full_name
                if "industry_sw" not in parsed_json:
                    parsed_json["industry_sw"] = sw_full
                parsed_json["report_title"] = title
                parsed_json["publ_date"] = item.get("publ_date", "")
                dur = time.time() - t0
                return {"status": "success", "data": parsed_json, "duration": dur}
        except Exception as e:
            if attempt < max_retries:
                time.sleep(attempt * 2)
            else:
                return {"status": "error", "secu_code": code, "secu_name": secu_abbr, "error": str(e)}


def format_core_clients_str(clients_obj) -> str:
    if isinstance(clients_obj, str):
        return clients_obj
    if isinstance(clients_obj, list):
        return "、".join(clients_obj)
    if isinstance(clients_obj, dict):
        parts = []
        specific = clients_obj.get("specific_named_clients", [])
        top5 = clients_obj.get("top5_client_info", "")
        groups = clients_obj.get("target_client_groups", [])

        if specific:
            parts.append(f"【明确合作客户】{'、'.join(specific)}")
        if top5:
            parts.append(f"【前五大客户】{top5}")
        if groups:
            parts.append(f"【核心客群】{'、'.join(groups)}")
        return "；".join(parts) if parts else "详见定期报告披露"
    return str(clients_obj)


def save_checkpoint(completed: dict, checkpoint_file: str):
    temp = checkpoint_file + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(completed, f, ensure_ascii=False, indent=2)
    os.replace(temp, checkpoint_file)


def export_pdf_tags(results_dict: dict, output_json: str, output_csv: str, names_map: dict):
    final_list = list(results_dict.values())
    final_list.sort(key=lambda x: x.get("secu_code", ""))

    for r in final_list:
        code = r.get("secu_code", "")
        if "company_name" not in r or not r["company_name"]:
            r["company_name"] = names_map.get(code, {}).get("company_name", r.get("secu_name", ""))

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(final_list, f, ensure_ascii=False, indent=2)

    fieldnames = ["股票代码", "股票名称", "公司名称", "所属行业", "主要业务", "主要产品", "下游市场", "核心客户", "商业模式", "业务亮点", "定期报告标题", "发布日期"]
    with open(output_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in final_list:
            products = r.get("primary_products", [])
            downstream = r.get("downstream_market", [])
            clients_obj = r.get("core_clients", {})
            clients_str = format_core_clients_str(clients_obj)
            
            row = {
                "股票代码": r.get("secu_code", ""),
                "股票名称": r.get("secu_name", ""),
                "公司名称": r.get("company_name", ""),
                "所属行业": r.get("industry", ""),
                "主要业务": r.get("major_business", ""),
                "主要产品": "、".join(products) if isinstance(products, list) else str(products),
                "下游市场": "、".join(downstream) if isinstance(downstream, list) else str(downstream),
                "核心客户": clients_str,
                "商业模式": r.get("business_model", ""),
                "业务亮点": r.get("key_highlights", ""),
                "定期报告标题": r.get("report_title", ""),
                "发布日期": r.get("publ_date", "")
            }
            writer.writerow(row)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 产物已导出:", flush=True)
    print(f"  - 完整 JSON: {output_json} ({len(final_list)} 条)")
    print(f"  - 区分股票名称/公司名称 CSV: {output_csv}", flush=True)


def run_pipeline(mode: str, sample_size: int = 5, target_codes: list = None, concurrency: int = DEFAULT_CONCURRENCY):
    base_dir = os.path.dirname(__file__)
    index_file = os.path.join(base_dir, "data", "raw_pdf_reports_index.json")
    if not os.path.exists(index_file):
        print(f"[错误] 报告索引文件不存在: {index_file}，请先运行 fetch_pdf_reports.py。", flush=True)
        sys.exit(1)

    with open(index_file, "r", encoding="utf-8") as f:
        all_reports = json.load(f)

    sw_map = load_sw_map()
    names_map = load_names_map()
    report_map = {item["secu_code"]: item for item in all_reports}

    if target_codes:
        tasks = [report_map[c] for c in target_codes if c in report_map]
    elif mode == "sample":
        tasks = all_reports[:sample_size]
    else:
        tasks = all_reports

    checkpoint_file = os.path.join(base_dir, "data", "pdf_stock_business_tags_checkpoint.json")
    final_json_file = os.path.join(base_dir, "data", "pdf_stock_business_tags.json")
    final_csv_file = os.path.join(base_dir, "data", "pdf_stock_business_tags.csv")

    completed = {}
    if os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, "r", encoding="utf-8") as f:
                completed = json.load(f)
            for c, v in completed.items():
                if "company_name" not in v:
                    v["company_name"] = names_map.get(c, {}).get("company_name", v.get("secu_name", ""))
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 检测到已有 Checkpoint，已包含 {len(completed)} 只股票解析结果。", flush=True)
        except Exception:
            pass

    if mode != "sample" and not target_codes:
        pending_tasks = [t for t in tasks if t["secu_code"] not in completed]
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 待处理任务: {len(pending_tasks)} 只 (已跳过 {len(tasks)-len(pending_tasks)} 只)", flush=True)
    else:
        pending_tasks = tasks

    if not pending_tasks:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 所有任务均已在 Checkpoint 中完成！直接导出产物。", flush=True)
        export_pdf_tags(completed, final_json_file, final_csv_file, names_map)
        return

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 启动智能定位高并发解析流水线 (并发数: {concurrency}, 待处理: {len(pending_tasks)})...\n", flush=True)

    start_time = time.time()
    success_count = 0
    fail_count = 0
    total_to_process = len(pending_tasks)

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {executor.submit(analyze_pdf_report, item, sw_map, names_map): item for item in pending_tasks}
        
        for future in as_completed(futures):
            item = futures[future]
            res = future.result()
            code = item["secu_code"]
            secu_abbr = names_map.get(code, {}).get("secu_name", item["secu_name"])
            full_name = names_map.get(code, {}).get("company_name", secu_abbr)
            
            if res.get("status") == "success":
                success_count += 1
                data = res["data"]
                completed[code] = data
                dur = res.get("duration", 0)
                clients_str = format_core_clients_str(data.get("core_clients"))

                cur_total = success_count + fail_count
                speed = cur_total / (time.time() - start_time) if (time.time() - start_time) > 0 else 0
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [{cur_total}/{total_to_process} ({cur_total/total_to_process*100:.1f}%)] [✓ 成功] 【{code} {secu_abbr}】({full_name}) (耗时: {dur:.2f}s, 速度: {speed:.2f} 只/秒)", flush=True)
                print(f"   ├─ 所属行业: {data.get('industry')}", flush=True)
                print(f"   ├─ 主要业务: {str(data.get('major_business'))[:70]}...", flush=True)
                print(f"   └─ 核心客户: {clients_str}\n", flush=True)
            else:
                fail_count += 1
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [✗ 失败] [{code}] {secu_abbr} -> 错误: {res.get('error')}\n", flush=True)

            if (success_count + fail_count) % 10 == 0:
                save_checkpoint(completed, checkpoint_file)
                export_pdf_tags(completed, final_json_file, final_csv_file, names_map)

    save_checkpoint(completed, checkpoint_file)
    export_pdf_tags(completed, final_json_file, final_csv_file, names_map)
    total_time = time.time() - start_time
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 深度解析流水线执行完毕！成功: {success_count}, 失败: {fail_count}, 总耗时: {total_time:.2f}s", flush=True)


def main():
    parser = argparse.ArgumentParser(description="长文本 7 大核心要素深度精准解析流水线")
    parser.add_argument("--sample", type=int, default=0, help="抽样数量（例如 --sample 5）")
    parser.add_argument("--code", type=str, default="", help="指定测试代码（例如 --code 000333,300750）")
    parser.add_argument("--all", action="store_true", help="全量运行")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="并发请求数量")

    args = parser.parse_args()

    if args.code:
        codes = [c.strip() for c in args.code.split(",") if c.strip()]
        run_pipeline(mode="code", target_codes=codes, concurrency=args.concurrency)
    elif args.sample > 0:
        run_pipeline(mode="sample", sample_size=args.sample, concurrency=args.concurrency)
    elif args.all:
        run_pipeline(mode="all", concurrency=args.concurrency)
    else:
        run_pipeline(mode="all", concurrency=args.concurrency)


if __name__ == "__main__":
    main()
