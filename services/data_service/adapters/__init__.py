from .base import DataSource

__all__ = ["DataSource", "AKShareAdapter", "YFinanceAdapter"]


def __getattr__(name: str):
    if name == "AKShareAdapter":
        from .akshare_adapter import AKShareAdapter

        return AKShareAdapter
    if name == "YFinanceAdapter":
        from .yfinance_adapter import YFinanceAdapter

        return YFinanceAdapter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
