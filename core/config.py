from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # --- paths ---
    project_root: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    data_dir: Path = Field(default=Path("./data"), alias="QUANT_DATA_DIR")
    db_path: Path = Field(default=Path("./data/quant_platform.db"), alias="QUANT_DB_PATH")
    log_dir: Path = Field(default=Path("./logs"), alias="QUANT_LOG_DIR")
    backup_dir: Path = Field(default=Path("./backup"), alias="QUANT_BACKUP_DIR")

    # --- server ---
    api_port: int = Field(default=8000, alias="API_PORT")
    dashboard_port: int = Field(default=8501, alias="DASHBOARD_PORT")

    # --- data sources ---
    tushare_api_key: str = Field(default="", alias="TUSHARE_API_KEY")
    akshare_enabled: bool = Field(default=True, alias="AKSHARE_ENABLED")
    yfinance_rate_limit: int = Field(default=200, alias="YFINANCE_RATE_LIMIT")
    # Tushare 限速：两次请求最小间隔（秒）。约 0.35s ≈ 170 次/分钟，低于常见 200/分钟 上限
    tushare_min_interval_sec: float = Field(default=0.35, alias="TUSHARE_MIN_INTERVAL_SEC")
    # 中证 A500 指数代码（Tushare）
    tushare_a500_index_code: str = Field(default="000510.SH", alias="TUSHARE_A500_INDEX_CODE")
    # A500 日线拉取回溯自然日（覆盖约 250 个交易日）
    a500_lookback_days: int = Field(default=400, alias="A500_LOOKBACK_DAYS")
    # 自动加入自选时的备注
    a500_watchlist_note: str = Field(default="A500自动", alias="A500_WATCHLIST_NOTE")
    # 是否启用定时 A500 同步任务
    a500_sync_enabled: bool = Field(default=True, alias="A500_SYNC_ENABLED")
    # 启动时自动初始化研究资产池
    research_universe_bootstrap_on_start: bool = Field(default=True, alias="RESEARCH_UNIVERSE_BOOTSTRAP_ON_START")
    # 是否启用指数 / ETF 增量同步任务
    research_universe_sync_enabled: bool = Field(default=True, alias="RESEARCH_UNIVERSE_SYNC_ENABLED")
    # 指数 / ETF 增量同步时间
    research_universe_sync_hour: int = Field(default=18, alias="RESEARCH_UNIVERSE_SYNC_HOUR")
    research_universe_sync_minute: int = Field(default=5, alias="RESEARCH_UNIVERSE_SYNC_MINUTE")
    # 研究资产默认回补自然日范围
    research_sync_lookback_days: int = Field(default=400, alias="RESEARCH_SYNC_LOOKBACK_DAYS")
    # 增量同步时与最后交易日重叠的自然日范围
    research_sync_overlap_days: int = Field(default=5, alias="RESEARCH_SYNC_OVERLAP_DAYS")
    # 是否启用市场宽度日更
    market_breadth_sync_enabled: bool = Field(default=True, alias="MARKET_BREADTH_SYNC_ENABLED")
    # 市场宽度日更时间
    market_breadth_sync_hour: int = Field(default=18, alias="MARKET_BREADTH_SYNC_HOUR")
    market_breadth_sync_minute: int = Field(default=12, alias="MARKET_BREADTH_SYNC_MINUTE")
    # 市场宽度日更回算窗口
    market_breadth_lookback_days: int = Field(default=120, alias="MARKET_BREADTH_LOOKBACK_DAYS")

    # --- security ---
    jwt_secret_key: str = Field(default="change-me", alias="JWT_SECRET_KEY")
    encryption_key: str = Field(default="change-me", alias="ENCRYPTION_KEY")

    # --- notification ---
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_critical_chat: str = Field(default="", alias="TELEGRAM_CRITICAL_CHAT")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.log_dir, self.backup_dir,
                  self.data_dir / "market_data", self.data_dir / "models",
                  self.data_dir / "backtest", self.data_dir / "cache"):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
