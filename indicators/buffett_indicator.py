"""
Buffett Indicator (证券化率) = A-share total market cap / China GDP.

Tracks the ratio daily. GDP is linearly extrapolated when full-year data
is not yet available (see data_sources/gdp.py for logic).
"""

import logging
from datetime import date

import pandas as pd

from core.base_indicator import BaseIndicator
from core.excel_writer import save_excel
from data_sources.market_cap import fetch_total_market_cap, last_trading_day
from data_sources.gdp import GDPData

logger = logging.getLogger(__name__)


class BuffettIndicator(BaseIndicator):
    """巴菲特证券化率指标."""

    @property
    def name(self) -> str:
        return "A股证券化率"

    @property
    def html_filename(self) -> str:
        return "证券化率.html"

    @property
    def value_col(self) -> str:
        return "证券化率(%)"

    @property
    def columns(self) -> list[str]:
        return ["日期", "A股总市值(万亿)", "GDP(万亿)", "GDP来源", "证券化率(%)", "类型"]

    def resolve_target_date(self, target_date: date) -> date | None:
        """周末/节假日没有当日行情，对齐到最近交易日。"""
        trading_day = last_trading_day(target_date)
        if trading_day is None:
            logger.warning(f"{target_date} 取不到指数日线，无法确定交易日")
        return trading_day

    def compute(self, target_date: date) -> dict | None:
        """
        Compute one day's Buffett Indicator.
        Returns None if market cap fetch fails (e.g., non-trading day).
        """
        # 1. Fetch A-share total market cap (supports historical dates via index-scaling)
        try:
            mcap = fetch_total_market_cap(target_date)
        except RuntimeError as e:
            logger.error(f"Market cap fetch failed: {e}")
            return None

        # 2. Fetch / extrapolate GDP
        gdp_data = GDPData().load()
        gdp, gdp_source = gdp_data.get_extrapolated_gdp(target_date)

        # 3. Compute ratio
        ratio = round(mcap / gdp * 100, 2) if gdp > 0 else 0.0

        logger.info(
            f"{target_date} | 总市值={mcap:.2f}万亿 | "
            f"GDP={gdp:.2f}万亿({gdp_source}) | 证券化率={ratio:.2f}%"
        )

        return {
            "日期": target_date,
            "A股总市值(万亿)": mcap,
            "GDP(万亿)": gdp,
            "GDP来源": gdp_source,
            "证券化率(%)": ratio,
            "类型": "",
        }

    def recompute_gdp(self) -> int:
        """
        用当前 GDP 数据重算所有历史行的 GDP 与证券化率（市值列不动）。

        用于 GDP 源修正后刷新历史口径，返回数值发生变化的行数。
        """
        df = self.load_history()
        if df.empty:
            logger.warning(f"{self.name}: 没有历史数据可重算")
            return 0

        gdp_data = GDPData().load()
        changed = 0
        for idx, row in df.iterrows():
            mcap = row.get("A股总市值(万亿)")
            if pd.isna(mcap) or not mcap:
                continue
            gdp, source = gdp_data.get_extrapolated_gdp(row[self.date_col])
            ratio = round(float(mcap) / gdp * 100, 2) if gdp > 0 else 0.0
            old_gdp = row.get("GDP(万亿)")
            old_ratio = row.get(self.value_col)
            if (
                pd.isna(old_gdp) or abs(float(old_gdp) - gdp) > 0.005
                or pd.isna(old_ratio) or abs(float(old_ratio) - ratio) > 0.005
            ):
                changed += 1
            df.at[idx, "GDP(万亿)"] = gdp
            df.at[idx, "GDP来源"] = source
            df.at[idx, self.value_col] = ratio

        save_excel(self.output_file, df, self.date_col)
        logger.info(f"{self.name}: 已重算 {len(df)} 行，其中 {changed} 行数值变化")
        return changed
