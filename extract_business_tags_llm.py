#!/usr/bin/env python3
"""
extract_business_tags_llm.py
使用大模型（内网 Qwen3.8-27B 或 OpenAI 兼容接口）对上市公司
【主营业务（BusinessMajor）、兼营业务（BusinessMinor）、公司简介（BriefIntroText）】
进行深度语义分析，严格对齐提取 7 大核心量化要素：
1. 代码 (secu_code)
2. 公司 (secu_name)
3. 所属行业 (industry: 官方申万行业 + 细分赛道)
4. 主要业务 (major_business)
5. 主要产品 (primary_products)
6. 下游市场 (downstream_market)
7. 核心客户 (core_clients)

支持：
1. 抽样验证模式: python extract_business_tags_llm.py --sample 5
2. 指定个股模式: python extract_business_tags_llm.py --code 000333,688981,600519
3. 全量批量模式（带断点续传+多并发）: python extract_business_tags_llm.py --all --concurrency 2
"""

import os
import sys

# 开启实时无缓冲输出
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
import urllib.error

# 自动加载 .env 环境变量
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
DEFAULT_CONCURRENCY = int(os.getenv("LLM_CONCURRENCY", "2"))

SYSTEM_PROMPT = """你是一位顶级的 A 股行业研究专家与上市公司商业模式分析师。
你的任务是根据提供的上市公司【申万行业分类】、【主营业务与经营范围】、【兼营业务】及【公司简介】，去粗取精，严谨、精准地提炼出 7 大核心要素画像。

请严格输出合法的 JSON 格式，不要包含任何额外的对话或代码块标记之外的废话。JSON 结构必须严格符合以下定义：
{
  "secu_code": "证券代码",
  "secu_name": "证券简称",
  "industry": "所属行业(包含官方申万行业及提炼的细分赛道，如: 电子-半导体-集成电路制造 | 先进芯片晶圆代工)",
  "major_business": "主要业务(50-80字精准业务概括与核心业务定位)",
  "primary_products": ["主要产品或核心服务1", "主要产品或核心服务2", "主要产品或核心服务3"],
  "downstream_market": ["主要下游市场/应用场景1", "主要下游市场/应用场景2", "主要下游市场/应用场景3"],
  "core_clients": ["代表性头部客户/知名合作品牌，或主要核心客户群体类型(如: 特斯拉/头部新能源车企/电网央企/全球芯片设计厂商/零售消费群体)"],
  "business_model": "商业与盈利模式(如: 研产销一体化 / 核心零部件OEM与定制 / 软硬件一体化解决方案 / 品牌专卖与经销)"
}
"""

def clean_json_response(raw_text: str) -> dict:
    """清洗大模型输出，提取合法的 JSON 对象"""
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


def call_llm_single(item: dict, max_retries: int = 3, timeout: int = 60) -> dict:
    """调用大模型解析单只股票"""
    code = item.get("secu_code", "")
    name = item.get("secu_abbr", "")
    sw_ind = item.get("industry_sw", "未分类")
    b_maj = (item.get("business_major") or "")[:1000]
    b_min = (item.get("business_minor") or "")[:400]
    intro = (item.get("brief_intro") or "")[:1000]

    user_content = f"""上市公司原始档案信息如下：
- 证券代码: {code}
- 证券简称: {name}
- 官方申万行业分类: {sw_ind}
- 主营业务与经营范围:
{b_maj or '(无)'}
- 兼营业务:
{b_min or '(无)'}
- 公司简介与沿革:
{intro or '(无)'}

请严格按 JSON 格式提炼该公司的 7 大核心要素（代码、公司、所属行业、主要业务、主要产品、下游市场、核心客户）："""

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

    print(f"[{datetime.now().strftime('%H:%M:%S')}] [开始请求] [{code}] {name} (所属申万行业: {sw_ind})...", flush=True)

    for attempt in range(1, max_retries + 1):
        try:
            t0 = time.time()
            req = urllib.request.Request(endpoint, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content = data["choices"][0]["message"]["content"]
                parsed_json = clean_json_response(content)
                parsed_json["secu_code"] = code
                parsed_json["secu_name"] = name
                if "industry_sw" not in parsed_json:
                    parsed_json["industry_sw"] = sw_ind
                parsed_json["update_time"] = item.get("update_time", "")
                dur = time.time() - t0
                return {"status": "success", "data": parsed_json, "raw": content, "duration": dur}
        except Exception as e:
            if attempt < max_retries:
                time.sleep(attempt * 1.5)
            else:
                return {
                    "status": "error",
                    "secu_code": code,
                    "secu_name": name,
                    "error": str(e)
                }


def save_checkpoint(results: dict, checkpoint_file: str):
    """原子写入保存 Checkpoint"""
    temp_file = checkpoint_file + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    os.replace(temp_file, checkpoint_file)


def export_final_outputs(results: dict, output_json_path: str, output_csv_path: str):
    """导出最终的 JSON 和 7 大核心要素扁平化 CSV"""
    final_list = list(results.values())
    final_list.sort(key=lambda x: x.get("secu_code", ""))

    # 1. 保存完整 JSON
    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(final_list, f, ensure_ascii=False, indent=2)

    # 2. 保存 7 大核心要素扁平化 CSV (带 UTF-8 BOM 方便 Excel/量化查阅)
    fieldnames = [
        "代码", "公司", "所属行业", "主要业务", "主要产品", "下游市场", "核心客户", "商业模式", "更新时间"
    ]
    with open(output_csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in final_list:
            products = r.get("primary_products", [])
            downstream = r.get("downstream_market", [])
            clients = r.get("core_clients", [])
            
            row = {
                "代码": r.get("secu_code", ""),
                "公司": r.get("secu_name", ""),
                "所属行业": r.get("industry") or r.get("industry_sw", ""),
                "主要业务": r.get("major_business") or r.get("one_sentence_summary", ""),
                "主要产品": "、".join(products) if isinstance(products, list) else str(products),
                "下游市场": "、".join(downstream) if isinstance(downstream, list) else str(downstream),
                "核心客户": "、".join(clients) if isinstance(clients, list) else str(clients),
                "商业模式": r.get("business_model", ""),
                "更新时间": r.get("update_time", "")
            }
            writer.writerow(row)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 7 大核心要素结果已成功导出:", flush=True)
    print(f"  - 完整 JSON: {output_json_path} ({len(final_list)} 条)", flush=True)
    print(f"  - 7 列核心要素 CSV: {output_csv_path}", flush=True)


def run_pipeline(mode: str, sample_size: int = 5, target_codes: list = None, concurrency: int = DEFAULT_CONCURRENCY):
    raw_file = os.path.join(os.path.dirname(__file__), "data", "raw_stock_archives.json")
    if not os.path.exists(raw_file):
        print(f"[错误] 原始数据文件不存在: {raw_file}，请先运行 fetch_stock_archives.py 抽取数据。", flush=True)
        sys.exit(1)

    with open(raw_file, "r", encoding="utf-8") as f:
        all_stocks = json.load(f)

    # 建立代码映射
    stocks_map = {item["secu_code"]: item for item in all_stocks}

    # 筛选任务列表
    if target_codes:
        tasks = [stocks_map[c] for c in target_codes if c in stocks_map]
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 指定测试个股: {len(tasks)} 只 ({target_codes})", flush=True)
    elif mode == "sample":
        # 精选 5 只跨行业代表性龙头
        representative = ["000333", "688981", "600519", "300750", "601398", "002594", "600036", "688012", "002475", "600276"]
        sample_pool = [stocks_map[c] for c in representative if c in stocks_map]
        if len(sample_pool) < sample_size:
            extra = [item for item in all_stocks if item["secu_code"] not in representative][:sample_size - len(sample_pool)]
            sample_pool.extend(extra)
        tasks = sample_pool[:sample_size]
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 抽样验证模式: 精选 {len(tasks)} 只典型上市公司", flush=True)
    else:
        tasks = all_stocks
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 全量批量运行模式: 共 {len(tasks)} 只 A 股公司", flush=True)

    checkpoint_file = os.path.join(os.path.dirname(__file__), "data", "stock_business_tags_checkpoint.json")
    final_json_file = os.path.join(os.path.dirname(__file__), "data", "stock_business_tags.json")
    final_csv_file = os.path.join(os.path.dirname(__file__), "data", "stock_business_tags.csv")

    completed = {}
    if os.path.exists(checkpoint_file):
        try:
            with open(checkpoint_file, "r", encoding="utf-8") as f:
                completed = json.load(f)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 检测到已有 Checkpoint，已包含 {len(completed)} 只股票解析结果。", flush=True)
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 加载 Checkpoint 失败，重新创建: {e}", flush=True)

    # 过滤待处理项（若是指定抽样或测试代码，则强制重新解析以验证最新 7 大要素）
    if mode != "sample" and not target_codes:
        pending_tasks = [t for t in tasks if t["secu_code"] not in completed]
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 待处理股票数量: {len(pending_tasks)} 只 (已跳过 {len(tasks) - len(pending_tasks)} 只)", flush=True)
    else:
        pending_tasks = tasks

    if not pending_tasks:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 所有任务均已在 Checkpoint 中完成！直接导出产物。", flush=True)
        export_final_outputs(completed, final_json_file, final_csv_file)
        return

    print(f"[{datetime.now().strftime('%H:%M:%S')}] 启动 7 大核心要素大模型解析流水线 (并发数: {concurrency}, 模型: {LLM_MODEL})...\n", flush=True)
    start_time = time.time()
    success_count = 0
    fail_count = 0

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {executor.submit(call_llm_single, item): item for item in pending_tasks}
        
        for future in as_completed(futures):
            item = futures[future]
            res = future.result()
            code = item["secu_code"]
            name = item["secu_abbr"]
            
            if res.get("status") == "success":
                success_count += 1
                data = res["data"]
                completed[code] = data
                dur = res.get("duration", 0)
                
                products = data.get("primary_products", [])
                downstream = data.get("downstream_market", [])
                clients = data.get("core_clients", [])
                
                # 打印 7 大要素核查结果
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [✓ 成功] 【{code} {name}】 (耗时: {dur:.2f}s)", flush=True)
                print(f"   ① 代码: {code}", flush=True)
                print(f"   ② 公司: {name}", flush=True)
                print(f"   ③ 所属行业: {data.get('industry')}", flush=True)
                print(f"   ④ 主要业务: {data.get('major_business')}", flush=True)
                print(f"   ⑤ 主要产品: {'、'.join(products) if isinstance(products, list) else products}", flush=True)
                print(f"   ⑥ 下游市场: {'、'.join(downstream) if isinstance(downstream, list) else downstream}", flush=True)
                print(f"   ⑦ 核心客户: {'、'.join(clients) if isinstance(clients, list) else clients}", flush=True)
                print(f"   └─ 商业模式: {data.get('business_model')}\n", flush=True)
            else:
                fail_count += 1
                print(f"[{datetime.now().strftime('%H:%M:%S')}] [✗ 失败] [{code}] {name} -> 错误: {res.get('error')}\n", flush=True)

            if (success_count + fail_count) % 10 == 0:
                save_checkpoint(completed, checkpoint_file)

    save_checkpoint(completed, checkpoint_file)
    export_final_outputs(completed, final_json_file, final_csv_file)

    total_time = time.time() - start_time
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 流水线完成！成功: {success_count}, 失败: {fail_count}, 总耗时: {total_time:.2f}s", flush=True)


def main():
    parser = argparse.ArgumentParser(description="上市公司 7 大核心要素大模型提炼流水线")
    parser.add_argument("--sample", type=int, default=0, help="抽样验证模式，指定测试股票数量（例如 --sample 5）")
    parser.add_argument("--code", type=str, default="", help="指定个股测试，支持逗号分隔（例如 --code 000333,688981）")
    parser.add_argument("--all", action="store_true", help="全量运行模式")
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
        # 默认抽样 5 只
        run_pipeline(mode="sample", sample_size=5, concurrency=args.concurrency)


if __name__ == "__main__":
    main()
