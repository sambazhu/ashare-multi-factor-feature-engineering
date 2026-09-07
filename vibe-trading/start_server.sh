#!/bin/bash
cd /data1/wkzq/vibe-trading

unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
export NO_PROXY=127.0.0.1,localhost,10.0.0.0/8
export no_proxy=127.0.0.1,localhost,10.0.0.0/8
export API_AUTH_KEY=vibe123456
export PATH=/data1/wkzq/vibe-trading/.venv-linux/bin:$PATH

pkill -9 -f "vibe-trading serve" 2>/dev/null || true
sleep 1
nohup /data1/wkzq/vibe-trading/.venv-linux/bin/vibe-trading serve --host 0.0.0.0 --port 8899 > /data1/wkzq/vibe-trading/server.log 2>&1 < /dev/null &
echo "Vibe-Trading server started on port 8899!"
