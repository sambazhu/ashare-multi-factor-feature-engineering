#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${DIR}"

# 加载环境变量
if [ -f "${DIR}/agent/.env" ]; then
    set -a; . "${DIR}/agent/.env"; set +a
elif [ -f "${DIR}/../.env" ]; then
    set -a; . "${DIR}/../.env"; set +a
fi

export API_AUTH_KEY="${API_AUTH_KEY:-${VIBE_API_KEY:-vibe123456}}"
PORT="${VIBE_PORT:-8899}"
HOST="${VIBE_HOST_BIND:-0.0.0.0}"

# 自动探测 Python 虚拟环境与可执行程序
if [ -f "${DIR}/.venv-linux/bin/vibe-trading" ]; then
    VIBE_BIN="${DIR}/.venv-linux/bin/vibe-trading"
elif [ -f "${DIR}/.venv/bin/vibe-trading" ]; then
    VIBE_BIN="${DIR}/.venv/bin/vibe-trading"
elif which vibe-trading >/dev/null 2>&1; then
    VIBE_BIN="$(which vibe-trading)"
else
    VIBE_BIN="vibe-trading"
fi

pkill -9 -f "vibe-trading serve" 2>/dev/null || true
sleep 1
nohup "${VIBE_BIN}" serve --host "${HOST}" --port "${PORT}" > server.log 2>&1 < /dev/null &
echo "Vibe-Trading server started on port ${PORT} (bind ${HOST})!"
