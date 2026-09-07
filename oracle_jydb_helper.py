#!/usr/bin/env python3
"""
聚源同步数据测试库 - Oracle 连接助手
支持 Thick 模式连接 Oracle 11g+ 数据库

配置说明：
- 数据库连接凭据通过环境变量或当前目录下的 .env 文件提供。
- 请参考 .env.example 创建并配置 .env 文件，切勿将明文密码提交至代码仓库。
"""
import os
import sys
import oracledb

def load_env_file():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if k.strip() not in os.environ:
                        os.environ[k.strip()] = v.strip().strip("'\"")

load_env_file()

def _resolve_ic_dir():
    ic = os.getenv("IC_DIR")
    if ic and os.path.exists(ic):
        return ic
    for p in os.getenv("LD_LIBRARY_PATH", "").split(":"):
        p = p.strip()
        if p and os.path.exists(p) and (os.path.exists(os.path.join(p, "libclntsh.so")) or "instantclient" in p):
            return p
    for p in ["/data1/wkzq/oracle/instantclient", "/opt/oracle/instantclient"]:
        if os.path.exists(p):
            return p
    return None

IC_DIR = _resolve_ic_dir()

HOST = os.getenv("JYDB_HOST")
PORT = int(os.getenv("JYDB_PORT", "1521"))
SERVICE = os.getenv("JYDB_SERVICE", "JYDBTEST")
USER = os.getenv("JYDB_USER")
PASSWORD = os.getenv("JYDB_PASSWORD")


def get_connection():
    if not HOST or not USER or not PASSWORD:
        raise RuntimeError(
            "未检测到完整的 Oracle 数据库连接配置 (JYDB_HOST, JYDB_USER, JYDB_PASSWORD)。\n"
            "请复制 .env.example 为 .env 并填入实际连接凭据，或在当前环境中配置相应环境变量。"
        )

    if IC_DIR and os.path.exists(IC_DIR):
        try:
            oracledb.init_oracle_client(lib_dir=IC_DIR)
        except Exception:
            # 客户端可能已被初始化，忽略重复初始化异常
            pass

    return oracledb.connect(
        user=USER, password=PASSWORD,
        host=HOST, port=PORT, service_name=SERVICE,
    )


def main():
    conn = get_connection()
    print(f"[OK] connected to {SERVICE} as {USER}")
    cur = conn.cursor()
    cur.execute("SELECT * FROM v$version WHERE ROWNUM <= 1")
    print("DB:", cur.fetchone()[0])
    cur.execute("SELECT COUNT(*) FROM all_tables WHERE owner='ZBJYDB'")
    print("zbjydb 表数量:", cur.fetchone()[0])
    conn.close()


if __name__ == "__main__":
    main()
