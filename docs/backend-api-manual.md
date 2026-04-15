# QuantAI Guardian — 后端 API 使用手册

> **基础 URL**: `http://localhost:8000`  
> **交互式文档**: `http://localhost:8000/docs` (Swagger UI)  
> **OpenAPI JSON**: `http://localhost:8000/openapi.json`

本文档覆盖后端所有 API 端点，按典型使用流程组织，包含完整的请求/响应示例。

---

## 目录

1. [系统运维](#1-系统运维)
2. [基础数据管理](#2-基础数据管理)
3. [研究资产池](#3-研究资产池)
4. [市场宽度特征](#4-市场宽度特征)
5. [因子研究 (P2)](#5-因子研究-p2)
6. [ML 模型 (P3)](#6-ml-模型-p3)
7. [自动挖掘 + Pipeline (P4)](#7-自动挖掘--pipeline-p4)
8. [策略回测](#8-策略回测)
9. [风控](#9-风控)
10. [模拟交易](#10-模拟交易)
11. [自选管理](#11-自选管理)
12. [报告](#12-报告)
13. [典型工作流](#13-典型工作流)

---

## 1. 系统运维

### 1.1 健康检查

```
GET /health
```

**响应**:
```json
{
  "status": "ok",
  "uptime": 1234.5,
  "data_service": true,
  "strategy_service": true,
  "scheduler": true
}
```

### 1.2 系统指标

```
GET /metrics
```

返回最近 50 条系统指标（内存、CPU、事件计数等）。

### 1.3 告警列表

```
GET /alerts?limit=20
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| limit | int | 20 | 返回条数 (1-100) |

### 1.4 事件通道

```
GET /api/v1/events/channels
```

返回事件总线注册的通道列表。

### 1.5 任务日志

```
GET /api/v1/logs/jobs?job_name=daily_update&status=success&limit=50
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| job_name | string | 空 | 如 `daily_update`, `research_universe_sync` |
| status | string | 空 | `success` / `failed` |
| limit | int | 50 | 返回条数 |

### 1.6 数据汇总

```
GET /api/v1/data/summary
```

**响应**:
```json
{
  "stocks": {"count": 5423},
  "daily_quotes": {"symbols": 128, "rows": 45000, "min_date": "2024-01-02", "max_date": "2026-04-10"},
  "asset_universe": {"index": 12, "etf": 10, "stock": 45, "sector": 30},
  "factor_values": {"rows": 12000, "symbols": 3},
  "factor_eval_results": {"rows": 42},
  "strategies": {"count": 3},
  "backtest_results": {"count": 15},
  "watchlist": {"count": 20},
  "job_logs": {"count": 100},
  "alerts": {"count": 5}
}
```

---

## 2. 基础数据管理

### 2.1 获取股票列表

```
GET /api/v1/stocks?market=A
```

### 2.2 刷新股票列表

```
POST /api/v1/stocks/update?market=A
```

从数据源拉取最新股票列表并写入 `stocks` 表。

### 2.3 获取指数实时行情

```
GET /api/v1/market/indices
```

返回内置指数池（沪深300、中证500 等）的实时行情。

### 2.4 获取 ETF 实时行情

```
GET /api/v1/market/etfs
```

### 2.5 获取指数 K 线（实时源）

```
GET /api/v1/index/{code}/daily?days=120
```

从腾讯财经直接拉取，不经过数据库。`code` 如 `sh000300`。

### 2.6 读取日线数据（数据库）

```
GET /api/v1/data/{symbol}/daily?start=2025-01-01&end=2026-04-12&limit=500
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| start | string | 2024-01-01 | 开始日期 |
| end | string | 今天 | 结束日期 |
| limit | int | 500 | 返回条数 (1-5000) |

**响应**:
```json
{
  "symbol": "sh000300",
  "rows": 306,
  "data": [
    {"trade_date": "2025-01-02", "open": 3800.0, "high": 3850.0, "low": 3780.0, "close": 3820.0, "volume": 150000000, "amount": 200000000000, "turnover": 1.5}
  ]
}
```

### 2.7 查询标的数据状态

```
GET /api/v1/data/{symbol}/info
```

返回该标的在数据库中的日线条数、起止日期。

### 2.8 全部日线状态汇总

```
GET /api/v1/data/statuses
```

### 2.9 拉取日线并入库

```
POST /api/v1/data/update
Content-Type: application/json

{
  "symbol": "sh000300",
  "start": "2025-01-01",
  "end": "2026-04-12"
}
```

支持 A 股(`000001`)、指数(`sh000300`)、ETF(`sh510300`)。

### 2.10 同步 A500 成分日线

```
POST /api/v1/data/a500/sync

{
  "add_watchlist": false,
  "refresh_stock_list": true
}
```

---

## 3. 研究资产池

### 3.1 初始化资产池

```
POST /api/v1/universe/bootstrap
```

写入内置指数、ETF 到 `asset_universe` + `asset_mapping` + `asset_tags`。

### 3.2 查询资产池

```
GET /api/v1/universe/assets?asset_type=index&only_active=true&limit=500
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| asset_type | string | 空 | `index` / `etf` / `stock` / `sector` |
| only_active | bool | true | 是否只看启用资产 |
| limit | int | 500 | 返回条数 |

### 3.3 资产日线状态汇总

```
GET /api/v1/universe/statuses
```

### 3.4 查询映射关系

```
GET /api/v1/universe/mappings?relation_type=tracks&source_symbol=sh510300
```

### 3.5 查询资产标签

```
GET /api/v1/universe/tags?symbol=sh000300&tag_type=theme
```

### 3.6 派生板块资产池

```
POST /api/v1/universe/sectors/rebuild?market=A
```

从 `stocks.industry` 派生板块资产池。

### 3.7 查询板块成分股

```
GET /api/v1/universe/sectors/constituents?industry=银行&limit=200
```

### 3.8 批量同步资产日线

```
POST /api/v1/universe/sync

{
  "asset_type": "index",
  "start": "2025-01-01",
  "end": "2026-04-12",
  "only_active": true,
  "limit": 3
}
```

---

## 4. 市场宽度特征

### 4.1 重建市场宽度

```
POST /api/v1/features/breadth/rebuild

{
  "start": "2025-01-01",
  "end": "2026-04-12"
}
```

基于已有股票日线计算：上涨/下跌/平盘家数、平均/中位数涨跌幅、总成交额、高换手占比、20日新高/新低占比、行业强弱摘要。

### 4.2 查询市场宽度

```
GET /api/v1/features/breadth?start=2025-01-01&end=2026-04-12&limit=60
```

---

## 5. 因子研究 (P2)

### 5.1 查看因子库

```
GET /api/v1/factors/library/list
```

**响应**:
```json
{
  "count": 42,
  "factors": ["ma_5", "ma_10", "ma_20", "ma_60", "ema_5", "ema_10", "ema_20", "ema_60", "macd", "macd_signal", "macd_hist", "adx", "plus_di", "minus_di", "rsi_14", "roc_5", "roc_10", "roc_20", "cci", "williams_r", "stoch_k", "stoch_d", "bb_upper", "bb_middle", "bb_lower", "bb_width", "bb_pct", "atr", "atr_pct", "rvol_5", "rvol_10", "rvol_20", "obv", "vwap", "volume_ratio", "ret_1", "ret_5", "ret_10", "ret_20", "log_ret", "hl_range", "co_range"]
}
```

**因子分类**:

| 类别 | 因子 |
|---|---|
| 趋势 | MA(5/10/20/60), EMA(5/10/20/60), MACD/Signal/Hist, ADX/+DI/-DI |
| 动量 | RSI(14), ROC(5/10/20), CCI, Williams %R, Stoch %K/%D |
| 波动率 | BB Upper/Middle/Lower/Width/Pct, ATR/ATR%, RVol(5/10/20) |
| 成交量 | OBV, VWAP, Volume Ratio |
| 价格形态 | Returns(1/5/10/20), Log Return, HL Range, CO Range |

### 5.2 计算因子（不持久化）

```
GET /api/v1/factors/{symbol}?full=false
```

### 5.3 批量计算并持久化

```
POST /api/v1/factors/batch-compute

{
  "symbol": "sh000300",
  "start": "2025-01-01",
  "end": "2026-04-12",
  "persist": true
}
```

**响应**:
```json
{
  "symbol": "sh000300",
  "rows": 306,
  "factors": ["ma_5", "ma_10", "..."],
  "sample": [{"trade_date": "2026-04-10", "ma_5": 3820.5, "rsi_14": 52.3, "...": "..."}]
}
```

### 5.4 因子评估

```
POST /api/v1/factors/evaluate

{
  "symbol": "sh000300",
  "forward_period": 5,
  "start": "2025-01-01",
  "end": "2026-04-12",
  "persist": true
}
```

**响应** (每个因子一条):
```json
[
  {
    "factor_name": "rsi_14",
    "ic_mean": -0.045,
    "ic_std": 0.18,
    "icir": -0.25,
    "rank_ic_mean": -0.05,
    "rank_icir": -0.28,
    "ic_positive_ratio": 0.42,
    "monotonicity": 0.12,
    "sub_period_ics": {"2025-Q1": -0.03, "2025-Q2": -0.06}
  }
]
```

### 5.5 因子 Walk-Forward 验证

```
POST /api/v1/factors/walk-forward

{
  "symbol": "sh000300",
  "factor_names": ["rsi_14", "macd_hist", "cci", "roc_5"],
  "train_days": 120,
  "test_days": 20,
  "step_days": 20,
  "forward_period": 5,
  "start": "2025-01-01"
}
```

如果 `factor_names` 为空/不传，则验证全部因子。

### 5.6 查询评估历史

```
GET /api/v1/factors/eval-history?symbol=sh000300&factor_name=rsi_14&limit=100
```

### 5.7 查询持久化因子值

```
GET /api/v1/factors/values/{symbol}?factor_name=rsi_14&limit=60
```

---

## 6. ML 模型 (P3)

### 6.1 生成标签

```
POST /api/v1/ml/labels

{
  "symbol": "sh000300",
  "forward_periods": [5, 10, 20],
  "start": "2025-01-01"
}
```

**响应**:
```json
{
  "symbol": "sh000300",
  "rows": 306,
  "labels": [
    "fwd_ret_5", "fwd_ret_10", "fwd_ret_20",
    "label_dir_5", "label_dir_10", "label_dir_20",
    "label_bucket_5", "label_vol_regime"
  ],
  "sample": [
    {"trade_date": "2026-03-27", "fwd_ret_5": -0.0137, "label_dir_5": 0, "label_bucket_5": 0, "label_vol_regime": 1}
  ]
}
```

**标签说明**:

| 标签 | 说明 |
|---|---|
| `fwd_ret_N` | 未来 N 日收益率 |
| `label_dir_N` | 方向标签: 1=上涨 0=下跌/平 |
| `label_bucket_N` | 分桶标签: 0=低 1=中 2=高 (三分位) |
| `label_vol_regime` | 波动率 regime: 0=低波 1=中波 2=高波 |

### 6.2 特征筛选

```
POST /api/v1/ml/feature-select

{
  "symbol": "sh000300",
  "start": "2025-01-01"
}
```

**响应**:
```json
{
  "symbol": "sh000300",
  "label_col": "label_dir_5",
  "report": {
    "original_count": 42,
    "after_variance": 42,
    "after_correlation": 27,
    "final_count": 27,
    "dropped_variance": [],
    "dropped_correlation": ["ema_10", "ema_20", "ma_10", "..."],
    "feature_ranking": [
      {"feature": "atr_pct", "abs_ic": 0.12, "ic": -0.12},
      {"feature": "rvol_20", "abs_ic": 0.11, "ic": -0.11}
    ]
  }
}
```

**三阶段 Pipeline**:
1. **方差过滤**: 移除方差 < 1e-6 的常量因子
2. **相关性去重**: 移除相关性 > 0.92 的冗余因子
3. **IC 重要性排序**: 按 |IC| 降序排列

### 6.3 训练模型

```
POST /api/v1/ml/train

{
  "symbol": "sh000300",
  "model_type": "lightgbm",
  "label_col": "label_dir_5",
  "forward_period": 5,
  "train_ratio": 0.8,
  "start": "2025-01-01",
  "params": {
    "n_estimators": 200,
    "max_depth": 5,
    "learning_rate": 0.05
  }
}
```

**支持的模型**:

| model_type | 算法 | 说明 |
|---|---|---|
| `lasso` | L1 LogisticRegression | 稀疏线性模型，适合基线 |
| `lightgbm` | LightGBM Classifier | 梯度提升树，适合非线性关系 |

**响应**:
```json
{
  "model_id": "lightgbm_sh000300_label_dir_5_20260412_134010",
  "model_type": "lightgbm",
  "symbol": "sh000300",
  "label_col": "label_dir_5",
  "n_features": 27,
  "n_train": 220,
  "n_test": 62,
  "train_metrics": {
    "accuracy": 0.95,
    "precision": 0.94,
    "recall": 0.96,
    "f1": 0.95,
    "auc": 0.99,
    "log_loss": 0.15
  },
  "test_metrics": {
    "accuracy": 0.54,
    "precision": 0.50,
    "recall": 0.48,
    "f1": 0.49,
    "auc": 0.55,
    "log_loss": 0.70
  },
  "feature_importance": [
    {"feature": "atr", "importance": 116},
    {"feature": "rvol_20", "importance": 114},
    {"feature": "ema_5", "importance": 88}
  ],
  "created_at": "2026-04-12T13:40:10"
}
```

模型自动序列化到 `data/models/{model_id}.pkl` + `.json`。

### 6.4 列出已训练模型

```
GET /api/v1/ml/models
```

**响应**:
```json
{
  "count": 3,
  "models": [
    {"model_id": "lightgbm_sh000300_label_dir_5_20260412_134010", "model_type": "lightgbm", "symbol": "sh000300", "...": "..."},
    {"model_id": "lasso_sh000300_label_dir_5_20260412_134007", "model_type": "lasso", "...": "..."}
  ]
}
```

### 6.5 模型 Walk-Forward 验证

```
POST /api/v1/ml/walk-forward

{
  "symbol": "sh000300",
  "model_type": "lightgbm",
  "label_col": "label_dir_5",
  "forward_period": 5,
  "train_days": 200,
  "test_days": 20,
  "step_days": 20,
  "start": "2025-01-01"
}
```

**响应**:
```json
{
  "model_type": "lightgbm",
  "symbol": "sh000300",
  "label_col": "label_dir_5",
  "n_folds": 5,
  "avg_accuracy": 0.54,
  "avg_f1": 0.42,
  "avg_auc": 0.66,
  "cumulative_return": -0.094,
  "cumulative_sharpe": -3.25,
  "folds": [
    {
      "fold": 0,
      "train_period": "2025-01-02~2025-10-16",
      "test_period": "2025-10-17~2025-11-14",
      "n_train": 180,
      "n_test": 20,
      "accuracy": 0.55,
      "f1": 0.50,
      "auc": 0.70,
      "fold_return": 0.02,
      "fold_sharpe": 1.5
    }
  ]
}
```

### 6.6 预测信号

```
POST /api/v1/ml/predict

{
  "model_id": "lightgbm_sh000300_label_dir_5_20260412_134010",
  "symbol": "sh000300",
  "start": "2026-03-01",
  "end": "2026-04-12"
}
```

**响应**:
```json
{
  "model_id": "lightgbm_sh000300_label_dir_5_20260412_134010",
  "symbol": "sh000300",
  "count": 30,
  "predictions": [
    {"date": "2026-03-03", "prediction": 1, "probability": 0.72},
    {"date": "2026-03-04", "prediction": 0, "probability": 0.35},
    {"date": "2026-04-10", "prediction": 0, "probability": 0.28}
  ]
}
```

**信号含义**: `prediction=1` 看多（概率 > 0.5），`prediction=0` 看空。`probability` 为看多概率。

---

## 7. 自动挖掘 + Pipeline (P4)

### 7.1 GP 表达式挖掘

```
POST /api/v1/ml/gp-mine

{
  "symbol": "sh000300",
  "forward_period": 5,
  "population_size": 300,
  "n_generations": 20,
  "metric": "sharpe",
  "start": "2025-01-01"
}
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| population_size | int | 200 | 种群大小 (20-1000) |
| n_generations | int | 30 | 进化代数 (5-200) |
| metric | string | sharpe | 适应度指标: `sharpe` / `ic` |

**响应**:
```json
{
  "symbol": "sh000300",
  "n_generations": 20,
  "population_size": 300,
  "hall_of_fame_size": 10,
  "best_expressions": [
    {
      "expression": "_safe_div(_abs(min(_safe_sqrt(...))), max(...))",
      "fitness_sharpe": 5.38,
      "fitness_return": 1.4524,
      "fitness_ic": 0.087,
      "n_generations": 20,
      "depth": 8
    }
  ]
}
```

**可用运算符**: `+`, `-`, `*`, `/`(安全除), `neg`, `abs`, `log`(安全), `sqrt`(安全), `max`, `min`

### 7.2 一键 Pipeline

```
POST /api/v1/ml/pipeline

{
  "symbol": "sh000300",
  "model_type": "lightgbm",
  "label_col": "label_dir_5",
  "forward_period": 5,
  "train_ratio": 0.8,
  "wf_train_days": 200,
  "wf_test_days": 20,
  "wf_step_days": 20,
  "start": "2025-01-01",
  "model_params": {
    "n_estimators": 200,
    "max_depth": 5
  }
}
```

**完整流程**:
1. 因子计算 (42+ 个技术因子)
2. 标签工程 (方向标签 + 分桶 + regime)
3. 特征筛选 (方差 → 相关性 → IC)
4. 模型训练 (Lasso 或 LightGBM)
5. Walk-Forward 验证
6. 生成最新 5 日信号

**响应**:
```json
{
  "symbol": "sh000300",
  "n_rows": 306,
  "n_features_original": 42,
  "n_features_selected": 27,
  "label_col": "label_dir_5",
  "model_type": "lightgbm",
  "selection_report": {"original_count": 42, "final_count": 27, "...": "..."},
  "train_result": {"model_id": "...", "test_metrics": {"accuracy": 0.54, "f1": 0.49, "auc": 0.55}},
  "walk_forward_result": {"n_folds": 5, "avg_accuracy": 0.54, "avg_auc": 0.66, "cumulative_return": -0.094},
  "latest_signal": {
    "model_id": "lightgbm_sh000300_label_dir_5_20260412_...",
    "predictions": [
      {"date": "2026-04-08", "prediction": 0, "probability": 0.39},
      {"date": "2026-04-10", "prediction": 0, "probability": 0.28}
    ]
  }
}
```

---

## 8. 策略回测

### 8.1 运行回测

```
POST /api/v1/backtest

{
  "strategy_id": "ma_cross",
  "symbol": "sh000300",
  "start": "2025-06-01",
  "end": "2026-04-12",
  "params": {"fast": 5, "slow": 20}
}
```

**可用策略**:

| strategy_id | 名称 | 参数 |
|---|---|---|
| `ma_cross` | MA 均线交叉 | `fast`, `slow` |
| `rsi_reversal` | RSI 超买超卖反转 | `period`, `oversold`, `overbought` |
| `bollinger_breakout` | 布林通道突破 | `period`, `num_std` |

### 8.2 查询回测历史

```
GET /api/v1/backtest/history?strategy_id=ma_cross&limit=20
```

### 8.3 策略管理

```
GET /api/v1/strategies
POST /api/v1/strategies/register
PUT /api/v1/strategies/{strategy_id}/status
```

### 8.4 参数优化

```
POST /api/v1/optimize

{
  "strategy_id": "ma_cross",
  "symbol": "sh000300",
  "start": "2025-01-01",
  "end": "2026-04-12",
  "n_trials": 20,
  "metric": "sharpe_ratio"
}
```

---

## 9. 风控

### 9.1 风险检查

```
POST /api/v1/risk/check
```

### 9.2 风控阈值

```
GET /api/v1/risk/thresholds
```

---

## 10. 模拟交易

```
POST   /api/v1/paper/accounts          # 创建账户
GET    /api/v1/paper/accounts          # 列出账户
GET    /api/v1/paper/accounts/{id}     # 查询账户
POST   /api/v1/paper/accounts/{id}/reset  # 重置账户
POST   /api/v1/paper/orders            # 下单
GET    /api/v1/paper/orders            # 查询订单
```

---

## 11. 自选管理

```
GET    /api/v1/watchlist                # 查询自选
POST   /api/v1/watchlist               # 加入自选 {"symbol": "sh000300", "name": "沪深300"}
DELETE /api/v1/watchlist/{symbol}       # 移除自选
```

---

## 12. 报告

```
POST /api/v1/reports/daily
```

生成每日 Markdown 报告。

---

## 13. 典型工作流

### 工作流 A: 从零开始研究一个指数

```bash
# Step 1: 拉取数据
curl -X POST localhost:8000/api/v1/data/update \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"sh000300","start":"2024-01-01"}'

# Step 2: 查看数据状态
curl localhost:8000/api/v1/data/sh000300/info

# Step 3: 一键 Pipeline（因子→标签→筛选→训练→验证→信号）
curl -X POST localhost:8000/api/v1/ml/pipeline \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"sh000300","model_type":"lightgbm","start":"2024-01-01"}'
```

### 工作流 B: 深度因子研究

```bash
# Step 1: 批量计算因子
curl -X POST localhost:8000/api/v1/factors/batch-compute \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"sh000300","start":"2024-01-01","persist":true}'

# Step 2: 评估因子有效性
curl -X POST localhost:8000/api/v1/factors/evaluate \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"sh000300","forward_period":5,"persist":true}'

# Step 3: Walk-Forward 样本外验证
curl -X POST localhost:8000/api/v1/factors/walk-forward \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"sh000300","factor_names":["rsi_14","macd_hist","cci"]}'

# Step 4: 查看因子评估历史
curl 'localhost:8000/api/v1/factors/eval-history?symbol=sh000300'
```

### 工作流 C: GP 自动挖掘

```bash
# Step 1: 确保因子数据已计算
curl -X POST localhost:8000/api/v1/factors/batch-compute \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"sh000300","start":"2024-01-01","persist":true}'

# Step 2: 运行 GP 挖掘
curl -X POST localhost:8000/api/v1/ml/gp-mine \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"sh000300","population_size":500,"n_generations":50,"metric":"sharpe"}'
```

### 工作流 D: 分步 ML 训练

```bash
# Step 1: 查看标签
curl -X POST localhost:8000/api/v1/ml/labels \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"sh000300","start":"2024-01-01"}'

# Step 2: 特征筛选报告
curl -X POST localhost:8000/api/v1/ml/feature-select \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"sh000300","start":"2024-01-01"}'

# Step 3: 训练 LightGBM
curl -X POST localhost:8000/api/v1/ml/train \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"sh000300","model_type":"lightgbm","label_col":"label_dir_5","start":"2024-01-01"}'

# Step 4: Walk-Forward 验证
curl -X POST localhost:8000/api/v1/ml/walk-forward \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"sh000300","model_type":"lightgbm","label_col":"label_dir_5","start":"2024-01-01"}'

# Step 5: 用训练好的模型预测
curl -X POST localhost:8000/api/v1/ml/predict \
  -H 'Content-Type: application/json' \
  -d '{"model_id":"MODEL_ID_FROM_STEP3","symbol":"sh000300","start":"2026-03-01"}'

# Step 6: 列出所有模型
curl localhost:8000/api/v1/ml/models
```

---

## 附录: 端点总览

| # | 方法 | 路径 | 分类 |
|---|---|---|---|
| 1 | GET | `/health` | 系统 |
| 2 | GET | `/metrics` | 系统 |
| 3 | GET | `/alerts` | 系统 |
| 4 | GET | `/api/v1/events/channels` | 系统 |
| 5 | GET | `/api/v1/logs/jobs` | 系统 |
| 6 | GET | `/api/v1/data/summary` | 系统 |
| 7 | GET | `/api/v1/stocks` | 数据 |
| 8 | POST | `/api/v1/stocks/update` | 数据 |
| 9 | GET | `/api/v1/market/indices` | 数据 |
| 10 | GET | `/api/v1/market/etfs` | 数据 |
| 11 | GET | `/api/v1/index/{code}/daily` | 数据 |
| 12 | GET | `/api/v1/data/{symbol}/daily` | 数据 |
| 13 | GET | `/api/v1/data/{symbol}/info` | 数据 |
| 14 | GET | `/api/v1/data/statuses` | 数据 |
| 15 | POST | `/api/v1/data/update` | 数据 |
| 16 | POST | `/api/v1/data/a500/sync` | 数据 |
| 17 | POST | `/api/v1/universe/bootstrap` | 资产池 |
| 18 | GET | `/api/v1/universe/assets` | 资产池 |
| 19 | GET | `/api/v1/universe/statuses` | 资产池 |
| 20 | GET | `/api/v1/universe/mappings` | 资产池 |
| 21 | GET | `/api/v1/universe/tags` | 资产池 |
| 22 | POST | `/api/v1/universe/sectors/rebuild` | 资产池 |
| 23 | GET | `/api/v1/universe/sectors/constituents` | 资产池 |
| 24 | POST | `/api/v1/universe/sync` | 资产池 |
| 25 | POST | `/api/v1/features/breadth/rebuild` | 市场宽度 |
| 26 | GET | `/api/v1/features/breadth` | 市场宽度 |
| 27 | GET | `/api/v1/factors/library/list` | P2 因子 |
| 28 | GET | `/api/v1/factors/{symbol}` | P2 因子 |
| 29 | POST | `/api/v1/factors/batch-compute` | P2 因子 |
| 30 | POST | `/api/v1/factors/evaluate` | P2 因子 |
| 31 | POST | `/api/v1/factors/walk-forward` | P2 因子 |
| 32 | GET | `/api/v1/factors/eval-history` | P2 因子 |
| 33 | GET | `/api/v1/factors/values/{symbol}` | P2 因子 |
| 34 | POST | `/api/v1/ml/labels` | P3 ML |
| 35 | POST | `/api/v1/ml/feature-select` | P3 ML |
| 36 | POST | `/api/v1/ml/train` | P3 ML |
| 37 | GET | `/api/v1/ml/models` | P3 ML |
| 38 | POST | `/api/v1/ml/walk-forward` | P3 ML |
| 39 | POST | `/api/v1/ml/predict` | P3 ML |
| 40 | POST | `/api/v1/ml/gp-mine` | P4 GP |
| 41 | POST | `/api/v1/ml/pipeline` | P4 Pipeline |
| 42 | POST | `/api/v1/backtest` | 策略 |
| 43 | GET | `/api/v1/backtest/history` | 策略 |
| 44 | GET | `/api/v1/strategies` | 策略 |
| 45 | POST | `/api/v1/strategies/register` | 策略 |
| 46 | PUT | `/api/v1/strategies/{id}/status` | 策略 |
| 47 | POST | `/api/v1/optimize` | 策略 |
| 48 | POST | `/api/v1/risk/check` | 风控 |
| 49 | GET | `/api/v1/risk/thresholds` | 风控 |
| 50 | POST | `/api/v1/paper/accounts` | 模拟 |
| 51 | GET | `/api/v1/paper/accounts` | 模拟 |
| 52 | GET | `/api/v1/paper/accounts/{id}` | 模拟 |
| 53 | POST | `/api/v1/paper/accounts/{id}/reset` | 模拟 |
| 54 | POST | `/api/v1/paper/orders` | 模拟 |
| 55 | GET | `/api/v1/paper/orders` | 模拟 |
| 56 | GET | `/api/v1/watchlist` | 自选 |
| 57 | POST | `/api/v1/watchlist` | 自选 |
| 58 | DELETE | `/api/v1/watchlist/{symbol}` | 自选 |
| 59 | POST | `/api/v1/reports/daily` | 报告 |
