---
title: A股量化因子选股与看板
type: tutorial
audience: [A1, A4]
runs: yes
verified_on: 2026-08-20
sources:
  - ma_features_200d_adj.sql
  - run_fast_200d_export.py
  - fetch_sw_industry.py
  - convert_200d_to_json.py
  - daily_update.py
  - server.py
  - test_30_stocks_full.py
  - docs/下一迭代因子策略需求文档.md
---

# A股量化因子选股与看板

本项目从聚源同步的 Oracle 测试库提取 A 股日行情，计算均线系统和九个策略因子，生成最近 200 个交易日的数据切片，并通过本地 Web 看板提供筛选、统计和明细穿透。

生产价格口径固定为 `CS_STOCKADJPERFORMANCE` 的前复权精确行情：

```text
ADJUSTINGMETHOD = 1
ADJUSTINGSTANDARD = 1
```

项目只生成研究与选股数据，不包含收益预测、组合构建、自动下单或实盘交易。

## 功能

- 覆盖沪市主板、科创板、深市主板和创业板。
- 使用前复权精确开高低收价格计算 K 线、均线和价格窗口。
- 合并主板/创业板与科创板成交额数据。
- 计算申万 2021 一级、二级和三级行业分类。
- 生成最近 200 个市场交易日的全市场面板。
- 将每日 JSON 切片写入版本目录，并原子切换线上 `data` 符号链接。
- 在历史覆盖不足、切片不完整或科创板成交额异常时拒绝发布。
- 提供 SQL 与纯 Python 的跨板块交叉验证。

## 因子标签

| 标签 | 含义 | 关键约束 |
| --- | --- | --- |
| `FACTOR_HL_5R` | HL+5R 底部五阳 | 180日回撤、低位反弹、五连阳、五日涨幅及180日无停牌 |
| `FACTOR_5R` | 五连阳 | T0至T-4收红、T-5收绿、排除HL+5R、六日无停牌 |
| `FACTOR_HIGH_ALL` | 覆盖期新高 | 上市交易日数大于500，突破覆盖期全部前序有效交易日最高价 |
| `FACTOR_HIGH_500` | 500有效日新高 | 上市交易日数大于500，排除覆盖期新高 |
| `FACTOR_HIGH_250` | 250有效日新高 | 上市交易日数大于250，排除前两类新高 |
| `FACTOR_HL_AMO` | 低位放量 | 满足AMO，并且前一日相对前180日高点回撤大于25% |
| `FACTOR_AMO` | 放量突破 | 成交额、最大额/均额倍数、收红、10日涨幅及16日无停牌 |
| `FACTOR_MA377_SUPPORT` | MA377支撑 | 连续四日位于MA377的 `[-2%, 7%]` 区间，至少一日收红 |
| `FACTOR_MA250_SUPPORT` | MA250支撑 | 连续四日位于MA250的 `[-2%, 7%]` 区间，至少一日收红 |

三个新高标签严格互斥。`HL_AMO` 可以与 `AMO` 同时命中，两个均线支撑标签也可以同时命中。`PRIMARY_FACTOR` 按以下顺序选择唯一主标签：

```text
HL_5R > 5R > HIGH_ALL > HIGH_500 > HIGH_250
> HL_AMO > AMO > MA377_SUPPORT > MA250_SUPPORT
```

均线系统另有 `LABEL` 标签：T0与T-1均满足 `MA5 > MA10 > MA20 > MA60 > MA120 > MA250`，且六条均线全部上升。

`4R` 只有名称，没有已确认的可执行定义，因此 v1.0 不输出 `FACTOR_4R`。

完整公式和边界定义见 [`docs/下一迭代因子策略需求文档.md`](docs/下一迭代因子策略需求文档.md)。

## 数据口径

| 数据 | 表或规则 |
| --- | --- |
| 股票池 | `SECUCODE` 前缀为 `60/68/00/30`，并且 `SECUCATEGORY = 1` |
| 前复权精确行情 | `CS_STOCKADJPERFORMANCE(ADJUSTINGMETHOD=1, ADJUSTINGSTANDARD=1)` |
| 主板/创业板成交额 | `QT_DAILYQUOTE.TURNOVERVALUE` |
| 科创板成交额 | `LC_STIBDAILYQUOTE.TURNOVERVALUE` |
| 市场交易日历 | `QT_TRADINGDAYNEW`，沪市市场码83 |
| 申万2021行业 | `LC_EXGINDUSTRY` 与 `LC_STIBEXGINDUSTRY`，`STANDARD=38` |
| 停牌识别 | `TURNOVERVALUE > 0` 为有效交易，否则为停牌占位行 |

窗口只使用 T0 及以前的数据。新高窗口按个股有效交易日序列计算；形态、放量和均线支撑窗口要求市场交易日连续并且窗口内无停牌。

`HIGH_ALL` 是数据库覆盖期新高，不等同于老股票真正的上市以来历史新高。最后一次成功发布的数据覆盖 2024-07-10 至 2026-08-18，共 512 个交易日；看板展示其中最近 200 个快照。

## 处理流程

```text
聚源 Oracle
  ├─ 前复权精确 OHLC
  ├─ 主板/创业板/科创板成交额
  └─ 申万 2021 行业
          ↓
ma_features_200d_adj.sql
          ↓
ma_features_200d_adj.csv
          ↓
data_versions/ver_YYYYMMDD_HHMMSS/
          ↓  原子切换
data -> 当前有效版本
          ↓
index.html / server.py
```

## 环境要求

- macOS 或其他能够运行 Oracle Instant Client 的环境。
- Python 3.11或更高版本。
- `python-oracledb` 4.x。
- Oracle Instant Client Basic，不能使用缺少 GBK 字符集的 Basic Light。
- 能访问聚源同步测试库 `JYDBTEST / ZBJYDB`。

Oracle 11.2.0.1 不支持 `python-oracledb` Thin 模式。所有数据库任务必须先初始化 Instant Client，再使用 Thick 模式连接。

创建虚拟环境并安装 Python 依赖。macOS/Homebrew 的系统 Python 受 PEP 668 管理，不要使用 `--break-system-packages` 绕过保护：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

检查环境：

```bash
python --version
python -c "import oracledb; print(oracledb.__version__)"
```

本版本验证环境为 Python 3.13.12、`python-oracledb` 4.0.2。

## 配置数据库连接

连接参数通过环境变量覆盖，其中 `JYDB_PASSWORD` 必须显式提供。不要把真实密码提交到 Git。

```bash title="not executed in this run"
export JYDB_HOST="<database-host>"
export JYDB_PORT="1521"
export JYDB_SERVICE="JYDBTEST"
export JYDB_USER="<database-user>"
export JYDB_PASSWORD="<database-password>"
```

当前脚本默认从 `/opt/oracle/instantclient` 加载 Instant Client。换机部署时，先修改各数据库入口脚本中的 `IC_DIR`，或将 Instant Client 安装到该路径。

配置完成后执行小查询验证连接：

```bash title="not executed in this run"
python3 oracle_jydb_helper.py
```

## 首次生成数据

以下步骤会连接数据库并生成数GB本地数据。确认磁盘空间和源表历史覆盖正常后再执行。

1. 生成申万行业映射：

   ```bash title="not executed in this run"
   python3 fetch_sw_industry.py
   ```

2. 导出最近200个交易日的全市场面板：

   ```bash title="not executed in this run"
   python3 run_fast_200d_export.py
   ```

3. 生成JSON切片并发布：

   ```bash title="not executed in this run"
   python3 convert_200d_to_json.py
   ```

也可以顺序执行导出与发布：

```bash title="not executed in this run"
python3 daily_update.py
```

`convert_200d_to_json.py` 只在以下校验全部通过后切换 `data`：

- 精确生成200个交易日切片。
- 源行情历史不少于300个交易日。
- 最新切片至少有500只科创板股票且成交额有效。
- 新版本完整写入独立版本目录。

发布失败不会替换当前有效版本。版本目录默认保留最近三代。

## 启动看板

数据生成成功后启动无缓存的多线程静态服务器：

```bash
python3 server.py
```

浏览器打开：

```text
http://localhost:8089/index.html
```

自定义端口：

```bash
PORT=8090 python3 server.py
```

按 `Ctrl+C` 停止服务器，不会删除任何数据。

## 验证

数据库可用时，运行30只跨板块股票的SQL与Python交叉验证：

```bash title="not executed in this run"
python3 test_30_stocks_full.py
```

测试包含：

- 无停牌与插入停牌的AMO A/B对照。
- 有效交易日新高跨停牌边界。
- 上市301日股票的HIGH_ALL门槛和HIGH_250降级。
- 30只股票乘200日、共6,000行九因子交叉比对。

已发布面板的数量、不变式和主标签优先级检查位于 `regression/`。这些脚本包含特定验收快照的预期值，切换数据日期后应先同步预期值再运行。

## 自动更新

`daily_cron_job.sh` 在执行前检查磁盘空间，并在不足3GB时清理旧版本。脚本会保留当前线上版本与最近版本，清理动作不可恢复，因此部署前应确认目录配置。

工作日每天19:00执行的 crontab 示例：

```cron
0 19 * * 1-5 ./daily_cron_job.sh
```

查看任务：

```bash
crontab -l
```

移除任务时运行 `crontab -e`，删除对应行即可回滚调度配置。

## 当前运行状态

- 最后一次成功发布：2026-08-18。
- 当前 `data` 指向 `data_versions/ver_20260819_091435`。
- 成功版本覆盖512个交易日，并提供200个看板快照。
- 2026-08-20检测到 `CS_STOCKADJPERFORMANCE` 同步历史缩短为243日。
- 发布护栏已拒绝该批次，线上仍保留最后一个完整版本。

恢复每日发布前，应先恢复源表长周期历史并重新执行完整验证。不要通过降低 `MIN_COVERAGE_DAYS` 绕过护栏。

## 目录

| 路径 | 说明 |
| --- | --- |
| `ma_features_200d_adj.sql` | 九因子和均线系统生产SQL |
| `run_fast_200d_export.py` | 流式执行SQL并生成CSV面板 |
| `fetch_sw_industry.py` | 生成申万2021行业映射 |
| `convert_200d_to_json.py` | 生成版本化JSON并原子发布 |
| `daily_update.py` | 日终导出与发布编排 |
| `daily_cron_job.sh` | cron包装、日志和磁盘预检 |
| `server.py` | 本地看板HTTP服务 |
| `index.html` | 看板前端 |
| `test_factor_calc.py` | 纯Python参考实现 |
| `test_30_stocks_full.py` | SQL与Python交叉验证 |
| `regression/` | 面板和数据库深度回归检查 |
| `docs/` | 需求文档与因子核对报告 |

CSV、JSON切片、日志、缓存和数据库生成的行业映射不进入 Git。它们可由上述流程重新生成。
