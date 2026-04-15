# QuantAI Guardian — 开发进度跟踪

> 更新日期: 2026-04-13
> 当前阶段: **构建阶段 (Phase 3) — 核心功能完善迭代**

---

## 阶段规划对照

| 阶段 | 状态 | 说明 |
|---|---|---|
| 第一阶段: 数据自动化 (第1-2周) | ✅ 完成 | 数据采集、清洗、存储、定时调度 |
| 第二阶段: 因子挖掘 + 回测 (第3-5周) | ✅ 完成 | 13个技术因子、向量化回测、3种策略、参数优化器 |
| 第三阶段: 可视化 + 风控 (第6-8周) | ✅ 完成 | 7页面前端、风控引擎、模拟交易 |
| 第四阶段: 策略部署 + 全链路 (第9-10周) | 🔶 进行中 | Paper Trading 已完成，OpenClaw 集成待开始 |

---

## 最近更新日志

### 2026-04-13 v0.7.2 — GP 表达式增强：数据区间 + 单个保存 + 评估

**GP 挖掘支持指定数据区间**

- 前端新增「开始日期」「结束日期」「前瞻期」输入框
- 后端 `gp-mine` API 已有 start/end 参数，前端此前写死 2025-01-01，现改为读取输入

**GP 表达式单个保存**

- 未勾选「批量保存 Top5」时，每个挖掘结果旁显示「保存」按钮
- 保存后按钮变为「预测/回测」+「评估」
- 新增 API: `POST /api/v1/ml/gp-save` 支持从表达式字符串直接保存
- 后端 `GPMiner.save_expression_from_str()` 自动推导 feature_cols

**GP 表达式评估（核心新功能）**

- 新增「GP 表达式评估」卡片，支持输入标的、日期区间、前瞻期
- 可从挖掘结果或已保存列表点击「评估」打开
- 评估指标: Sharpe / 总收益 / 年化 / IC / 胜率 / 最大回撤 / 盈亏比 / 平均盈利亏损
- 支持跨标的评估（用 A 标的挖掘的表达式评估 B 标的）
- 新增 API: `POST /api/v1/ml/gp-evaluate`
- 后端 `GPMiner.evaluate_expression()` 完整实现

**标签前瞻期截断修复 (v0.7.1)**

- 修复 `LabelEngine.add_direction_labels` 中 `label_dir_*` 在 `fwd_ret` 为 NaN 时被错误填充为 0 的 bug
- 确保最后 N 天（前瞻期天数）的方向标签保持 NaN
- `generate_labels` API 新增 `valid_rows`、`truncated_tail`、`nan_per_period`、`valid_end` 等字段
- 前端标签生成结果展示各前瞻期的 NaN 详情和截断提示

**文件变更**

| 文件 | 变更 |
|---|---|
| `services/strategy_service/ml/gp_miner.py` | 新增 `save_expression_from_str()` + `evaluate_expression()` |
| `services/strategy_service/ml/label_engine.py` | 修复 label_dir NaN 处理 |
| `services/strategy_service/main.py` | 新增 `gp_save_single()` + `gp_evaluate()` + generate_labels 增强 |
| `services/api.py` | 新增 3 个 API 端点 (gp-save / gp-evaluate + 请求模型) |
| `web_ui/index.html` | GP 挖掘区域 UI 重构 + 评估卡片 |
| `web_ui/js/models.js` | 新增单个保存 + 评估交互逻辑 |
| `web_ui/js/research.js` | 标签生成结果展示截断信息 |
| `docs/api-reference.md` | 更新 GP 接口文档 |

### 2026-04-12 v0.5.5 — 完善后端测试脚本

- **Python 测试套件增强**：`scripts/p1_backend_smoke.py` 新增
  - `core / research / sector / full` 四种 profile
  - 断言校验
  - 汇总结果输出
  - `--output-json` 报告导出
- **Shell 脚本增强**：`scripts/p1_backend_smoke.sh` 已覆盖
  - universe
  - breadth
  - factors
  - backtest
  - sectors
  - logs
- **HTTP 请求集合**：新增 `docs/http/p1-backend.http`
- **文档更新**：`docs/backend-api-runbook.md` 已补充 profile 和 `.http` 用法

### 2026-04-12 v0.5.4 — 派生板块资产池

- **sector universe**：新增基于 `stocks.industry` 的板块资产派生能力
- **派生结果**：
  - `asset_universe` 中新增 `asset_type=sector`
  - `asset_mapping` 中新增 `belongs_to_sector`
- **新接口**：
  - `POST /api/v1/universe/sectors/rebuild`
  - `GET /api/v1/universe/sectors/constituents`
- **日志**：新增 `sector_universe_rebuild` 结构化任务日志
- **实测**：已成功派生 `110` 个 sector、`5500` 条 stock -> sector 映射

### 2026-04-12 v0.5.3 — 后端结构化任务日志

- **日志落库**：新增 `job_logs` 表，记录后端关键任务执行情况
- **日志范围扩展**：已覆盖
  - 股票列表同步
  - 单标的日线同步
  - 研究资产池初始化
  - 研究资产批量同步
  - 研究资产增量同步
  - 市场宽度重建
  - 调度器自动任务
- **日志接口**：新增 `GET /api/v1/logs/jobs`
- **文档更新**：`docs/backend-api-runbook.md`、`docs/api-reference.md` 已补充日志查询说明

### 2026-04-12 v0.5.2 — P1 后端自动化调度补齐

- **启动自动初始化**：`RESEARCH_UNIVERSE_BOOTSTRAP_ON_START=true` 时，服务启动自动写入内置研究资产池
- **指数 / ETF 增量同步调度**：新增工作日研究资产日更任务，默认 `18:05`
- **市场宽度日更调度**：新增工作日宽度特征重建任务，默认 `18:12`
- **配置项补齐**：新增研究资产同步与宽度重建相关 `.env` 配置
- **验证结果**：服务重启后自动初始化成功，API 冒烟脚本再次跑通

### 2026-04-12 v0.5.1 — P1 后端数据模块首批落地

- **研究资产池**：新增 `asset_universe`、`asset_mapping`、`asset_tags`
- **兼容视图**：新增 `asset_daily_quotes`、`asset_data_status`，先复用现有 `daily_quotes`
- **指数 / ETF 数据入库**：`POST /api/v1/data/update` 已支持指数和 ETF 日线拉取入库
- **批量接口**：新增
  - `POST /api/v1/universe/bootstrap`
  - `GET /api/v1/universe/assets`
  - `GET /api/v1/universe/statuses`
  - `GET /api/v1/universe/mappings`
  - `GET /api/v1/universe/tags`
  - `POST /api/v1/universe/sync`
- **市场宽度特征**：新增 `market_breadth_features`，并提供
  - `POST /api/v1/features/breadth/rebuild`
  - `GET /api/v1/features/breadth`
- **后端联调资产**：新增 `docs/backend-api-runbook.md`、`scripts/p1_backend_smoke.py`、`scripts/p1_backend_smoke.sh`

### 2026-04-12 v0.5.0 — 项目方向切换到指数 / ETF 择时 v2

- **目标收敛**：从通用量化平台收敛为“指数择时 / ETF择时研究系统”
- **后端模块抽象方向明确**：
  - 数据获取模块：资产池、行情抓取、特征原始表、调度
  - 量化研究模块：因子、特征工程、模型、信号、回测
- **执行顺序调整**：先做数据模块，再做研究模块
- **P1 数据策略明确**：
  - 市场宽度优先由现有股票日线数据自行派生
  - 估值 / 资金 / 宏观不作为 P1 刚性依赖
  - 指数 / ETF / 板块列表作为 P1 核心交付
- **文档更新**：`docs/plan.md` 已重写为 v2 版本，明确 P1~P4 路线图

### 2026-04-12 v0.4.3 — 中证 A500 自动拉取 + 数据同步

- **定时任务**：工作日 **18:20** 自动同步中证 A500（`000510.SH`）成分日线，按 `TUSHARE_MIN_INTERVAL_SEC`（默认 0.35s）限速请求
- **自选**：当前默认仅拉取数据，不自动加入自选；如需加入自选，通过 `add_watchlist=true` 显式开启
- **数据源**：优先 Tushare `index_weight`，失败时回退 `index_member`（需足够积分与权限）
- **配置**：`TUSHARE_MIN_INTERVAL_SEC`、`TUSHARE_A500_INDEX_CODE`、`A500_LOOKBACK_DAYS`、`A500_WATCHLIST_NOTE`、`A500_SYNC_ENABLED`
- **API**：`POST /api/v1/data/a500/sync`；**脚本**：`python scripts/sync_a500.py`（适合长时间跑，避免 HTTP 超时）

### 2026-04-12 v0.4.2 — 多周期K线 + ETF行情 + 图表滚动优化

- **多周期K线切换**：
  - 支持 五日/日K/周K/月K/季K/年K 六个周期
  - 客户端聚合日线数据为周/月/季/年 OHLCV 蜡烛
  - 五日模式只展示最近5个交易日
  - 切换时重新渲染图表，Tab 高亮同步
- **K线图滚动限制**：`rightOffset: 2` 防止向左滑动超出最新数据
- **行情页新增热门ETF板块**：
  - 新增 `/api/v1/market/etfs` API (腾讯财经数据源)
  - 展示9只热门ETF: 上证50/沪深300/中证500/创业板/中证1000/纳指/黄金/光伏/医药
  - 点击ETF进入详情页，复用指数K线API展示历史数据
  - 实时价格+涨跌幅显示 (红涨绿跌)
- **前端数据流优化**：`App.detailDailyRows` 统一存储ASC序日线数据供多周期复用

### 2026-04-12 v0.4.1 — 雪球 APP 级 UI 复刻

- **完全复刻雪球 APP 数据展示风格**：
  - 个股详情页：‹ 返回 + 股票名 / 代码+行业+日期 / 大号价格+涨跌 / 4×2 数据网格 (高/开/量/振幅 + 低/昨收/额/区间) / 图表周期 Tab / K线图 / 技术指标
  - 自选页 (原"关注"改名)：沪/深 市场标签 + 股票名+代码 / 最新价 / 涨跌幅彩色药丸
  - 行情页指数卡片：名称 + 大号价格 + 涨跌额+涨跌幅 (红涨绿跌)
  - 图表周期选择器 Tab (分时/五日/日K/周K/月K/季K/年K)
- **"关注"全面改名为"自选"**：Tab、按钮、Toast、空态文案统一更新
- **涨跌色数据标注**：高/低价根据与昨收对比显示红/绿色
- **页面结构**: 行情 / 自选 / 个股 / 有效策略 / 回测 / 交易 / 报告 (7页)

### 2026-04-12 v0.4.0 — 有效策略页面 + 专业级 UI 优化

- **移除分析页，新增有效策略页**：
  - 展示所有回测收益为正的策略组合
  - 按收益率排序，按策略+股票聚合
  - 点击策略卡片重新回测展示详细买卖记录
  - 个股详情页新增「全策略回测」按钮
- **UI 专业级优化** (参考 Tiger/同花顺/雪球 风格)：
  - 全新深色主题配色，更专业的视觉层次
  - 品牌标识升级 (渐变Logo + 精简标题)
  - 指数卡片涨跌色背景标注
  - 策略卡片设计 (指标概览 + 点击详情)
  - 更精细的字体层级和间距系统
  - 表格、按钮、输入框全面优化
  - 新增 section-header 组件统一页面区块

### 2026-04-12 v0.3.1 — 前端模块化重构 + 数据体验优化

- **前端代码模块化拆分**：
  - `index.html` 从 ~600 行缩减至 182 行 (纯 HTML 结构)
  - CSS 抽取至 `web_ui/css/main.css`
  - JS 拆分为 9 个模块: `core.js` / `stocks.js` / `detail.js` / `watchlist.js` / `strategy.js` / `backtest.js` / `trading.js` / `report.js` / `init.js`
  - 全局状态统一为 `App` 命名空间对象
- **个股数据智能加载**：数据库已有近期数据时直接展示，无需重新拉取；缺失数据后台静默补全
- **指数卡片可点击**：指数面板卡片点击后进入个股页面展示对应指数K线及行情数据
- **回测详情增强**：回测结果新增详细买卖记录表 (入场/出场日期、价格、盈亏%、持仓天数)
- **回测历史点击查看**：历史记录行可点击重新执行回测并展示详细结果
- **新增后端 API**:
  - `GET /api/v1/index/{code}/daily` — 指数历史K线数据 (腾讯财经)
  - `GET /api/v1/data/{symbol}/info` — 查询本地数据库数据状态

### 2026-04-11 v0.3.0 — 前端功能大升级

- **移除概览页**：去掉 Dashboard，行情页作为默认首页
- **行情页新增指数面板**：展示上证指数、深证成指、创业板指、沪深300、上证50、中证500 六大指数实时数据
- **个股 tab 常驻**：修复刷新后个股 tab 消失的问题，无选中时显示引导文案
- **分析页因子交互升级**：
  - 技术因子增加中文名称 (如 MACD 差离值、RSI-14 相对强弱)
  - 点击因子芯片展示对应走势图 (Line/Histogram)
  - 显示因子说明文字，解释含义与用法
  - 移除原有因子数据表格
- **回测页增强**：
  - 新增初始资金 (万元)、交易成本 (‰) 设置项
  - 回测完成后展示详细报告 (策略、区间、资金变化、年化波动、盈亏比、交易频率)
  - 回测历史新增资金列显示
- **关注列表功能** (v0.2.5): 添加/移除关注股票, 卡片式列表展示
- **新增后端 API**: `/api/v1/market/indices` 获取主要指数数据 (Tushare index_daily)
- **因子 API 增强**: `/api/v1/factors/{symbol}?full=true` 支持返回全量时序数据

---

## 模块完成度

### Core 基础层 (100%)

| 模块 | 文件 | 状态 | 说明 |
|---|---|---|---|
| 配置管理 | `core/config.py` | ✅ | Pydantic Settings, .env |
| 事件总线 | `core/event_bus.py` | ✅ | asyncio Queue, subscribe/publish |
| 数据库 | `core/db.py` | ✅ | SQLite + Schema (10张表, 含 watchlist) |

### M1: 数据接入与管理层 (100%)

| 模块 | 文件 | 状态 | 说明 |
|---|---|---|---|
| Tushare适配器 | `services/data_service/adapters/tushare_adapter.py` | ✅ | A股日线、股票列表、health_check |
| AKShare适配器 | `services/data_service/adapters/akshare_adapter.py` | ✅ | 备用数据源 |
| YFinance适配器 | `services/data_service/adapters/yfinance_adapter.py` | ✅ | US市场 (已禁用A股) |
| 数据验证 | `services/data_service/pipeline/validator.py` | ✅ | 质量评分 + 异常检测 |
| 数据清洗 | `services/data_service/pipeline/cleaner.py` | ✅ | 去重、补全、类型修正 |
| 数据服务 | `services/data_service/main.py` | ✅ | 链式数据源、upsert入库 |

### M2: 策略研究与回测引擎 (100%)

| 模块 | 文件 | 状态 | 说明 |
|---|---|---|---|
| 因子库 | `services/strategy_service/factor_mining/library.py` | ✅ | 13 技术因子 (MA/MACD/RSI/BB/MOM) |
| 回测引擎 | `services/strategy_service/backtester/engine.py` | ✅ | 向量化回测, Sharpe/MaxDD/WinRate |
| 策略服务 | `services/strategy_service/main.py` | ✅ | 3种策略 + 事件驱动因子计算 |
| **参数优化** | `services/strategy_service/optimizer/bayesian.py` | ✅ | **Optuna TPE 贝叶斯优化** |
| 策略管理 | `services/strategy_service/main.py` | ✅ | 注册、状态更新、回测历史 |

**策略列表:**
| ID | 名称 | 参数 |
|---|---|---|
| `ma_cross` | MA 均线交叉 | fast(2-30), slow(10-120) |
| `rsi_reversal` | RSI 超买超卖反转 | period(5-30), oversold(15-40), overbought(60-85) |
| `bollinger_breakout` | 布林通道突破 | period(10-40), num_std(1.5-3.0) |

### M3: 实时监控与告警系统 (100%)

| 模块 | 文件 | 状态 | 说明 |
|---|---|---|---|
| 监控服务 | `services/monitor_service/main.py` | ✅ | CPU/内存/磁盘, Telegram通知 |
| 定时调度 | `services/scheduler.py` | ✅ | APScheduler (数据/健康/报告/备份) |

### M4: 风控与组合管理 (100%)

| 模块 | 文件 | 状态 | 说明 |
|---|---|---|---|
| **风控引擎** | `services/risk_service/main.py` | ✅ | 仓位限制、回撤检测、集中度检查 |
| **风控API** | `services/api.py` | ✅ | /risk/check, /risk/thresholds |

**风控阈值:**
| 规则 | 阈值 | 说明 |
|---|---|---|
| 最大回撤 | 15% | 超过触发 critical 告警 |
| VaR 95% | 5% | 风险价值阈值 |
| 集中度限制 | 10% | 单只股票最大占比 |
| 单股上限 | 5% | 信号级别的单股限制 |

### M5: 可视化与报告 (100%)

| 模块 | 文件 | 状态 | 说明 |
|---|---|---|---|
| 日报生成 | `services/report_service/main.py` | ✅ | Markdown日报 + 回测报告 |
| Web前端 | `web_ui/index.html` + `css/` + `js/` | ✅ | **模块化架构**: HTML壳 + 9个JS模块 + 独立CSS |
| 指数数据 | `services/api.py` | ✅ | 6大主要指数实时数据 + 指数K线历史 + 9只热门ETF |
| 有效策略 | `web_ui/js/strategy.js` | ✅ | 正收益策略列表 + 回测详情查看 |

### M6: 模拟交易 (100%)

| 模块 | 文件 | 状态 | 说明 |
|---|---|---|---|
| **Paper Trading** | `services/paper_trading/main.py` | ✅ | 模拟账户、买卖下单、持仓管理、订单记录 |
| **交易API** | `services/api.py` | ✅ | 7个端点 (accounts CRUD, orders) |
| **事件联动** | 同上 | ✅ | 策略信号自动触发模拟下单 |

### API 服务入口 (100%)

| 模块 | 文件 | 状态 | 说明 |
|---|---|---|---|
| FastAPI服务 | `services/api.py` | ✅ | **30个** RESTful端点 |
| 入口文件 | `main.py` | ✅ | asyncio单命令启动 7个服务 |

---

## 前端页面 (7个)

| 页面 | 功能 | 状态 |
|---|---|---|
| 行情 Stocks (首页) | **指数面板**(涨跌色) + **热门ETF面板** + A股搜索列表 + 一键拉取/自选 | ✅ |
| 自选 Watchlist | 自选列表管理，雪球风格卡片 (沪/深标签+涨跌药丸) | ✅ |
| 个股 Detail | **雪球风格**: 4×2数据网格+**多周期K线**(5日/日/周/月/季/年)+技术指标+回测 | ✅ |
| **有效策略 Strategy** | **正收益策略列表** + 点击查看详细回测记录 | ✅ |
| 回测 Backtest | 3策略 + 资金/成本设置 + 回测详情 + 历史 | ✅ |
| 交易 Trading | 模拟账户总览 + 买卖下单 + 持仓/订单 | ✅ |
| 报告 Report | 一键生成日报 | ✅ |

---

## API 端点 (31个)

| 端点 | 方法 | 说明 |
|---|---|---|
| `/health` | GET | 系统健康检查 |
| `/metrics` | GET | 系统指标查询 |
| `/alerts` | GET | 告警列表 |
| `/api/v1/market/indices` | GET | **六大主要指数数据** |
| `/api/v1/market/etfs` | GET | **9只热门ETF实时数据** |
| `/api/v1/stocks` | GET | 股票列表 |
| `/api/v1/stocks/update` | POST | 同步股票列表 |
| `/api/v1/data/{symbol}/daily` | GET | 日线数据查询 |
| `/api/v1/data/update` | POST | 拉取日线数据 |
| `/api/v1/data/{symbol}/info` | GET | **查询本地数据状态** |
| `/api/v1/index/{code}/daily` | GET | **指数历史K线数据** |
| `/api/v1/factors/{symbol}` | GET | 技术因子计算 (支持 ?full=true) |
| `/api/v1/backtest` | POST | 策略回测 |
| `/api/v1/backtest/history` | GET | 回测历史记录 |
| `/api/v1/strategies` | GET | 策略列表 (含参数空间) |
| `/api/v1/strategies/register` | POST | 注册新策略 |
| `/api/v1/strategies/{id}/status` | PUT | 更新策略状态 |
| `/api/v1/optimize` | POST | **参数优化 (Optuna)** |
| `/api/v1/risk/check` | POST | **风控检查** |
| `/api/v1/risk/thresholds` | GET | 风控阈值配置 |
| `/api/v1/paper/accounts` | GET | 模拟账户列表 |
| `/api/v1/paper/accounts` | POST | 创建模拟账户 |
| `/api/v1/paper/accounts/{id}` | GET | 查看模拟账户 |
| `/api/v1/paper/accounts/{id}/reset` | POST | 重置模拟账户 |
| `/api/v1/paper/orders` | GET | 订单列表 |
| `/api/v1/paper/orders` | POST | **模拟下单** |
| `/api/v1/watchlist` | GET | 关注列表查询 |
| `/api/v1/watchlist` | POST | 添加关注 |
| `/api/v1/watchlist/{symbol}` | DELETE | 移除关注 |
| `/api/v1/reports/daily` | POST | 生成日报 |
| `/api/v1/events/channels` | GET | 事件通道列表 |

---

### v0.6.0 — P2 因子研究后端 + 数据汇总接口 (2026-04-12)

**新增数据汇总接口**

- `GET /api/v1/data/summary` — 一键查看全平台数据快照，覆盖 stocks、daily_quotes、asset_universe、market_breadth、factors、factor_values、factor_eval_results、strategies、backtest_results、watchlist、job_logs、alerts

**因子库升级 (FactorLibrary)**

- 从 5 组 13 个因子 → **5 大类 42+ 个因子**
- 新增趋势类: EMA(5/10/20/60)、ADX/+DI/-DI
- 新增动量类: ROC(5/10/20)、CCI、Williams %R、Stochastic %K/%D
- 新增波动率类: ATR、ATR%、Realized Vol(5/10/20)
- 新增成交量类: OBV、VWAP、Volume Ratio
- 新增价格形态类: Returns(1/5/10/20)、Log Return、HL Range、CO Range
- `GET /api/v1/factors/library/list` 查看全部可用因子

**因子批量计算与持久化**

- `POST /api/v1/factors/batch-compute` — 批量计算全部因子并持久化到 `factor_values` 表
- DB 新增 `factor_values` 表 (symbol + trade_date + factor_name → value)
- `GET /api/v1/factors/values/{symbol}` — 查询已持久化因子值

**因子评估框架 (FactorEvaluator)**

- `POST /api/v1/factors/evaluate` — 批量评估因子 IC / IC Std / ICIR / Rank IC / Rank ICIR / IC 正比例 / 单调性 / 分期 IC
- DB 新增 `factor_eval_results` 表，评估结果自动持久化
- `GET /api/v1/factors/eval-history` — 查询历史评估记录

**Walk-Forward 样本外验证 (WalkForwardValidator)**

- `POST /api/v1/factors/walk-forward` — 滚动窗口验证，输出每个 fold 的 train/test IC、收益、Sharpe、IC 一致性
- 支持自定义 train_days / test_days / step_days / forward_period / factor_names
- 单因子或全因子批量验证

**文件变更**

| 文件 | 变更 |
|---|---|
| `core/db.py` | 新增 `factor_values`、`factor_eval_results` 表及索引 |
| `services/strategy_service/factor_mining/library.py` | 因子库从 13 → 42+ |
| `services/strategy_service/factor_mining/evaluator.py` | **新文件** — 因子评估框架 |
| `services/strategy_service/factor_mining/walk_forward.py` | **新文件** — Walk-Forward 验证引擎 |
| `services/strategy_service/main.py` | 新增 batch_compute / evaluate / walk_forward / persist 方法 |
| `services/api.py` | 新增 8 个 P2 API 端点 + data summary 端点；修复路由优先级 |
| `docs/api-reference.md` | 更新 P2 接口文档 |
| `docs/http/p1-backend.http` | 扩展为完整 P1+P2 API 测试集 |

---

### v0.7.0 — P3 特征工程 + ML 模型 + P4 GP 挖掘 + Pipeline (2026-04-12)

**P3.1 标签工程 (LabelEngine)**

- 未来 N 日前向收益 (fwd_ret_5/10/20)
- 方向标签 (label_dir_5/10/20)：1=上涨 0=下跌
- 分桶标签 (label_bucket_5)：分位数分桶
- 波动率 regime 标签 (label_vol_regime)
- `POST /api/v1/ml/labels`

**P3.2 特征筛选 (FeatureSelector)**

- 三阶段 Pipeline：方差过滤 → 相关性去重 → IC 重要性排序
- `POST /api/v1/ml/feature-select`

**P3.3 ML 择时模型 (TimingModelTrainer)**

- Lasso（L1 正则 LogisticRegression）+ LightGBM 二分类
- 模型自动序列化到 `data/models/` (pkl + json 元数据)
- 训练/测试集 metrics: accuracy / precision / recall / F1 / AUC / log_loss
- 特征重要性排序
- `POST /api/v1/ml/train` / `GET /api/v1/ml/models` / `POST /api/v1/ml/predict`

**P3.4 模型 Walk-Forward (ModelWalkForward)**

- 滚动窗口训练→预测→评估
- 每个 fold 输出 accuracy / F1 / AUC / 收益 / Sharpe
- 累计收益 + 累计 Sharpe
- `POST /api/v1/ml/walk-forward`

**P4.1 GP 自动表达式挖掘 (GPMiner)**

- 基于 DEAP 的遗传编程引擎
- 原始运算: +, -, *, /, neg, abs, log, sqrt, max, min
- 适应度函数: Sharpe 或 IC
- Hall of Fame 保留 Top 10 表达式
- 支持指定数据区间和前瞻期
- 支持单个表达式保存 (`POST /api/v1/ml/gp-save`)
- 支持跨标的表达式评估 (`POST /api/v1/ml/gp-evaluate`)
  - 评估指标: Sharpe / 总收益 / 年化 / IC / 胜率 / 最大回撤 / 盈亏比
- `POST /api/v1/ml/gp-mine`

**P4.2 全流程 Research Pipeline**

- 一键端到端: 因子计算 → 标签工程 → 特征筛选 → ML 训练 → Walk-Forward → 最新信号
- `POST /api/v1/ml/pipeline`

**新增依赖**

- `lightgbm >= 4.6.0`
- `scikit-learn >= 1.8.0`
- `deap` (GP 遗传编程)

**文件变更**

| 文件 | 变更 |
|---|---|
| `services/strategy_service/ml/label_engine.py` | **新文件** — 标签工程 |
| `services/strategy_service/ml/feature_selector.py` | **新文件** — 特征筛选 |
| `services/strategy_service/ml/timing_model.py` | **新文件** — Lasso + LightGBM 训练/预测 |
| `services/strategy_service/ml/model_walk_forward.py` | **新文件** — 模型 Walk-Forward |
| `services/strategy_service/ml/gp_miner.py` | **新文件** — GP 表达式挖掘 |
| `services/strategy_service/ml/pipeline.py` | **新文件** — 一键研究 Pipeline |
| `services/strategy_service/main.py` | 新增 P3/P4 方法 |
| `services/api.py` | 新增 9 个 ML 端点 |
| `docs/api-reference.md` | 更新 P3/P4 接口文档 |
| `docs/http/p1-backend.http` | 扩展为完整 P1-P4 测试集 |

---

## 里程碑总结

| 阶段 | 状态 | 核心能力 |
|---|---|---|
| P1 数据获取模块 | ✅ 已完成 | 资产池 / 行情 / 市场宽度 / 板块派生 / 日志 |
| P2 因子研究后端 | ✅ 已完成 | 42+ 因子 / IC评估 / Walk-Forward / 持久化 |
| P3 特征工程+ML模型 | ✅ 已完成 | 标签 / 特征筛选 / Lasso+LightGBM / 模型WF |
| P4 自动挖掘+Pipeline | ✅ 已完成 | GP 表达式挖掘 / 一键Pipeline |

---

## 待办事项

### 后续优化方向

- [ ] 多标的批量 Pipeline 运行
- [ ] LSTM / Transformer 深度学习模型
- [ ] 实盘接入 (券商API)
- [ ] 模型定时自动再训练 (scheduler)
- [ ] 前端可视化: 因子评估仪表盘 / 模型对比 / 信号展示
