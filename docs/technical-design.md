# QuantAI Guardian — 量化分析平台技术设计文档

> **版本**: v1.0.0  
> **日期**: 2026-04-11  
> **状态**: Draft  
> **适用对象**: 量化开发工程师、系统架构师、投资组合经理

---

## 目录

1. [项目概述](#1-项目概述)
2. [系统架构](#2-系统架构)
3. [核心功能模块设计](#3-核心功能模块设计)
4. [接口设计](#4-接口设计)
5. [数据源与数据管道](#5-数据源与数据管道)
6. [OpenClaw 智能调度层](#6-openclaw-智能调度层)
7. [技术选型](#7-技术选型)
8. [部署架构](#8-部署架构)
9. [安全与风控](#9-安全与风控)
10. [开发阶段规划与里程碑](#10-开发阶段规划与里程碑)

---

## 1. 项目概述

### 1.1 背景与目标

构建一个以 OpenClaw 为中央智能调度器的 **AI 驱动全自动量化平台 (QuantAI Guardian)**，覆盖数据采集、因子挖掘、策略回测、风险控制、可视化展示的完整闭环。

平台最终状态：OpenClaw 作为中央大脑自动完成以下工作——

- 自动更新多源股票数据（A股、港股、美股）
- 自动挖掘与验证量化因子
- 自动执行策略回测与参数优化
- 自动进行风险评估与预警
- 自动生成可视化报告并推送通知

### 1.2 关键用户角色

| 角色 | 关注点 | 典型操作 |
|---|---|---|
| 量化研究员 | 策略研发、因子构造、回测分析 | Jupyter 编码、策略配置、回测审查 |
| 投资经理 | 组合收益、风险敞口、策略表现 | Dashboard 监控、报告查阅 |
| 系统管理员 | 服务可用性、资源利用率、安全合规 | 运维监控、权限管理、备份恢复 |
| OpenClaw 自动化 Agent | 全流程自动调度与异常自愈 | 定时任务、事件触发、自动恢复 |

### 1.3 核心指标要求

| 指标 | 目标值 | 说明 |
|---|---|---|
| 系统可用性 | >= 99.95% | 7×24 小时运行 |
| 数据更新成功率 | >= 98.7% | 多源容灾 |
| 因子挖掘吞吐 | >= 15 factors/hour | GPU 加速 |
| 回测吞吐 | >= 50 strategies/day | 向量化引擎 |
| API P99 延迟 | < 200ms | 缓存+连接池 |
| 单策略最大回撤 | < 15% | 硬性风控红线 |

---

## 2. 系统架构

### 2.1 整体分层

平台采用 **"四层 + 微服务"** 云原生架构，将关注点清晰分离：

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    第一层：用户交互层 (User Interaction)                  │
│  Web 控制台 (React)  │  Jupyter Notebook  │  Open API (REST/SDK)       │
│  Telegram/飞书 Bot   │  移动端 PWA        │  CLI 工具                   │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────────┐
│              第二层：应用服务层 (Application Service)                     │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │              OpenClaw 中央控制器 (Central Controller)           │    │
│  │  任务调度引擎 │ 资源管理器 │ 异常自愈系统 │ 审计追踪 │ 安全沙箱  │    │
│  └───────────┬───────────────────────────────────────┬─────────────┘    │
│              ↓                                       ↓                  │
│  ┌────────────────────────┐       ┌────────────────────────────┐       │
│  │    数据自动化层         │       │    策略智能层               │       │
│  │  数据采集 Agent        │       │  因子挖掘 Agent            │       │
│  │  数据清洗验证 Agent    │       │  策略生成 Agent            │       │
│  │  数据质量监控 Agent    │       │  回测优化 Agent            │       │
│  │  数据版本控制 Agent    │       │  风险控制 Agent            │       │
│  └────────────────────────┘       └────────────────────────────┘       │
│                                                                         │
│  微服务: 数据服务 │ 策略服务 │ 监控服务 │ 报告服务 │ 风控服务            │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────────┐
│               第三层：本地数据管理层 (Local Data Management)              │
│  SQLite (关系数据)            │  Parquet + DuckDB (时序/分析)            │
│  JSONL 文件 (非结构化)        │  TTLCache (进程内存缓存)                 │
│  本地文件系统 (模型/报告)     │  LocalEventBus (事件总线)                │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────────┐
│               第四层：本地基础设施层 (Local Infrastructure)               │
│  asyncio (协程管理)  │  本地 GPU  │  Python logging  │  APScheduler     │
│  venv (环境隔离)     │  单进程    │  本地文件备份     │  健康检查脚本     │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 关键数据流

```
数据采集 → 本地事件总线 → 计算引擎 → 信号生成 → 风控拦截 → 执行服务 → 成交回报 → 监控系统
```

1. 数据采集 Agent 从多数据源（AKShare/Tushare/YFinance）拉取行情，通过本地事件总线广播
2. 计算引擎订阅事件，执行因子计算与策略信号生成
3. 风控服务对信号做实时拦截校验（仓位、回撤、相关性）
4. 通过校验的信号进入执行服务（模拟/实盘）
5. 成交回报写入本地 SQLite + Parquet，监控模块更新 Dashboard 和告警

### 2.3 可用性设计

| 策略 | 实现方式 |
|---|---|
| 数据源容灾 | 主备切换：AKShare (主) → Tushare (备) → YFinance (兜底) |
| 服务高可用 | asyncio 异常捕获自动重启任务，watchdog 文件监控 |
| 自动恢复 | OpenClaw AutoRecovery：最多重试 3 次，冷却 15 分钟 |
| 数据持久化 | SQLite WAL 模式 + 每日本地快照备份至 backup/ 目录 |
| 降级策略 | 数据质量 < 0.9 时跳过因子挖掘，保护下游 |

---

## 3. 核心功能模块设计

平台遵循 **高内聚、低耦合** 原则，划分为六大独立可部署的功能模块。

### 3.1 模块总览

| 编号 | 模块名称 | 主要职责 | 关键子功能 |
|---|---|---|---|
| M1 | 数据接入与管理层 | 多源金融数据获取、清洗、缓存与版本管理 | 行情/财务数据接入、数据质量校验、优先级切换 |
| M2 | 策略研发与回测引擎 | 提供策略编写、因子构造、历史回测环境 | Python SDK、事件驱动编程、参数优化 |
| M3 | 实时监控与预警系统 | 价格变动监控与阈值告警 | 自定义规则配置、多通道通知推送 |
| M4 | 风险控制与组合管理 | 账户/持仓/流速三级风控体系 | 最大仓位限制、止损止盈、敞口分析 |
| M5 | 可视化展示与报告生成 | Web 看板展示与自动化报表输出 | K线图、净值曲线、PDF/Excel 导出 |
| M6 | 系统管理与运维中心 | 平台配置、权限、日志、安全与健康检查 | 本地部署、API 密钥管理、备份恢复 |

### 3.2 M1 — 数据接入与管理层

#### 3.2.1 功能描述

为平台提供统一、高质量的金融数据基础。通过适配器模式对接多个数据源，内置数据清洗、异常检测与版本管理机制。

#### 3.2.2 子功能详细设计

| 子功能 | 描述 | 技术方案 |
|---|---|---|
| 多源数据接入 | 对接 AKShare、Tushare、YFinance 等 | 适配器模式，统一 DataSource 抽象接口 |
| 定时数据更新 | 每 4 小时自动拉取增量数据 | OpenClaw Skill 调度，Cron `0 */4 * * *` |
| 数据清洗验证 | 异常值检测、缺失填充、格式归一化 | Pandas Pipeline + 质量评分（阈值 0.95） |
| 数据版本管理 | 数据变更可追溯 | 数据快照 + 元数据写入 SQLite |
| 优先级自动切换 | 主源不可用时自动切换备源 | 健康检查 + 优先级权重配置 |

#### 3.2.3 核心类设计

```python
class DataSource(ABC):
    """数据源抽象基类"""
    @abstractmethod
    def fetch(self, symbol: str, period: str, start: datetime) -> pd.DataFrame: ...
    @abstractmethod
    def health_check(self) -> bool: ...

class DataSourceManager:
    """数据源管理器，负责优先级切换"""
    def __init__(self, sources: dict[str, DataSource]):
        self.sources = sources  # {'akshare': ..., 'tushare': ..., 'yfinance': ...}
        self.priority = ['akshare', 'tushare', 'yfinance']

    def select_primary(self) -> DataSource:
        for name in self.priority:
            if self.sources[name].health_check():
                return self.sources[name]
        raise AllSourcesUnavailableError()

class DataValidator:
    """数据质量校验器"""
    def validate(self, source_name: str, data: pd.DataFrame) -> ValidationReport:
        checks = [
            self._check_missing_values(data),
            self._check_outliers(data),
            self._check_timestamp_continuity(data),
            self._check_price_validity(data),
        ]
        quality_score = sum(c.score for c in checks) / len(checks)
        return ValidationReport(quality_score=quality_score, checks=checks)
```

### 3.3 M2 — 策略研发与回测引擎

#### 3.3.1 功能描述

提供从因子构造到策略回测的完整研发环境，支持手动策略编写和 AI 自动因子挖掘两种模式。

#### 3.3.2 子功能详细设计

| 子功能 | 描述 | 技术方案 |
|---|---|---|
| 因子构造 SDK | 技术面/基本面/情绪因子 API | Python SDK，内置 200+ 标准因子库 |
| AI 因子挖掘 | 遗传编程 + 神经网络自动发现因子 | GeneticProgramming (max_gen=50) + NeuralFactorMiner |
| 因子有效性验证 | IC/IR/最大回撤/换手率评估 | 因子筛选条件: IC>0.03, IR>0.5, MaxDD<0.2 |
| 向量化回测引擎 | 高性能历史回测 | NumPy 向量化计算，支持多周期 (1y/3y/5y/all) |
| 参数优化 | 贝叶斯优化 + 遗传算法 | BayesianOptimizer (max_trials=100) |
| 样本外验证 | 防止过拟合 | 训练/验证/测试三段式数据划分 |

#### 3.3.3 策略生命周期

```
创建 → 编码/配置 → 回测 → 参数优化 → 样本外验证 → 模拟盘 → 实盘 → 监控 → 迭代/退役
```

#### 3.3.4 部署标准

策略从回测进入模拟盘需满足以下硬性指标：

```python
DEPLOYMENT_THRESHOLDS = {
    'sharpe_ratio': 1.5,      # 夏普比率 >= 1.5
    'win_rate': 0.6,           # 胜率 >= 60%
    'max_drawdown': 0.25,      # 最大回撤 < 25%
    'profit_factor': 1.3,      # 盈亏比 >= 1.3
    'sample_trades': 100,      # 最少交易次数
}
```

### 3.4 M3 — 实时监控与预警系统

#### 3.4.1 功能描述

实时跟踪市场行情、策略运行状态与系统健康度，支持多通道阈值告警。

#### 3.4.2 告警规则体系

**Critical 告警**（立即通知 Telegram + Email）：

| 告警项 | 阈值 | 时间窗口 |
|---|---|---|
| 数据更新连续失败 | >= 3 次 | 1 小时 |
| 系统宕机 | >= 5 分钟 | 即时 |
| 任意策略最大回撤 | >= 30% | 即时 |
| CPU/内存/磁盘使用率 | 95% / 90% / 85% | 5 分钟 |

**Warning 告警**（邮件通知）：

| 告警项 | 阈值 | 说明 |
|---|---|---|
| 数据质量评分下降 | < 0.85 | 质量不足 |
| 因子 IR 变化 | 降幅 > 20% | 因子失效 |
| 策略间相关性 | > 0.8 且 >= 3 组 | 分散化不足 |

#### 3.4.3 通知通道配置

```yaml
notification_channels:
  telegram:
    bot_token: ${TELEGRAM_BOT_TOKEN}
    channels:
      critical: ${TELEGRAM_CRITICAL_CHAT}
      warning: ${TELEGRAM_WARNING_CHAT}
      report: ${TELEGRAM_REPORT_CHAT}
  email:
    smtp_server: smtp.gmail.com
    sender: quant-alerts@yourdomain.com
  webhook:
    url: https://hooks.yourcompany.com/quant
    headers:
      Authorization: Bearer ${WEBHOOK_TOKEN}
```

### 3.5 M4 — 风险控制与组合管理

#### 3.5.1 三级风控体系

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  第一级：账户  │ →  │  第二级：持仓  │ →  │  第三级：流速  │
│  总资金风控   │    │  个股/行业限制 │    │  下单频率控制  │
└──────────────┘    └──────────────┘    └──────────────┘
```

#### 3.5.2 风控红线参数

```python
RISK_THRESHOLDS = {
    'max_drawdown': 0.15,        # 15% 组合最大回撤
    'var_95': 0.05,              # 5% 95%VaR
    'concentration': 0.10,       # 单策略不超过总资本 10%
    'correlation_ceiling': 0.7,  # 策略间相关性上限 70%
    'turnover_annual': 2.0,      # 年化换手率上限 200%
    'single_stock_limit': 0.05,  # 单只股票不超过总资本 5%
    'sector_limit': 0.20,        # 单一行业不超过总资本 20%
}
```

#### 3.5.3 紧急熔断机制

当以下任一条件触发时，系统自动停止所有策略并发送 Critical 告警：

1. 单日亏损 >= 5% 总资本
2. 连续 3 个交易日净值创新低
3. 市场出现极端波动（指数涨跌幅 >= 7%）

### 3.6 M5 — 可视化展示与报告生成

#### 3.6.1 Web Dashboard 模块

| 页面 | 核心组件 | 刷新频率 |
|---|---|---|
| 总览页 | 总资产、当日收益、活跃策略数、系统健康度 | 5 秒 |
| 行情页 | K线图（MA/MACD/RSI/Bollinger）、热力图 | 实时 |
| 策略页 | 策略净值曲线、收益分布、参数配置 | 30 秒 |
| 风控页 | 回撤图、VaR 热力图、仓位饼图 | 1 分钟 |
| 因子页 | IC 时序图、因子衰减分析、因子相关矩阵 | 1 小时 |

#### 3.6.2 自动报告生成

```yaml
report_templates:
  daily_report:
    schedule: "0 20 * * 1-5"  # 每个交易日晚 8 点
    format: [pdf, html]
    sections: [market_summary, strategy_performance, risk_status, factor_update]
    distribution: [email, telegram_report_chat]

  weekly_report:
    schedule: "0 10 * * 6"  # 每周六上午 10 点
    format: [pdf, excel]
    sections: [weekly_pnl, drawdown_analysis, factor_decay, optimization_suggestions]

  strategy_analysis:
    trigger: "backtest_complete"
    format: [html]
    sections: [backtest_metrics, trade_log, equity_curve, risk_decomposition]
```

### 3.7 M6 — 系统管理与运维中心

#### 3.7.1 核心运维能力

| 能力 | 实现方式 |
|---|---|
| 进程管理 | Python asyncio 内部协程管理，异常自动重启 |
| 日志管理 | Python logging + RotatingFileHandler (按大小/日期轮转) |
| 指标监控 | 自研 `/metrics` 端点 + Streamlit Dashboard 内置展示 |
| API 密钥管理 | 本地 .env 文件 + Python `cryptography` 库加密存储 |
| 自动备份 | APScheduler 每日凌晨 2 点 SQLite 快照 + Parquet 备份至 backup/ |
| 健康检查 | OpenClaw System Monitor 每 5 分钟执行本地 health_check.py |

#### 3.7.2 权限模型

```
SuperAdmin → 全部权限
├── Admin → 系统配置、用户管理、策略审批
├── Researcher → 策略研发、回测、因子管理
├── Viewer → 只读查看 Dashboard 和报告
└── Bot (OpenClaw) → 自动化操作、数据更新、策略部署（受沙箱限制）
```

---

## 4. 接口设计

### 4.1 设计原则

- **标准化**: 所有请求与响应遵循统一 JSON Schema 格式
- **解耦性**: 模块间通信通过消息队列异步完成，避免阻塞与强依赖
- **可扩展**: 适配器模式 + 插件化契约，支持新模块无缝接入

### 4.2 数据接口 (Data API)

RESTful 风格设计，路径统一前缀 `/api/v1/data/`。

| 方法 | 路径 | 描述 | 请求参数 |
|---|---|---|---|
| GET | `/data/{symbol}/kline` | 获取 K 线数据 | period, start, end, source |
| GET | `/data/{symbol}/realtime` | 获取实时行情 | fields |
| GET | `/data/{symbol}/financial` | 获取财务数据 | report_type, year |
| GET | `/data/market/overview` | 市场概览 | market (A股/港股/美股) |
| POST | `/data/batch` | 批量数据查询 | symbols[], period, start, end |

**统一响应格式**:

```json
{
  "code": 200,
  "message": "success",
  "data": { ... },
  "meta": {
    "source": "akshare",
    "quality_score": 0.97,
    "cached": true,
    "timestamp": "2026-04-11T20:30:00+08:00"
  }
}
```

### 4.3 策略接口 (Strategy API)

基于 `@openclaw.skill` 装饰器定义技能契约。

| 方法 | 路径 | 描述 |
|---|---|---|
| POST | `/strategy/register` | 注册新策略 |
| GET | `/strategy/{id}` | 获取策略详情 |
| PUT | `/strategy/{id}/start` | 启动策略 |
| PUT | `/strategy/{id}/stop` | 停止策略 |
| PATCH | `/strategy/{id}/params` | 更新策略参数 |
| POST | `/strategy/{id}/backtest` | 执行回测 |
| GET | `/strategy/{id}/performance` | 获取策略绩效 |

### 4.4 通信接口 (Communication API)

| 场景 | 协议 | 说明 |
|---|---|---|
| 模块间异步通信 | Python asyncio.Queue / multiprocessing.Queue | 本地进程间事件传递，零外部依赖 |
| 模块间同步调用 | 本地函数调用 / HTTP (localhost) | 同一进程直接调用，跨进程走 localhost REST |
| 对外通知 | SMTP / Telegram Bot API (httpx) | 告警推送、报告分发 |
| 前端实时数据 | SSE (Server-Sent Events) | Streamlit/Dash 原生支持，轻量级单向推送 |

### 4.5 本地事件通道设计

采用 Python 内置的事件总线模式替代 Kafka，通过 `asyncio.Queue` 实现进程内事件分发：

| 通道名称 | 生产者 | 消费者 | 说明 |
|---|---|---|---|
| `market.data.update` | 数据采集 Agent | 计算引擎、监控服务 | 行情更新事件 |
| `factor.mining.result` | 因子挖掘 Agent | 回测引擎 | 因子发现通知 |
| `strategy.signal` | 策略服务 | 风控服务 | 交易信号 |
| `risk.alert` | 风控服务 | 监控服务、通知服务 | 风控告警 |
| `system.health` | 所有模块 | 监控中心 | 健康心跳 |

```python
class LocalEventBus:
    """本地事件总线，基于 asyncio.Queue 实现发布/订阅"""
    def __init__(self):
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)

    def subscribe(self, channel: str) -> asyncio.Queue:
        queue = asyncio.Queue(maxsize=1000)
        self._subscribers[channel].append(queue)
        return queue

    async def publish(self, channel: str, event: dict):
        for queue in self._subscribers[channel]:
            await queue.put(event)
```

---

## 5. 数据源与数据管道

### 5.1 数据源选型

#### 免费数据源（基础研究）

| 数据源 | 覆盖范围 | 数据类型 | 特点 |
|---|---|---|---|
| **AKShare** (主源) | A股、港股、美股、期货、基金 | 行情、财务、估值(PE/PB)、龙虎榜 | 完全免费无门槛，社区活跃 |
| **Tushare** (备源) | 主打 A 股，部分港美股 | 日线/分钟行情、财报、资金流向 | 基础版免费，高级需积分 |
| **Baostock** | A 股、指数、基金 | 历史 K 线、基本面 | 完全免费，数据质量稳定 |
| **YFinance** (兜底) | 全球市场 | 日线行情、基本面 | 国际化覆盖好 |

#### 付费数据源（生产环境可选）

| 数据源 | 价格范围 | 适用场景 |
|---|---|---|
| Wind (万得) | 数万元/年 | 机构级全市场数据 |
| Choice (东方财富) | 1-3 万元/年 | 中型团队，Python SDK |
| 聚宽 (JoinQuant) | 2000-5000 元/年 | 量化研发一体化 |
| iTick | 基础免费，高级付费 | 多市场实时行情 |

### 5.2 数据管道架构

```
┌────────────┐   ┌───────────┐   ┌────────────┐   ┌────────────────────┐
│  多数据源   │ → │ 适配器层   │ → │ 清洗/验证  │ → │  本地存储引擎       │
│ AKShare    │   │ Adapter   │   │ Pipeline   │   │ SQLite (结构化)    │
│ Tushare    │   │ Pattern   │   │ Validator  │   │ Parquet (时序)     │
│ YFinance   │   │           │   │ Normalizer │   │ TTLCache (热点)    │
└────────────┘   └───────────┘   └────────────┘   └────────────────────┘
                                        │
                                        ↓
                               ┌──────────────────┐
                               │ 本地事件总线       │
                               │ LocalEventBus    │
                               │ channel:          │
                               │ market.data.update│
                               └──────────────────┘
```

### 5.3 数据存储策略（全本地化）

| 数据类型 | 存储方式 | 保留策略 | 说明 |
|---|---|---|---|
| 分钟/Tick 行情 | Parquet 文件 (按日期分区) | 全量本地存储，超 3 年压缩归档 | DuckDB 原生高效查询 |
| 日线行情 | SQLite 数据库 | 全量保留 | 结构化，支持 SQL 关联查询 |
| 财务报表 | SQLite 数据库 | 全量保留 | 按季度/年度入库 |
| 非结构化事件 | JSON Lines 文件 (.jsonl) | 最近 1 年 | 公告、新闻、舆情，按月归档 |
| 热点缓存 | Python TTLCache (内存) | TTL 5 分钟 ~ 1 小时 | 实时报价、常用因子值 |
| 历史回测结果 | 本地 Parquet / CSV 文件 | 永久保留 | data/backtest/ 目录 |
| 模型权重 | 本地文件 (.pt / .pkl) | 保留最近 10 个版本 | data/models/ 目录 |

---

## 6. OpenClaw 智能调度层

### 6.1 Skills 配置

OpenClaw 通过 Skill 机制管理所有自动化任务，每个 Skill 定义独立的调度规则和执行逻辑。

```yaml
# ~/.openclaw/skills/quant-platform.yaml
skills:
  - name: data-auto-updater
    description: 自动更新股票数据，支持多数据源
    schedule: "0 */4 * * *"
    parameters:
      data_sources: [akshare, tushare, yfinance]
      markets: [A股, 港股, 美股]
      data_types: [daily, minute, tick, financial]
    handler: python /app/data_updater/main.py

  - name: factor-mining-engine
    description: 自动挖掘和验证量化因子
    trigger: data-updated
    parameters:
      factor_types: [technical, fundamental, sentiment, macro]
      mining_methods: [genetic_programming, neural_network, statistical]
      validation_metrics: [ic, ir, max_drawdown]
    handler: python /app/factor_mining/engine.py

  - name: auto-backtester
    description: 自动策略回测和优化
    dependencies: [factor-mining-engine]
    parameters:
      backtest_periods: [1y, 3y, 5y, all]
      optimization_methods: [grid_search, bayesian, genetic]
      risk_constraints:
        max_drawdown: 0.25
        sharpe_ratio: 1.0
    handler: python /app/backtester/automatic.py

  - name: strategy-deployer
    description: 自动部署通过验证的策略到模拟/实盘
    trigger: backtest-success
    parameters:
      approval_threshold:
        sharpe_ratio: 1.5
        win_rate: 0.6
      deployment_modes: [paper_trading, real_money]
      position_sizing: risk_parity
    handler: python /app/deployer/strategy_deployer.py

  - name: system-monitor
    description: 监控系统健康状态和性能
    schedule: "*/5 * * * *"
    alert_channels: [telegram, email, webhook]
    handler: python /app/monitoring/health_check.py
```

### 6.2 任务编排与依赖

```
data-auto-updater (定时 4h)
        │
        ↓ [trigger: data-updated]
factor-mining-engine
        │
        ↓ [dependency]
auto-backtester
        │
        ↓ [trigger: backtest-success, 满足部署阈值]
strategy-deployer (先 paper_trading → 通过后 real_money)
```

### 6.3 自动恢复机制

```yaml
auto_recovery:
  max_restart_attempts: 3
  cooldown_minutes: 15
  fallback_strategies:
    - use_backup_data        # 切换备用数据源
    - reduce_computation     # 降低计算负载
    - notify_and_pause       # 通知管理员并暂停
  escalation:
    - level_1: auto_restart  # 自动重启
    - level_2: manual_alert  # 告警人工介入
    - level_3: emergency_stop # 紧急停机
```

### 6.4 OpenClaw 身份与工作空间配置

平台在 OpenClaw 工作空间中配置以下身份文件，定义 AI Agent 的行为边界：

| 文件 | 用途 |
|---|---|
| `IDENTITY.md` | 定义系统专业身份（QuantAI Guardian 量化策略执行官） |
| `SOUL.md` | 定义核心价值观与行为准则（专业严谨、透明责任、风险敬畏、持续进化、人文关怀） |
| `MISSION.md` | 定义量化投资使命与量化目标 (2026-2030) |
| `VALUES.md` | 定义红线行为与决策优先级框架 |

**决策优先级框架**（当面临冲突时按以下顺序决策）：

1. **合规安全** — 首要确保符合法律法规
2. **风险控制** — 防止重大损失优先于追求收益
3. **客户利益** — 客户最佳利益优先于平台利润
4. **性能优化** — 在前三项基础上追求收益优化
5. **技术创新** — 不以牺牲前四项为代价

---

## 7. 技术选型

> **设计原则**: 除 AI 管理器 (OpenClaw) 外，所有组件均采用**本地化实现**，零外部云服务依赖，单机即可完整运行。

### 7.1 后端技术栈

| 组件 | 技术 | 版本 | 选型理由 |
|---|---|---|---|
| 核心语言 | Python | 3.11+ | 量化生态最丰富 |
| Web 框架 | FastAPI | 0.100+ | 高性能异步、自动 OpenAPI 文档 |
| 任务调度 | APScheduler | 3.10+ | 纯 Python 本地调度器，无外部依赖，支持 Cron/Interval/Date 触发 |
| 进程间通信 | Python multiprocessing + asyncio.Queue | 内置 | 零依赖的本地消息传递，满足单机吞吐需求 |
| 数据处理 | Pandas + NumPy | 2.x / 1.26+ | 向量化计算、金融数据处理 |
| 分析引擎 | DuckDB | 1.x | 嵌入式 OLAP 引擎，本地文件即数据库，SQL 查询 Parquet/CSV |
| ML 框架 | PyTorch / scikit-learn | 2.x / 1.4+ | 本地 GPU/CPU 训练，因子挖掘 + 传统 ML |
| 回测引擎 | 自研 VectorizedBacktester | — | NumPy 向量化，纯 Python 实现 |
| 优化算法 | Optuna / DEAP | 3.x / 1.4 | 本地贝叶斯优化 + 遗传编程 |

### 7.2 前端技术栈

| 组件 | 技术 | 选型理由 |
|---|---|---|
| 框架 | Streamlit / Dash | 纯 Python 构建 Web Dashboard，无需前端工程链 |
| 图表库 | Plotly + Lightweight Charts (嵌入) | 交互式金融图表，本地渲染 |
| 备选方案 | Panel + HoloViews | Jupyter 生态，适合量化研究员 |

> 选择 Streamlit/Dash 而非 React 的理由：量化平台用户以研究员为主，Python 全栈更易维护，无需 Node.js 构建链。如后续需要更复杂交互，可升级为 React + Ant Design。

### 7.3 数据存储（全本地化）

| 组件 | 技术 | 选型理由 |
|---|---|---|
| 关系数据库 | SQLite 3 | 嵌入式零配置，单文件即数据库，适合中等规模金融数据 |
| 时序存储 | Parquet 文件 + DuckDB | 本地列式存储，DuckDB 原生高效查询 Parquet，无需独立数据库进程 |
| 缓存层 | Python `cachetools` (TTLCache / LRUCache) | 进程内存缓存，热点数据 TTL 管理，零外部依赖 |
| 文件存储 | 本地文件系统 (data/ 目录) | 回测结果、报告文件、模型权重直接写本地磁盘 |
| 日志 | Python `logging` + `RotatingFileHandler` | 标准库实现，按大小/日期自动轮转，无需 ELK |

### 7.4 基础设施（全本地化）

| 组件 | 技术 | 选型理由 |
|---|---|---|
| 进程管理 | Python asyncio 协程 + 子进程 | 单 main.py 入口，内部协程调度，无额外进程管理工具 |
| 监控 | 自研 `/metrics` 端点 + Streamlit Dashboard | FastAPI 内置 metrics 采集，Dashboard 页面直接展示 |
| 健康检查 | Python 内置 health_check.py | 定时检查各组件状态，异常写日志并触发通知 |
| AI 管理器 | OpenClaw 2026.4.x | 中央智能调度（唯一外部依赖） |

### 7.5 本地化架构优势

| 优势 | 说明 |
|---|---|
| 零成本启动 | 无需购买云服务或商业数据库许可证 |
| 部署极简 | `pip install -r requirements.txt && python main.py` 即可启动 |
| 数据安全 | 所有数据存储在本地磁盘，不经过任何外部服务 |
| 离线可用 | 除数据拉取外，所有分析、回测、可视化可完全离线运行 |
| 易于调试 | 单进程/少量进程，直接 pdb 断点调试 |

---

## 8. 部署架构

### 8.1 项目目录结构

```
quant-ai-guardian/
├── core/                        # 核心框架
│   ├── event_bus.py             # LocalEventBus 本地事件总线
│   ├── config.py                # 配置加载 (.env)
│   └── db.py                    # SQLite / DuckDB 连接管理
├── config/
│   ├── system/                  # 系统级配置
│   │   ├── identity_config.json
│   │   ├── system_config.json
│   │   └── security_config.json
│   ├── workspace/               # OpenClaw 工作空间
│   │   └── quant-platform/
│   │       ├── IDENTITY.md
│   │       ├── SOUL.md
│   │       ├── MISSION.md
│   │       └── VALUES.md
│   └── skills/                  # AI 技能配置
│       ├── skills_config.yaml
│       └── notification_config.json
├── services/
│   ├── data_service/            # M1: 数据接入与管理
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── adapters/            # 数据源适配器
│   │   ├── pipeline/            # 清洗管道
│   │   └── tests/
│   ├── strategy_service/        # M2: 策略研发与回测
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── factor_mining/       # 因子挖掘
│   │   ├── backtester/          # 回测引擎
│   │   ├── optimizer/           # 参数优化
│   │   └── tests/
│   ├── monitor_service/         # M3: 实时监控与预警
│   ├── risk_service/            # M4: 风险控制
│   ├── report_service/          # M5: 报告生成
│   ├── admin_service/           # M6: 系统管理
│   └── scheduler.py             # APScheduler 调度入口
├── web_ui/                      # Streamlit Dashboard
│   ├── dashboard.py             # 主入口
│   ├── pages/                   # 多页面: 行情/策略/风控/因子
│   └── components/              # 自定义 Streamlit 组件
├── scripts/                     # 运维脚本
│   ├── deploy.sh
│   ├── backup.sh
│   └── health_check.py
├── templates/                   # 报告模板
├── data/                        # 数据挂载卷
├── .env                         # 环境变量
├── requirements.txt
└── README.md
```

### 8.2 启动方式

采用 **直接 Python 启动**，单命令即可运行完整平台。

#### 环境准备

```bash
# 1. 创建虚拟环境
python3.11 -m venv venv
source venv/bin/activate        # Linux/macOS
# venv\Scripts\activate         # Windows

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 TUSHARE_API_KEY 等必要配置
```

#### 启动服务

```bash
# 初始化数据库（仅首次运行）
python scripts/init_db.py

# 启动全部服务（单进程，内部多线程/协程）
python main.py
```

#### 服务端口

| 服务 | 端口 | 说明 |
|---|---|---|
| API Server (FastAPI) | http://localhost:8000 | RESTful 接口 + OpenAPI 文档 (/docs) |
| Dashboard (Streamlit) | http://localhost:8501 | 可视化看板 |
| OpenClaw UI | http://localhost:18789 | AI 管理控制台 |

#### main.py 入口设计

```python
import asyncio
from services.data_service import DataService
from services.strategy_service import StrategyService
from services.monitor_service import MonitorService
from services.risk_service import RiskService
from services.report_service import ReportService
from services.scheduler import SchedulerService
from core.event_bus import LocalEventBus
from web_ui.server import start_dashboard

async def main():
    event_bus = LocalEventBus()

    services = [
        DataService(event_bus),
        StrategyService(event_bus),
        MonitorService(event_bus),
        RiskService(event_bus),
        ReportService(event_bus),
        SchedulerService(event_bus),
    ]

    for svc in services:
        await svc.start()

    # 启动 API Server (FastAPI + uvicorn)
    api_task = asyncio.create_task(start_api_server())
    # 启动 Dashboard (Streamlit subprocess)
    dashboard_task = asyncio.create_task(start_dashboard())

    await asyncio.gather(api_task, dashboard_task)

if __name__ == "__main__":
    asyncio.run(main())
```

### 8.3 硬件要求

| 环境 | CPU | 内存 | 存储 | GPU | 说明 |
|---|---|---|---|---|---|
| 个人学习 | 2 核 | 8 GB | 100 GB SSD | 无 | 笔记本即可运行 |
| 开发/测试 | 4 核 | 16 GB | 500 GB SSD | 无 | 本地 Python 直接启动 |
| 生产 (最低) | 8 核 | 32 GB | 1 TB SSD | 无 | 满足日常量化需求 |
| 生产 (推荐) | 16 核 | 64 GB | 2 TB NVMe | 本地 GPU (可选) | 支持 AI 因子挖掘 |

---

## 9. 安全与风控

### 9.1 安全策略

| 维度 | 措施 |
|---|---|
| 网络隔离 | 默认监听 localhost，仅需外部访问时开放 |
| API 认证 | JWT Token + API Key 双重认证 (PyJWT 本地签发) |
| 密钥管理 | .env 文件 + Python `cryptography` 库 Fernet 加密 |
| 数据安全 | 所有数据存储本地磁盘，不经过外部服务，文件权限 600 |
| 审计日志 | Python logging 写入本地审计日志文件，保留 7 年 |
| 沙箱执行 | OpenClaw Agent 运行于隔离环境，操作需经风控校验 |

### 9.2 合规要求

- 严格遵守证券监管要求（证监会、SEC 等）
- GDPR 数据保护合规
- 完整审计追踪，所有 AI 决策可解释、可追溯

---

## 10. 开发阶段规划与里程碑

### 10.1 阶段规划

采用 **统一过程 (UP) 生命周期模型**，划分为四个阶段：

| 阶段 | 目标 | 主要任务 | 周期 |
|---|---|---|---|
| 初始阶段 | 明确愿景与范围 | 需求调研、干系人确认、可行性分析 | 第 1-2 周 |
| 精化阶段 | 建立稳定架构基线 | 需求规格说明书、系统设计、原型验证 | 第 3-5 周 |
| 构建阶段 | 完成功能开发 | 模块并行开发、持续集成、联调测试 | 第 6-9 周 |
| 移交阶段 | 用户验收交付 | 生产部署、UAT 测试、培训移交 | 第 10 周 |

### 10.2 渐进式部署计划

```
第一阶段 (第 1-2 周): 数据自动化
  → 部署 data-auto-updater + system-monitor
  → 验证: 数据每 4 小时自动更新，质量评分 >= 0.95

第二阶段 (第 3-5 周): 因子挖掘 + 回测
  → 部署 factor-mining-engine + auto-backtester (dry-run)
  → 验证: 因子 IC > 0.03, 回测 Sharpe > 1.0

第三阶段 (第 6-8 周): 可视化 + 风控
  → 部署 Web Dashboard + 风控服务
  → 验证: Dashboard 实时刷新，风控规则生效

第四阶段 (第 9-10 周): 策略部署 + 全链路
  → 部署 strategy-deployer (paper_trading 模式)
  → 验证: 端到端流程自动运行，OpenClaw 自主管理
```

### 10.3 里程碑节点

| 里程碑 | 交付物 | 验收标准 | 责任人 |
|---|---|---|---|
| M0: 项目启动 | 《项目章程》签字版 | 三方共识达成 | 项目经理 |
| M1: 架构评审通过 | 《系统架构说明书》《数据库设计文档》 | 技术委员会评审通过 | CTO / 架构师 |
| M2: 数据层上线 | 数据采集 + 清洗 + 存储 | 数据更新成功率 >= 98%，延迟 < 30s | 数据组 |
| M3: 核心模块完成 | Git Tag 可交付代码包 | 单元测试覆盖率 >= 90%，无 Critical Bug | 各模块负责人 |
| M4: 系统测试通过 | 《系统测试报告》《缺陷清单》 | 所有 Critical 缺陷修复 | 测试经理 |
| M5: UAT 验收 | 《UAT 签字确认单》 | 业务方代表确认满足需求 | 客户代表 |
| M6: 正式上线 | 《上线监控报告》(72h 无重大故障) | 连续稳定运行，告警正常 | 运维主管 |

> 若任一里程碑延迟超过 2 个工作日，需触发 **"里程碑延迟分析会"** 机制。

### 10.4 成本优化策略

| 维度 | 策略 | 预期效果 |
|---|---|---|
| 计算资源 | Spot 实例运行回测任务 | 节省 60-70% |
| 数据采购 | AKShare + Tushare 组合覆盖 90% 需求 | 基础研究零成本 |
| 存储优化 | 冷热数据分离，历史数据自动归档至对象存储 | 存储成本降低 50% |
| GPU 使用 | 按需申请，非高峰期释放 | 避免空跑浪费 |

---

## 附录

### A. 环境变量清单

```bash
# 数据源
TUSHARE_API_KEY=<your_key>
AKSHARE_ENABLED=true
YFINANCE_RATE_LIMIT=200

# 本地存储路径
QUANT_DATA_DIR=./data
QUANT_DB_PATH=./data/quant_platform.db
QUANT_LOG_DIR=./logs
QUANT_BACKUP_DIR=./backup

# OpenClaw
OC_AUTO_MANAGEMENT=true
OC_AUTO_RECOVERY_ENABLED=true

# 通知
TELEGRAM_BOT_TOKEN=<your_token>
TELEGRAM_CRITICAL_CHAT=<chat_id>
TELEGRAM_WARNING_CHAT=<chat_id>
TELEGRAM_REPORT_CHAT=<chat_id>

# 安全
JWT_SECRET_KEY=<generated>
ENCRYPTION_KEY=<generated>
```

### B. 核心 Python 依赖

```txt
# requirements.txt
# Web & API
fastapi>=0.100.0
uvicorn>=0.23.0
streamlit>=1.30.0

# 数据获取
akshare>=1.12.0
tushare>=1.4.0
yfinance>=0.2.30

# 数据处理与存储
pandas>=2.0.0
numpy>=1.26.0
duckdb>=1.0.0
pyarrow>=14.0.0
cachetools>=5.3.0

# ML & 优化
torch>=2.0.0
scikit-learn>=1.4.0
optuna>=3.0.0
deap>=1.4.0

# 调度 & 通信
apscheduler>=3.10.0
httpx>=0.25.0

# 安全
pyjwt>=2.8.0
cryptography>=41.0.0

# 可视化
plotly>=5.18.0

# 工具
python-dotenv>=1.0.0
loguru>=0.7.0
```

### C. 参考文档

- OpenClaw 官方文档: https://openclaw.dev/docs
- AKShare 文档: https://akshare.akfamily.xyz
- Tushare 文档: https://tushare.pro
- DuckDB 文档: https://duckdb.org/docs
- Streamlit 文档: https://docs.streamlit.io
- APScheduler 文档: https://apscheduler.readthedocs.io
