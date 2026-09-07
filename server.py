#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ashare 看板极速静态 Web 服务器 (In-Memory Gzip + Threading + Vibe-Trading Proxy)
- 启动时自动将 meta.json / dates_index.json / 最近 15 日切片预加载至 RAM
- 后台异步预热全量 200 个历史交易日 JSON 数据至 RAM 缓存
- 具备强协商缓存 (ETag)、Gzip 预压缩零开销下发
- 内置 Vibe-Trading 量化投研接口同源反向代理 (/api/ashare/*, /chat)
"""

import os
import sys
import time
import gzip
import mimetypes
import threading
import json
import urllib.request
import socketserver
from http.server import HTTPServer, SimpleHTTPRequestHandler


def load_env_file():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() not in os.environ:
                        val = v.strip()
                        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                            val = val[1:-1]
                        os.environ[k.strip()] = val

load_env_file()

PORT = int(os.getenv("ASHARE_PORT", "8089"))
VIBE_HOST = os.getenv("VIBE_HOST", "http://127.0.0.1:8899").rstrip("/")
VIBE_API_KEY = os.getenv("VIBE_API_KEY", "vibe123456")

WEB_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE = {}
CACHE_LOCK = threading.Lock()

# 符号链接动态监听
LATEST_SYMLINK = os.path.join(WEB_DIR, "data", "data_latest.json")
LATEST_COMPACT_SYMLINK = os.path.join(WEB_DIR, "data", "data_latest.compact.json")
CURRENT_SYMLINK_TARGET = None
CURRENT_COMPACT_SYMLINK_TARGET = None

def get_mime_type(file_path):
    mime, _ = mimetypes.guess_type(file_path)
    if mime:
        return mime
    if file_path.endswith(".json"):
        return "application/json"
    if file_path.endswith(".js"):
        return "application/javascript"
    if file_path.endswith(".css"):
        return "text/css"
    if file_path.endswith(".html"):
        return "text/html"
    return "application/octet-stream"

def get_cached_file(rel_path):
    """从内存缓存获取预压缩文件数据，若未命中则实时读取并缓存"""
    global CURRENT_SYMLINK_TARGET
    full_path = os.path.join(WEB_DIR, rel_path)

    # 针对 data_latest.json 与 data_latest.compact.json 符号链接动态感知
    if os.path.abspath(full_path) == os.path.abspath(LATEST_SYMLINK):
        try:
            if os.path.islink(LATEST_SYMLINK):
                target = os.readlink(LATEST_SYMLINK)
                if target != CURRENT_SYMLINK_TARGET:
                    with CACHE_LOCK:
                        for k in list(CACHE.keys()):
                            if k.endswith("data_latest.json"):
                                del CACHE[k]
                        CURRENT_SYMLINK_TARGET = target
        except Exception:
            pass

    if os.path.abspath(full_path) == os.path.abspath(LATEST_COMPACT_SYMLINK):
        try:
            if os.path.islink(LATEST_COMPACT_SYMLINK):
                target = os.readlink(LATEST_COMPACT_SYMLINK)
                if target != CURRENT_COMPACT_SYMLINK_TARGET:
                    with CACHE_LOCK:
                        for k in list(CACHE.keys()):
                            if k.endswith("data_latest.compact.json"):
                                del CACHE[k]
                        CURRENT_COMPACT_SYMLINK_TARGET = target
        except Exception:
            pass

    if not os.path.exists(full_path) or os.path.isdir(full_path):
        return None

    try:
        mtime = os.path.getmtime(full_path)
    except OSError:
        return None

    with CACHE_LOCK:
        entry = CACHE.get(full_path)
        if entry and entry["mtime"] == mtime:
            return entry

    # 读取并压缩至内存
    try:
        with open(full_path, "rb") as f:
            raw_data = f.read()
        
        mime = get_mime_type(full_path)
        is_compressible = (
            mime.startswith("text/") or 
            mime in ("application/json", "application/javascript", "image/svg+xml") or
            full_path.endswith((".json", ".js", ".html", ".css", ".svg", ".md"))
        )
        
        if is_compressible and len(raw_data) > 128:
            gz_data = gzip.compress(raw_data, compresslevel=6)
        else:
            gz_data = None

        etag = f'"{int(mtime)}-{len(raw_data)}"'
        new_entry = {
            "raw": raw_data,
            "gzip": gz_data,
            "mtime": mtime,
            "etag": etag,
            "mime": mime
        }

        with CACHE_LOCK:
            CACHE[full_path] = new_entry
        return new_entry
    except Exception as e:
        print(f"[ERROR] 读取并缓存文件失败 {full_path}: {e}")
        return None

class InMemoryGzipHTTPRequestHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def do_OPTIONS(self):
        """统一处理 CORS 预检请求"""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_POST(self):
        """反向代理 Vibe-Trading 量化投研与大模型接口 (同源转发)"""
        path = self.path.split("?")[0]
        if path.startswith("/api/") or path.startswith("/chat"):
            try:
                content_len = int(self.headers.get("Content-Length", 0))
                post_body = self.rfile.read(content_len) if content_len > 0 else b""
                target_url = f"{VIBE_HOST}{path}"
                
                req = urllib.request.Request(
                    target_url,
                    data=post_body,
                    headers={
                        "Content-Type": self.headers.get("Content-Type", "application/json"),
                        "Authorization": self.headers.get("Authorization", f"Bearer {VIBE_API_KEY}"),
                    },
                    method="POST"
                )
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(req, timeout=180) as resp:
                    content_type = resp.headers.get("Content-Type", "application/json; charset=utf-8")
                    disposition = resp.headers.get("Content-Disposition")

                    if "text/event-stream" in content_type:
                        self.send_response(resp.status)
                        self.send_header("Content-Type", content_type)
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Connection", "keep-alive")
                        self.send_header("X-Accel-Buffering", "no")
                        self.end_headers()

                        try:
                            while True:
                                chunk = resp.read(128)
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                                self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                        return
                    else:
                        body = resp.read()
                        self.send_response(resp.status)
                        self.send_header("Content-Type", content_type)
                        self.send_header("Content-Length", str(len(body)))
                        if disposition:
                            self.send_header("Content-Disposition", disposition)
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.send_header("Access-Control-Expose-Headers", "Content-Disposition")
                        self.end_headers()
                        try:
                            self.wfile.write(body)
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                        return
            except urllib.error.HTTPError as e:
                err_data = e.read()
                self.send_response(e.code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(err_data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(err_data)
                return
            except Exception as e:
                err_msg = json.dumps({"detail": f"Proxy Error: {e}"}).encode("utf-8")
                self.send_response(502)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(err_msg)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(err_msg)
                return

        self.send_error(404, f"Not Found: {path}")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            path = "/index.html"
            
        rel_path = path.lstrip("/")
        file_entry = get_cached_file(rel_path)

        if file_entry is None:
            self.send_error(404, f"File not found: {path}")
            return

        client_etag = self.headers.get("If-None-Match")
        if client_etag and client_etag == file_entry["etag"]:
            self.send_response(304)
            self.send_header("ETag", file_entry["etag"])
            self.send_header("Cache-Control", "public, max-age=60")
            self.end_headers()
            return

        accept_encoding = self.headers.get("Accept-Encoding", "")
        supports_gzip = "gzip" in accept_encoding and file_entry["gzip"] is not None

        if supports_gzip:
            payload = file_entry["gzip"]
            content_encoding = "gzip"
        else:
            payload = file_entry["raw"]
            content_encoding = None

        self.send_response(200)
        content_type = file_entry["mime"]
        if "text" in content_type or "json" in content_type or "javascript" in content_type:
            content_type += "; charset=utf-8"
            
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("ETag", file_entry["etag"])
        
        if content_encoding:
            self.send_header("Content-Encoding", content_encoding)
            
        if "data/" in rel_path or "vendor/" in rel_path:
            self.send_header("Cache-Control", "public, max-age=300")
        else:
            self.send_header("Cache-Control", "no-cache")
            
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_HEAD(self):
        path = self.path.split("?")[0]
        if path == "/":
            path = "/index.html"
            
        rel_path = path.lstrip("/")
        file_entry = get_cached_file(rel_path)

        if file_entry is None:
            self.send_error(404, f"File not found: {path}")
            return

        accept_encoding = self.headers.get("Accept-Encoding", "")
        supports_gzip = "gzip" in accept_encoding and file_entry["gzip"] is not None

        payload_len = len(file_entry["gzip"]) if supports_gzip else len(file_entry["raw"])
        content_encoding = "gzip" if supports_gzip else None

        self.send_response(200)
        content_type = file_entry["mime"]
        if "text" in content_type or "json" in content_type or "javascript" in content_type:
            content_type += "; charset=utf-8"
            
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(payload_len))
        self.send_header("ETag", file_entry["etag"])
        
        if content_encoding:
            self.send_header("Content-Encoding", content_encoding)
            
        if "data/" in rel_path or "vendor/" in rel_path:
            self.send_header("Cache-Control", "public, max-age=300")
        else:
            self.send_header("Cache-Control", "no-cache")
            
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

class ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

def preload_all_data_async():
    """后台异步将全量 200 个交易日切片完整预热至 RAM 内存"""
    def _worker():
        try:
            dates_path = os.path.join(WEB_DIR, "data", "dates_index.json")
            if not os.path.exists(dates_path):
                return
            with open(dates_path, "r", encoding="utf-8") as f:
                dates = json.load(f)
            
            t0 = time.time()
            for d in dates[15:]:
                get_cached_file(f"data/data_{d['date']}.json")
                time.sleep(0.02)
                
            mem_size = sum(len(v["raw"]) + (len(v["gzip"]) if v["gzip"] else 0) for v in CACHE.values()) / (1024*1024)
            print(f"[PRELOAD-BG] 全量 200 个交易日数据已 100% 载入 RAM 内存! 缓存文件数: {len(CACHE)}, 总内存占用: {mem_size:.2f} MB (~{mem_size/1024:.2f} GB, 耗时: {time.time()-t0:.2f}s)")
        except Exception as e:
            print(f"[WARN] 后台全量预热异常: {e}")

    threading.Thread(target=_worker, daemon=True).start()

def preload_latest_data():
    """服务器启动时优先将核心资源与最近 15 日切片预热进内存"""
    print("[PRELOAD] 正在将看板核心资源与最新 15 个交易日切片预加载至 RAM 内存...")
    t0 = time.time()
    preload_list = [
        "index.html",
        "vendor/tailwind.js",
        "vendor/lucide.js",
        "vendor/xlsx.full.min.js",
        "data/dates_index.json",
        "data/stock_200d_summary.json",
        "data/meta.json",
        "data/sw_custom_group.json",
        "data/history_matrix.json",
        "data/stock_basic_index.json",
        "data/data_latest.compact.json"
    ]
    for rel in preload_list:
        get_cached_file(rel)
        
    try:
        dates_path = os.path.join(WEB_DIR, "data", "dates_index.json")
        if os.path.exists(dates_path):
            with open(dates_path, "r", encoding="utf-8") as f:
                dates = json.load(f)
            for d in dates[:15]:
                get_cached_file(f"data/data_{d['date']}.json")
    except Exception as e:
        print(f"[WARN] 预热切片异常: {e}")
        
    cost = time.time() - t0
    cached_count = len(CACHE)
    mem_size = sum(len(v["raw"]) + (len(v["gzip"]) if v["gzip"] else 0) for v in CACHE.values()) / (1024*1024)
    print(f"[PRELOAD] 核心预加载完成! 已缓存 {cached_count} 个核心文件，占用 RAM: {mem_size:.2f} MB (耗时: {cost:.2f}s)")
    
    preload_all_data_async()

def main():
    os.chdir(WEB_DIR)
    preload_latest_data()
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), InMemoryGzipHTTPRequestHandler)
    print(f"🚀 高性能 In-Memory Gzip 服务器已启动: http://0.0.0.0:{PORT} (端口: {PORT})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()

if __name__ == "__main__":
    main()
