# QuantAI Guardian

AI 驱动的本地量化分析平台，以 OpenClaw 为中央智能调度器。

## 快速启动

```bash
# 1. 创建虚拟环境
python3.11 -m venv venv && source venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 填入必要配置（如 TUSHARE_API_KEY）

# 4. 初始化数据库
python scripts/init_db.py

# 5. 启动平台
python main.py
```

## 服务端口

| 服务 | 地址 | 说明 |
|---|---|---|
| API Server | http://localhost:8000 | RESTful 接口 + OpenAPI 文档 (/docs) |
| Frontend | http://localhost:8000/ | 内置静态页面（当前后端联调优先使用 API） |

## 项目结构

```
quant-ai/
├── core/                  # 核心框架（事件总线、配置、数据库）
├── services/              # 业务服务模块
│   ├── data_service/      # 数据接入与管理
│   ├── strategy_service/  # 策略研发与回测
│   ├── monitor_service/   # 实时监控与预警
│   ├── risk_service/      # 风险控制
│   ├── report_service/    # 报告生成
│   └── api.py             # FastAPI 接口层
├── web_ui/                # Streamlit Dashboard
├── scripts/               # 运维脚本
├── config/                # 配置文件
├── data/                  # 本地数据存储
├── logs/                  # 日志
└── main.py                # 入口
```

## 技术文档

详见：

- [docs/technical-design.md](./docs/technical-design.md)
- [docs/api-reference.md](./docs/api-reference.md)
- [docs/backend-api-runbook.md](./docs/backend-api-runbook.md)
