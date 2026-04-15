# QuantAI Guardian — API 参考文档

> 基础 URL: `http://localhost:8000`  
> 交互式文档: `http://localhost:8000/docs`  
> OpenAPI JSON: `http://localhost:8000/openapi.json`

---

## 1. 系统接口

### GET /health

系统健康检查。

### GET /metrics

最近 50 条系统指标。

### GET /alerts?limit=20

最近告警列表，`limit` 范围 `1-100`。

### GET /api/v1/events/channels

当前事件总线注册的通道列表。

### GET /api/v1/logs/jobs

查询后端结构化任务日志。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| job_name | string | 空 | 如 `daily_update`、`research_universe_sync` |
| status | string | 空 | 如 `success` / `failed` |
| limit | int | 50 | 返回条数上限 |

### GET /api/v1/data/summary

全平台数据汇总快照。返回所有核心表的统计信息：

- `stocks`: 总数
- `daily_quotes`: 标的数、行数、日期范围
- `asset_universe`: 按 asset_type 分组统计
- `asset_mapping` / `asset_tags`: 总数
- `market_breadth`: 行数、日期范围
- `factors` / `factor_values` / `factor_eval_results`: 统计信息
- `strategies` / `backtest_results`: 总数
- `watchlist` / `job_logs` / `alerts`: 统计信息

---

## 2. 基础数据接口

### GET /api/v1/stocks?market=A

获取股票列表。

### POST /api/v1/stocks/update?market=A

刷新股票列表并写入 `stocks`。

### GET /api/v1/market/indices

获取内置指数池实时行情。

### GET /api/v1/market/etfs

获取内置 ETF 池实时行情。

### GET /api/v1/index/{code}/daily?days=120

直接从腾讯财经拉取指数 K 线，不经过数据库。

### GET /api/v1/data/{symbol}/daily

从数据库读取日线。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| start | string | 2024-01-01 | 开始日期 |
| end | string | 今天 | 结束日期 |
| limit | int | 500 | 返回条数上限，范围 `1-5000` |

### GET /api/v1/data/{symbol}/info

返回数据库中该标的的日线条数、起止日期。

### GET /api/v1/data/statuses

返回全部日线状态汇总。

### POST /api/v1/data/update

从数据源拉取日线并写入 `daily_quotes`。

已支持：

- A 股股票，如 `000001`
- 指数，如 `sh000300`
- ETF，如 `sh510300`

**请求体**:

```json
{
  "symbol": "sh000300",
  "start": "2025-01-01",
  "end": "2026-04-12"
}
```

### POST /api/v1/data/a500/sync

同步中证 A500 成分日线。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| add_watchlist | bool | false | 是否把成分股加入自选 |
| refresh_stock_list | bool | true | 是否先刷新 A 股列表 |

长任务建议改用：

```bash
./venv/bin/python scripts/sync_a500.py
```

---

## 3. P1 研究资产池接口

### POST /api/v1/universe/bootstrap

初始化内置研究资产池，写入：

- `asset_universe`
- `asset_mapping`
- `asset_tags`

### GET /api/v1/universe/assets

查询研究资产池，并附带日线状态信息。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| asset_type | string | 空 | `index / etf / stock` |
| only_active | bool | true | 是否只看启用资产 |
| limit | int | 500 | 返回条数上限 |

### GET /api/v1/universe/statuses

查询研究资产池的日线状态汇总。

### GET /api/v1/universe/mappings

查询映射关系，如 ETF 跟踪指数。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| relation_type | string | 空 | 如 `tracks` |
| source_symbol | string | 空 | 如 `sh510300` |

### GET /api/v1/universe/tags

查询资产标签。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| symbol | string | 空 | 指定标的 |
| tag_type | string | 空 | 如 `theme` / `sector` / `style` |

### POST /api/v1/universe/sectors/rebuild?market=A

基于现有 `stocks.industry` 派生板块资产池，并写入：

- `asset_universe` 中的 `asset_type=sector`
- `asset_mapping` 中的 `belongs_to_sector`
- `asset_tags`

### GET /api/v1/universe/sectors/constituents

查询板块成分股。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| sector_symbol | string | 空 | 如 `sector:银行` |
| industry | string | 空 | 如 `银行`，会自动转为 `sector:银行` |
| limit | int | 200 | 返回条数上限 |

### POST /api/v1/universe/sync

批量同步研究资产池日线。

**请求体**:

```json
{
  "asset_type": "index",
  "start": "2025-01-01",
  "end": "2026-04-12",
  "only_active": true,
  "limit": 3
}
```

同步结果会继续写入现有 `daily_quotes`，同时通过兼容视图暴露为：

- `asset_daily_quotes`
- `asset_data_status`

---

## 4. 市场宽度接口

### POST /api/v1/features/breadth/rebuild

基于已有股票日线重建第一版市场宽度特征，写入 `market_breadth_features`。

**请求体**:

```json
{
  "start": "2025-01-01",
  "end": "2026-04-12"
}
```

### GET /api/v1/features/breadth

查询市场宽度特征结果。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| start | string | 空 | 开始日期 |
| end | string | 空 | 结束日期 |
| limit | int | 60 | 返回条数上限 |

当前第一版输出包括：

- 上涨 / 下跌 / 平盘家数
- 平均 / 中位数涨跌幅
- 总成交额
- 高换手占比
- 20 日新高 / 新低占比
- 行业强弱摘要

---

## 5. 研究模块接口

### GET /api/v1/factors/library/list

返回因子库中所有可用因子名称（40+ 个），包括趋势、动量、波动率、成交量、价格形态五大类。

### GET /api/v1/factors/{symbol}

计算全部技术因子并返回最近 N 行。建议先确保日线数据已拉取。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| full | bool | false | true 则返回全部行 |

### POST /api/v1/factors/batch-compute

批量计算全部因子并持久化到 `factor_values` 表。

**请求体**:

```json
{
  "symbol": "sh000300",
  "start": "2025-01-01",
  "end": "2026-04-12",
  "persist": true
}
```

返回计算行数、因子列名列表、尾部样本。

### POST /api/v1/factors/evaluate

对因子批量评估 IC/ICIR/Rank IC/单调性/分期表现，结果持久化到 `factor_eval_results`。

**请求体**:

```json
{
  "symbol": "sh000300",
  "forward_period": 5,
  "start": "2025-01-01",
  "end": "2026-04-12",
  "persist": true
}
```

### POST /api/v1/factors/walk-forward

Walk-forward（滚动窗口样本外）验证，输出每个 fold 的 train/test IC、收益、Sharpe。

**请求体**:

```json
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

### GET /api/v1/factors/eval-history

查询已持久化的因子评估记录。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| symbol | string | 空 | 如 `sh000300` |
| factor_name | string | 空 | 如 `rsi_14` |
| limit | int | 100 | 返回条数上限 |

### GET /api/v1/factors/values/{symbol}

查询已持久化的因子值。

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| factor_name | string | 空 | 如 `rsi_14` |
| limit | int | 60 | 返回条数上限 |

### POST /api/v1/backtest

运行策略回测。

**请求体**:

```json
{
  "strategy_id": "ma_cross",
  "symbol": "sh000300",
  "start": "2025-01-01",
  "end": "2026-04-12",
  "params": {"fast": 5, "slow": 20}
}
```

### GET /api/v1/backtest/history

查询回测历史。

### GET /api/v1/strategies

已注册策略列表。

### POST /api/v1/strategies/register

注册新策略元数据。

### PUT /api/v1/strategies/{strategy_id}/status

更新策略状态。

### POST /api/v1/optimize

运行参数优化。

---

## 5b. P3 ML 模型接口

### POST /api/v1/ml/labels

生成标签工程：未来 5/10/20 日前向收益 + 方向标签 + 分桶标签 + 波动率 regime。

**请求体**:

```json
{
  "symbol": "sh000300",
  "forward_periods": [5, 10, 20],
  "start": "2025-01-01"
}
```

### POST /api/v1/ml/feature-select

运行特征筛选 Pipeline（方差过滤 → 相关性去重 → 重要性排序），返回筛选报告。

### POST /api/v1/ml/train

训练择时模型（Lasso 或 LightGBM 二分类）。

**请求体**:

```json
{
  "symbol": "sh000300",
  "model_type": "lightgbm",
  "label_col": "label_dir_5",
  "forward_period": 5,
  "train_ratio": 0.8,
  "start": "2025-01-01"
}
```

返回训练/测试集 metrics（accuracy / precision / recall / F1 / AUC）+ 特征重要性。

### POST /api/v1/ml/walk-forward

Walk-forward ML 模型验证：滚动窗口训练→预测→评估，输出每个 fold 的 accuracy / F1 / AUC / 收益 / Sharpe。

### POST /api/v1/ml/predict

使用已训练模型预测择时信号。

| 参数 | 类型 | 说明 |
|---|---|---|
| model_id | string | 训练返回的 model_id |
| symbol | string | 预测标的 |

### GET /api/v1/ml/models

列出所有已训练的模型元信息。

---

## 5c. P4 GP 挖掘 + Pipeline 接口

### POST /api/v1/ml/gp-mine

运行 GP（遗传编程）自动表达式挖掘，发现择时信号表达式。

**请求体**:

```json
{
  "symbol": "sh000300",
  "forward_period": 5,
  "population_size": 200,
  "n_generations": 30,
  "max_depth": 5,
  "parsimony_coeff": 0.005,
  "metric": "sharpe",
  "save": false,
  "start": "2024-01-01",
  "end": "2026-04-12"
}
```

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| symbol | string | 必填 | 标的代码 |
| forward_period | int | 5 | 前瞻期天数 |
| population_size | int | 200 | 种群大小 (20-1000) |
| n_generations | int | 30 | 进化代数 (5-200) |
| max_depth | int | 5 | 最大树深 (2-5) |
| parsimony_coeff | float | 0.005 | 复杂度惩罚 (0-0.1) |
| metric | string | sharpe | 适应度 `sharpe` 或 `ic` |
| save | bool | false | 是否批量保存 Top5 |
| start | string | 2024-01-01 | 数据开始日期 |
| end | string | 今天 | 数据结束日期 |

返回 Hall of Fame 中的最优表达式（含 Sharpe / Return / IC）。

### POST /api/v1/ml/gp-save

保存单个 GP 表达式。

**请求体**:

```json
{
  "expression": "_safe_log(x19)",
  "symbol": "sh000300",
  "metric": "sharpe",
  "sharpe": 1.48,
  "total_ret": 2.75,
  "ic": 0.05,
  "depth": 1,
  "tree_size": 2
}
```

返回 `{ "gp_id": "...", "expression": "...", "symbol": "..." }`。

### POST /api/v1/ml/gp-evaluate

将已保存的 GP 表达式应用于指定标的和日期区间进行评估。

**请求体**:

```json
{
  "gp_id": "gp_sh000300_20260413_...",
  "symbol": "601988",
  "forward_period": 5,
  "start": "2024-01-01",
  "end": "2025-04-10"
}
```

**返回指标**:

| 字段 | 说明 |
|---|---|
| sharpe | Sharpe 比率 |
| total_return | 累计收益率 |
| annualized_return | 年化收益率 |
| ic | 信息系数 |
| win_rate | 胜率 |
| wins / losses | 盈利/亏损次数 |
| max_drawdown | 最大回撤 |
| avg_win / avg_loss | 平均盈利/亏损 |
| profit_factor | 盈亏比 |

支持跨标的评估（用 A 标的挖掘的表达式评估 B 标的）。

### GET /api/v1/ml/gp-list

列出所有已保存的 GP 表达式。

### POST /api/v1/ml/gp-predict

使用已保存的 GP 表达式预测信号。

### POST /api/v1/ml/pipeline

一键端到端 Pipeline：因子计算 → 标签工程 → 特征筛选 → ML 训练 → Walk-Forward 验证 → 最新信号输出。

**请求体**:

```json
{
  "symbol": "sh000300",
  "model_type": "lightgbm",
  "label_col": "label_dir_5",
  "forward_period": 5,
  "train_ratio": 0.8,
  "wf_train_days": 200,
  "wf_test_days": 20,
  "wf_step_days": 20,
  "start": "2025-01-01"
}
```

---

## 6. 风控接口

### POST /api/v1/risk/check

组合风险检查 + 回撤检查。

### GET /api/v1/risk/thresholds

读取当前风控阈值。

---

## 7. 模拟交易接口

### POST /api/v1/paper/accounts

创建模拟账户。

### GET /api/v1/paper/accounts

列出模拟账户。

### GET /api/v1/paper/accounts/{account_id}

查询单个模拟账户。

### POST /api/v1/paper/accounts/{account_id}/reset

重置模拟账户。

### POST /api/v1/paper/orders

下模拟单。

### GET /api/v1/paper/orders

查询模拟订单。

---

## 8. 自选接口

### GET /api/v1/watchlist

查询自选。

### POST /api/v1/watchlist

加入自选。

### DELETE /api/v1/watchlist/{symbol}

从自选移除。

---

## 9. 报告接口

### POST /api/v1/reports/daily

生成每日 Markdown 报告。

---

## 10. 推荐验证方式

如果你当前目标是按 `v2 / P1` 推进，推荐优先使用：

1. `docs/backend-api-runbook.md`
2. `scripts/p1_backend_smoke.sh`
3. `scripts/p1_backend_smoke.py`
