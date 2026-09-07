#!/usr/bin/env python3
"""
integrate_business_tags.py
将大模型提炼的 7 大核心业务要素与现有量化工程/看板体系进行整合与适配。

7 大核心要素包含：
1. 代码 (code)
2. 公司 (name)
3. 所属行业 (industry)
4. 主要业务 (major_business)
5. 主要产品 (primary_products)
6. 下游市场 (downstream_market)
7. 核心客户 (core_clients)
"""

import os
import json
import argparse


def build_web_summary_dict(input_json_path: str = None, output_json_path: str = None):
    base_dir = os.path.dirname(__file__)
    if input_json_path is None:
        pdf_json = os.path.join(base_dir, "data", "pdf_stock_business_tags.json")
        default_json = os.path.join(base_dir, "data", "stock_business_tags.json")
        input_json_path = pdf_json if os.path.exists(pdf_json) else default_json
    if output_json_path is None:
        output_json_path = os.path.join(base_dir, "data", "stock_profiles_summary.json")

    if not os.path.exists(input_json_path):
        print(f"[警告] 标签数据文件不存在: {input_json_path}，请先运行 extract_business_tags_llm.py。")
        return {}

    with open(input_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 转换成以 6 位股票代码为 key 的 7 大核心要素画像字典
    summary_dict = {}
    for item in data:
        code = item.get("secu_code", "")
        if not code:
            continue
        summary_dict[code] = {
            "code": code,
            "name": item.get("secu_name", ""),
            "industry": item.get("industry") or item.get("industry_sw", ""),
            "major_business": item.get("major_business") or item.get("one_sentence_summary", ""),
            "primary_products": item.get("primary_products", []),
            "downstream_market": item.get("downstream_market", []),
            "core_clients": item.get("core_clients", []),
            "business_model": item.get("business_model", ""),
            "update_time": item.get("update_time", "")
        }

    with open(output_json_path, "w", encoding="utf-8") as f:
        json.dump(summary_dict, f, ensure_ascii=False, indent=2)

    print(f"[OK] 7 大核心要素画像索引已构建: {output_json_path} (共 {len(summary_dict)} 只个股)")
    return summary_dict


def get_stock_profile(secu_code: str) -> dict:
    """供外部量化模块调用的查询函数"""
    base_dir = os.path.dirname(__file__)
    summary_path = os.path.join(base_dir, "data", "stock_profiles_summary.json")
    if not os.path.exists(summary_path):
        build_web_summary_dict()
    
    if os.path.exists(summary_path):
        with open(summary_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get(secu_code, {})
    return {}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成前端与量化适配信义画像字典")
    parser.add_argument("--build", action="store_true", help="构建 stock_profiles_summary.json")
    args = parser.parse_args()
    build_web_summary_dict()
