"""
Buffett Indicator (证券化率) = A-share total market cap / China GDP.

Tracks the ratio daily. GDP is linearly extrapolated when full-year data
is not yet available (see data_sources/gdp.py for logic).
"""

import logging
from datetime import date

from core.base_indicator import BaseIndicator
from data_sources.market_cap import fetch_total_market_cap
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
