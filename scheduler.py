#!/usr/bin/env python3
"""
A 股量化特征工程系统 - 每日晚 19:00 定时执行调度守护进程
支持前台运行或使用 nohup / systemd / crontab 部署。
"""
import os
import sys
import time
import datetime
import subprocess

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON_BIN = "python3"
DAILY_SCRIPT = os.path.join(PROJECT_DIR, "daily_update.py")
TARGET_HOUR = 19
TARGET_MINUTE = 0

def run_update():
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ⏰ 触发每日晚 19:00 自动化更新任务...")
    subprocess.run([PYTHON_BIN, DAILY_SCRIPT], cwd=PROJECT_DIR)

def main():
    print("=" * 70)
    print(f"A 股特征工程定时守护进程已启动! 目标触发时间: 每日 {TARGET_HOUR:02d}:{TARGET_MINUTE:02d}")
    print("=" * 70)
    
    last_run_date = None
    
    while True:
        now = datetime.datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        
        # 仅在工作日/每天晚 19:00 触发一次
        if now.hour == TARGET_HOUR and now.minute == TARGET_MINUTE and last_run_date != today_str:
            last_run_date = today_str
            run_update()
            
        time.sleep(30)

if __name__ == "__main__":
    main()
