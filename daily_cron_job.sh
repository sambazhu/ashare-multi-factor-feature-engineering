#!/bin/bash
# ============================================================
# A 股量化特征工程系统 - 每日晚 19:00 定时执行与验证包装脚本
# ============================================================

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="$(which python3 || echo "python3")"
LOG_DIR="${PROJECT_DIR}/logs"

mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/daily_cron_$(date +\%Y\%m\%d_\%H\%M\%S).log"

echo "============================================================" >> "${LOG_FILE}"
echo "Cron Job Triggered at $(date '+%Y-%m-%d %H:%M:%S')" >> "${LOG_FILE}"
echo "============================================================" >> "${LOG_FILE}"

cd "${PROJECT_DIR}" || exit 1

# ---- 1. 加载 Oracle Instant Client 环境变量 ----
if [ -d "/data1/wkzq/oracle/instantclient" ]; then
    export LD_LIBRARY_PATH="/data1/wkzq/oracle/instantclient:${LD_LIBRARY_PATH}"
fi

# ---- 2. 加载聚源连接凭据 ----
if [ -f "${PROJECT_DIR}/.env" ]; then
    set -a; . "${PROJECT_DIR}/.env"; set +a
fi

# ---- 3. 磁盘预检: 剩余不足 3GB 时自动清理历史版本目录 (保留最近 2 代 + 当前线上版本) ----
FREE_MB=$(df -m "${PROJECT_DIR}" | awk 'NR==2 {print $4}')
if [ -n "${FREE_MB}" ] && [ "${FREE_MB}" -lt 3000 ]; then
    echo "[PRE-FLIGHT] 磁盘剩余 ${FREE_MB}MB 不足 3GB, 自动清理历史版本..." >> "${LOG_FILE}"
    CURRENT_VER=$(basename "$(readlink "${PROJECT_DIR}/data" 2>/dev/null)")
    ALL_VERS=($(ls -1d "${PROJECT_DIR}/data_versions"/ver_* 2>/dev/null | sort))
    NUM_VERS=${#ALL_VERS[@]}
    if [ "${NUM_VERS}" -gt 2 ]; then
        NUM_TO_REMOVE=$((NUM_VERS - 2))
        for ((i=0; i<NUM_TO_REMOVE; i++)); do
            d="${ALL_VERS[$i]}"
            [ "$(basename "${d}")" = "${CURRENT_VER}" ] && continue
            rm -rf "${d}"
            echo "[PRE-FLIGHT] 已删除 ${d}" >> "${LOG_FILE}"
        done
    fi
fi

# ---- 4. 执行更新与 28 项回归验证流水线 ----
"${PYTHON_BIN}" "${PROJECT_DIR}/daily_update.py" >> "${LOG_FILE}" 2>&1
EXIT_CODE=$?

# ---- 5. 自动同步数据至 125 演示与 AI 服务器 (121.14.52.125) ----
if [ ${EXIT_CODE} -eq 0 ]; then
    echo "[SYNC-125] 开始向 125 展示服务器同步最新数据切片与索引..." >> "${LOG_FILE}"
    rsync -avz --delete -e "ssh -o StrictHostKeyChecking=no" "${PROJECT_DIR}/data/" wkzjapp@121.14.52.125:/home/wkzjapp/ashare-multi-factor-feature-engineering/data/ >> "${LOG_FILE}" 2>&1
    SYNC_STATUS=$?
    if [ ${SYNC_STATUS} -eq 0 ]; then
        echo "[SYNC-125] ✅ 125 服务器数据同步大获成功!" >> "${LOG_FILE}"
        ssh -o StrictHostKeyChecking=no wkzjapp@121.14.52.125 "touch /home/wkzjapp/ashare-multi-factor-feature-engineering/data/data_latest.json" 2>/dev/null || true
    else
        echo "[SYNC-125] ⚠️ 125 服务器数据同步出现警告 (退出码: ${SYNC_STATUS})" >> "${LOG_FILE}"
    fi
fi

echo "Cron Job Finished with Exit Code ${EXIT_CODE} at $(date '+%Y-%m-%d %H:%M:%S')" >> "${LOG_FILE}"

# 保留最近 30 天日志，自动清理过期日志
find "${LOG_DIR}" -type f -name "daily_cron_*.log" -mtime +30 -delete 2>/dev/null || true

exit ${EXIT_CODE}
