#!/usr/bin/env python3
"""
A 股量化特征工程系统 - 每日自动化日终全量更新与数据验证流水线
1. 步骤一: Oracle 200 交易日 9 大核心策略因子流式抽取落盘 (run_fast_200d_export.py)
2. 步骤二: 生成版本化 JSON 切片与 POSIX 零停机原子软链接发布 (convert_200d_to_json.py)
3. 步骤三: 运行自动化回归测试套件，严格校验 28 项系统数学不变式 (regression/verify_panel_stats.py)
4. 记录完整的更新与校验日志到 logs/ 目录
"""
import os
import sys
import time
import subprocess
import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
PYTHON_BIN = sys.executable

def ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)

def run_step(step_name, cmd):
    print(f"\n[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] >>> 开始执行: {step_name} ...")
    start_t = time.time()
    
    proc = subprocess.Popen(
        cmd,
        cwd=BASE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    
    for line in proc.stdout:
        print(line, end="")
        
    proc.wait()
    cost = time.time() - start_t
    
    if proc.returncode != 0:
        print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ [ERROR] {step_name} 失败! 退出码: {proc.returncode} (耗时: {cost:.2f}s)")
        return False
        
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ [SUCCESS] {step_name} 成功完成! (耗时: {cost:.2f}s)")
    return True

def main():
    ensure_log_dir()
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    print("=" * 85)
    print(f"🚀 A 股量化特征工程系统 - 每日 19:00 全量更新与回归验证任务启动 [{today_str}]")
    print("=" * 85)
    
    total_start = time.time()
    
    # 步骤 1: 导出 200 日面板数据
    step1_cmd = [PYTHON_BIN, os.path.join(BASE_DIR, "run_fast_200d_export.py")]
    if not run_step("步骤 1/3: Oracle 200 交易日 9 大核心策略因子流式抽取落盘", step1_cmd):
        print("\n[FATAL] 步骤 1 抽取失败，中止后续更新与发布!")
        sys.exit(1)
        
    # 步骤 2: 切片生成与原子软链接发布
    step2_cmd = [PYTHON_BIN, os.path.join(BASE_DIR, "convert_200d_to_json.py")]
    if not run_step("步骤 2/4: 生成版本化 JSON 切片与 POSIX 零停机原子软链接发布", step2_cmd):
        print("\n[FATAL] 步骤 2 发布失败，中止后续验证!")
        sys.exit(1)

    # 步骤 3: 自动生成紧凑列式数组切片 (.compact.json 350KB)
    step3_compact_cmd = [PYTHON_BIN, os.path.join(BASE_DIR, "export_all_compact_slices.py")]
    if not run_step("步骤 3/4: 自动生成定长紧凑列式切片 (.compact.json)", step3_compact_cmd):
        print("\n[WARN] 紧凑切片生成异常，跳过继续验证!")
        
    # 步骤 3: 运行自动化回归测试套件
    step3_cmd = [PYTHON_BIN, os.path.join(BASE_DIR, "regression", "verify_panel_stats.py")]
    if not run_step("步骤 4/4: 自动化回归测试套件 (28 项系统数学不变式校验)", step3_cmd):
        print("\n[FATAL] 步骤 3 回归测试未全部通过，请检查数据异常!")
        sys.exit(1)

    total_cost = time.time() - total_start
    print("\n" + "=" * 85)
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 🏆 每日自动化更新与数据验证全流程大获成功! 总耗时: {total_cost:.2f} 秒 ({total_cost/60:.2f} 分钟)")
    print("=" * 85)

if __name__ == "__main__":
    main()
