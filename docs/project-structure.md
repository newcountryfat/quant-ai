# QuantAI Guardian — 项目结构

```
quant-ai/
├── main.py                          # 入口：asyncio 启动所有服务
├── requirements.txt                 # Python 依赖
├── .env                             # 环境变量 (含 Tushare token)
├── .env.example                     # 环境变量模板
├── README.md                        # 快速开始指南
├── technical-design.md              # 技术设计文档 (完整版)
│
├── core/                            # 核心基础设施
│   ├── __init__.py
│   ├── config.py                    # Pydantic Settings 配置管理
│   ├── event_bus.py                 # asyncio 事件总线
│   └── db.py                        # SQLite 连接 + Schema 初始化
│
├── services/                        # 业务服务层
│   ├── __init__.py
│   ├── api.py                       # FastAPI 应用 (12个端点)
│   ├── scheduler.py                 # APScheduler 定时任务
│   │
│   ├── data_service/                # M1: 数据接入与管理
│   │   ├── main.py                  # DataService 入口
│   │   ├── a500_sync.py             # 中证 A500 限速拉取 + 自选
│   │   ├── adapters/
│   │   │   ├── base.py              # DataSource 抽象基类
│   │   │   ├── tushare_adapter.py   # Tushare Pro (A股首选)
│   │   │   ├── akshare_adapter.py   # AKShare (A股备选)
│   │   │   └── yfinance_adapter.py  # YFinance (US市场)
│   │   └── pipeline/
│   │       ├── validator.py         # 数据质量验证
│   │       └── cleaner.py           # 数据清洗
│   │
│   ├── strategy_service/            # M2: 策略研究与回测
│   │   ├── main.py                  # StrategyService 入口
│   │   ├── factor_mining/
│   │   │   └── library.py           # 13 技术因子 (MA/MACD/RSI/BB/MOM)
│   │   ├── backtester/
│   │   │   └── engine.py            # 向量化回测引擎
│   │   └── optimizer/
│   │       └── bayesian.py          # 参数优化 (待实现)
│   │
│   ├── monitor_service/             # M3: 监控与告警
│   │   └── main.py                  # 健康检查 + Telegram 通知
│   │
│   ├── risk_service/                # M4: 风控 (待实现)
│   │   └── main.py
│   │
│   ├── report_service/              # M5: 报告生成
│   │   └── main.py                  # Markdown 日报 + 回测报告
│   │
│   └── admin_service/               # M6: 系统管理 (待实现)
│       └── __init__.py
│
├── web_ui/                          # 前端 (单文件SPA)
│   └── index.html                   # 6 页面, 暗色主题, 移动端优先
│
├── scripts/                         # 工具脚本
│   ├── init_db.py                   # 数据库初始化
│   └── sync_a500.py                 # 中证 A500 全量同步（CLI）
│
├── docs/                            # 项目文档
│   ├── development-progress.md      # 开发进度跟踪
│   ├── api-reference.md             # API 参考文档
│   └── project-structure.md         # 本文件
│
├── data/                            # 运行时数据 (gitignore)
│   ├── quant_platform.db            # SQLite 数据库
│   ├── market_data/
│   ├── models/
│   ├── backtest/
│   ├── cache/
│   └── reports/                     # 生成的日报
│
├── logs/                            # 日志 (gitignore)
└── backup/                          # 数据库备份 (gitignore)
```

## 数据库表结构 (SQLite)

| 表名 | 用途 | 关键字段 |
|---|---|---|
| `stocks` | 股票基本信息 | symbol(PK), name, market, industry |
| `daily_quotes` | 日线行情 | symbol+trade_date(PK), OHLCV |
| `factors` | 因子数据 | symbol+trade_date+factor_name(PK), value |
| `strategies` | 策略注册 | strategy_id(PK), sharpe, max_dd, status |
| `backtest_results` | 回测记录 | strategy_id, total_return, sharpe |
| `alerts` | 告警记录 | level, source, message |
| `system_metrics` | 系统指标 | metric_name, value, tags_json |

## 数据源优先级

```
A股: Tushare Pro (首选) → AKShare (备选)
US股: YFinance (已禁用, 仅代码保留)
```
