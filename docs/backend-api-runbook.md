# QuantAI Backend API Runbook

> 目标：按 `v2 / P1` 实施路线，仅通过后端接口验证“数据获取模块 -> 量化研究模块”的最小闭环。  
> 默认地址：`http://localhost:8000`

---

## 1. 启动方式

```bash
cd quant-ai
cp .env.example .env
# 按需填写 TUSHARE_API_KEY

./venv/bin/python scripts/init_db.py
./venv/bin/python main.py
```

启动后可使用：

- OpenAPI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

当前默认还会自动执行：

- 启动时初始化研究资产池
- 工作日 `18:05` 增量同步指数 / ETF
- 工作日 `18:12` 重建市场宽度特征
- 工作日 `18:20` 同步 A500 成分数据

---

## 2. P1 验证顺序

建议按下面顺序做后端验证：

1. `GET /health`
2. `POST /api/v1/universe/bootstrap`
3. `GET /api/v1/universe/assets`
4. `GET /api/v1/universe/mappings`
5. `POST /api/v1/universe/sync`
6. `GET /api/v1/universe/statuses`
7. `POST /api/v1/features/breadth/rebuild`
8. `GET /api/v1/features/breadth`
9. `GET /api/v1/factors/{symbol}`
10. `POST /api/v1/backtest`
11. `GET /api/v1/logs/jobs`
12. `POST /api/v1/universe/sectors/rebuild`

这样可以先验证数据模块，再验证研究模块。

---

## 3. 推荐冒烟脚本

### 3.1 快速 `curl` 脚本

```bash
cd quant-ai
chmod +x scripts/p1_backend_smoke.sh
BASE_URL=http://localhost:8000 \
ASSET_TYPE=index \
START=2025-01-01 \
END=$(date +%F) \
LIMIT=3 \
./scripts/p1_backend_smoke.sh
```

### 3.2 完整 Python 冒烟脚本

```bash
cd quant-ai
./venv/bin/python scripts/p1_backend_smoke.py \
  --base-url http://localhost:8000 \
  --profile full \
  --asset-type index \
  --start 2025-01-01 \
  --end $(date +%F) \
  --limit 3 \
  --symbol sh000300 \
  --output-json ./tmp/p1-backend-report.json
```

如果要验证 ETF：

```bash
./venv/bin/python scripts/p1_backend_smoke.py \
  --profile research \
  --asset-type etf \
  --symbol sh510300
```

可选 `profile`：

- `core`：健康检查 + universe 基础接口 + 日志
- `research`：数据同步 + 宽度 + 因子 + 回测 + 日志
- `sector`：板块派生 + 成分查询 + 日志
- `full`：全部检查

### 3.3 `.http` 请求集合

如果你在 IDE 里使用 REST Client，可直接打开：

- `docs/http/p1-backend.http`

逐条执行后端接口。

---

## 4. 核心接口调用示例

### 4.1 健康检查

```bash
curl -s http://localhost:8000/health
```

### 4.2 初始化研究资产池

会写入：

- `asset_universe`
- `asset_mapping`
- `asset_tags`

```bash
curl -s -X POST http://localhost:8000/api/v1/universe/bootstrap
```

### 4.3 查询研究资产池

```bash
curl -s "http://localhost:8000/api/v1/universe/assets?asset_type=index&limit=50"
curl -s "http://localhost:8000/api/v1/universe/assets?asset_type=etf&limit=50"
curl -s "http://localhost:8000/api/v1/universe/statuses?asset_type=index"
curl -s "http://localhost:8000/api/v1/universe/mappings?relation_type=tracks"
curl -s "http://localhost:8000/api/v1/universe/tags?tag_type=theme"
```

### 4.4 同步研究资产日线

这里的同步会把指数 / ETF 日线写入现有 `daily_quotes`，并通过兼容视图暴露成：

- `asset_daily_quotes`
- `asset_data_status`

```bash
curl -s -X POST http://localhost:8000/api/v1/universe/sync \
  -H "Content-Type: application/json" \
  -d '{
    "asset_type": "index",
    "start": "2025-01-01",
    "end": "2026-04-12",
    "only_active": true,
    "limit": 3
  }'
```

### 4.5 单标的日线同步

`POST /api/v1/data/update` 已支持：

- A 股股票，如 `000001`
- 指数，如 `sh000300`
- ETF，如 `sh510300`

```bash
curl -s -X POST http://localhost:8000/api/v1/data/update \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "sh000300",
    "start": "2025-01-01",
    "end": "2026-04-12"
  }'
```

### 4.6 市场宽度特征重建

```bash
curl -s -X POST http://localhost:8000/api/v1/features/breadth/rebuild \
  -H "Content-Type: application/json" \
  -d '{
    "start": "2025-01-01",
    "end": "2026-04-12"
  }'

curl -s "http://localhost:8000/api/v1/features/breadth?limit=5"
```

当前第一版宽度特征包括：

- 上涨家数 / 下跌家数 / 平盘家数
- 平均涨跌幅 / 中位数涨跌幅
- 总成交额
- 高换手占比
- 20 日新高 / 新低比例
- 行业强弱摘要

### 4.7 研究模块验证

先确保指数或 ETF 数据已经通过上面的接口同步入库。

```bash
curl -s "http://localhost:8000/api/v1/factors/sh000300"

curl -s -X POST http://localhost:8000/api/v1/backtest \
  -H "Content-Type: application/json" \
  -d '{
    "strategy_id": "ma_cross",
    "symbol": "sh000300",
    "start": "2025-01-01",
    "end": "2026-04-12",
    "params": {"fast": 5, "slow": 20}
  }'
```

### 4.8 查询后端任务日志

```bash
curl -s "http://localhost:8000/api/v1/logs/jobs?limit=20"
curl -s "http://localhost:8000/api/v1/logs/jobs?job_name=research_universe_sync&limit=10"
curl -s "http://localhost:8000/api/v1/logs/jobs?status=failed&limit=20"
```

当前已记录的核心任务包括：

- `stock_list_update`
- `daily_update`
- `research_universe_bootstrap`
- `research_universe_sync`
- `research_universe_incremental_sync`
- `market_breadth_rebuild`
- `scheduler_startup_bootstrap`
- `scheduler_research_universe_sync`
- `scheduler_market_breadth_sync`
- `scheduler_a500_sync`

### 4.9 基于股票行业派生板块资产池

当前第一版不依赖外部新源，直接基于 `stocks.industry` 派生 sector universe。

```bash
curl -s -X POST "http://localhost:8000/api/v1/universe/sectors/rebuild?market=A"
curl -s "http://localhost:8000/api/v1/universe/assets?asset_type=sector&limit=20"
curl -s "http://localhost:8000/api/v1/universe/sectors/constituents?sector_symbol=sector:银行"
curl -s "http://localhost:8000/api/v1/logs/jobs?job_name=sector_universe_rebuild&limit=5"
```

当前验证结果：

- 已成功派生 `110` 个 sector 资产
- 已生成 `5500` 条 stock -> sector 映射

---

## 5. 自动化调度配置

可通过 `.env` 控制：

```bash
RESEARCH_UNIVERSE_BOOTSTRAP_ON_START=true
RESEARCH_UNIVERSE_SYNC_ENABLED=true
RESEARCH_UNIVERSE_SYNC_HOUR=18
RESEARCH_UNIVERSE_SYNC_MINUTE=5
RESEARCH_SYNC_LOOKBACK_DAYS=400
RESEARCH_SYNC_OVERLAP_DAYS=5

MARKET_BREADTH_SYNC_ENABLED=true
MARKET_BREADTH_SYNC_HOUR=18
MARKET_BREADTH_SYNC_MINUTE=12
MARKET_BREADTH_LOOKBACK_DAYS=120
```

说明：

- `RESEARCH_UNIVERSE_BOOTSTRAP_ON_START`：服务启动时自动把内置指数 / ETF 研究资产写入数据库
- `RESEARCH_UNIVERSE_SYNC_*`：控制工作日指数 / ETF 增量同步
- `RESEARCH_SYNC_LOOKBACK_DAYS`：首次或无数据时默认回补窗口
- `RESEARCH_SYNC_OVERLAP_DAYS`：增量同步时向前重叠补数，避免漏交易日
- `MARKET_BREADTH_SYNC_*`：控制市场宽度的自动重建
- `MARKET_BREADTH_LOOKBACK_DAYS`：每次重建的回算窗口

---

## 6. 长任务建议

### A500 成分同步

HTTP 接口适合触发，但长时间运行更推荐脚本：

```bash
curl -s -X POST "http://localhost:8000/api/v1/data/a500/sync?add_watchlist=false&refresh_stock_list=true"
./venv/bin/python scripts/sync_a500.py
```

默认行为：

- 只拉数据
- 不自动加入自选

---

## 7. 当前 P1 已落地的后端能力

- 研究资产池：指数 / ETF / 映射 / 标签
- 派生板块资产池：sector universe + 成分映射
- 指数 / ETF 日线批量同步
- 兼容视图：`asset_daily_quotes` / `asset_data_status`
- 市场宽度派生特征
- 结构化任务日志与日志查询接口
- 纯接口化后端验证脚本

---

## 8. 下一步建议

按当前实现，后续可以继续直接往下做：

1. 增加更丰富的主题 / 概念来源，而不只依赖 `stocks.industry`
2. 给 `asset_universe` 增加更多研究标的和映射
3. 给 sector / theme 增加研究维度接口
4. 基于这些接口开始做 `P2` 因子研究与评估
