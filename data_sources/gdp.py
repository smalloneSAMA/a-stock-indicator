"""
Fetch China GDP data with multi-source fallback and linear extrapolation.

Data sources:
  1. 东方财富 datacenter API（转引国家统计局）— 季度累计值，可自动刷新
  2. Hardcoded baseline — fallback with known official values

GDP extrapolation logic (for current year):
  - If annual GDP exists → use directly
  - If Q1+Q2+Q3 available → (Q1+Q2+Q3) / 3 * 4
  - If Q1+Q2 available        → (Q1+Q2) * 2
  - If Q1 available            → Q1 * 4
  - Else                        → last year's annual GDP

Units: 万亿 RMB
"""

import logging
import re
from datetime import date as DateType
from typing import Optional

from core.cache import Cache
from core.data_fetcher import http_get

logger = logging.getLogger(__name__)

_EM_GDP_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def _parse_em_quarter(label: str | None) -> tuple[int | None, int | None]:
    """解析东财季度标签：「2026年第1-3季度」→ (2026, 3)，「2025年第1季度」→ (2025, 1)。"""
    if not label:
        return None, None
    match = re.search(r"(\d{4})年第1(?:-(\d))?季度", label)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2) or 1)

# ── Hardcoded baseline GDP data (万亿 RMB) ──────────────────────────
# Source: National Bureau of Statistics official releases.
# Update quarterly as new data is published (usually ~15 days after quarter end).
_GDP_BASELINE = {
    "_version": 6,
    "annual": {
        2000: 10.03,
        2001: 11.09,
        2002: 12.17,
        2003: 13.74,
        2004: 15.99,
        2005: 18.73,
        2006: 21.94,
        2007: 27.01,
        2008: 31.92,
        2009: 34.85,
        2010: 41.21,
        2011: 48.79,
        2012: 53.86,
        2013: 59.30,
        2014: 64.36,
        2015: 68.89,
        2016: 74.64,
        2017: 83.20,
        2018: 91.93,
        2019: 98.65,
        2020: 101.36,
        2021: 114.92,
        2022: 121.02,
        2023: 126.06,
        2024: 134.91,
        # 2025 官方值（统计局 2026-01 发布，第五次经济普查修订口径）
        2025: 140.19,
    },
    "quarterly": {
        # 2023
        "2023Q1": 28.50,
        "2023Q2": 30.82,
        "2023Q3": 30.80,
        "2023Q4": 35.94,
        # 2024
        "2024Q1": 29.63,
        "2024Q2": 32.05,
        "2024Q3": 33.29,
        "2024Q4": 39.94,
        # 2025
        "2025Q1": 31.87,
        "2025Q2": 34.14,
        "2025Q3": 35.41,
        "2025Q4": 38.79,
    },
}


class GDPData:
    """Manages China GDP data: loading, caching, extrapolation."""

    def __init__(self):
        self.annual: dict[int, float] = {}
        self.quarterly: dict[str, float] = {}  # key: "2024Q1"
        self._cache = Cache("gdp_data")

    def load(self):
        """
        Load GDP data: cache → API fetch → hardcoded baseline.
        Returns self for chaining.
        """
        # 1. Try cache (lasts 1 day; versioned so baseline updates invalidate old caches)
        cached_version = self._cache.get("_version")
        if cached_version == _GDP_BASELINE.get("_version", 1) and self._cache.get("quarterly"):
            self.quarterly = self._cache.get("quarterly") or {}
            # JSON serializes integer dict keys to strings; convert back
            raw_annual = self._cache.get("annual") or {}
            self.annual = {int(k): v for k, v in raw_annual.items()}
            self._compute_annual_from_quarterly()
            logger.info("GDP data loaded from cache")
            return self

        # 2. Load hardcoded baseline
        self.annual = dict(_GDP_BASELINE["annual"])
        self.quarterly = dict(_GDP_BASELINE["quarterly"])
        self._compute_annual_from_quarterly()

        # 3. 从东方财富刷新（失败则继续用内置基线，但会打 warning）
        try:
            self._try_fetch_eastmoney()
        except Exception as e:
            logger.warning("GDP 刷新异常，改用内置基线：%s", e)

        # 4. Save to cache for 24h (versioned)
        self._cache.set("_version", _GDP_BASELINE.get("_version", 1))
        self._cache.set("quarterly", self.quarterly, ttl=86400)
        self._cache.set("annual", self.annual, ttl=86400)

        return self

    def _compute_annual_from_quarterly(self):
        """Fill annual GDP from quarterly sums where annual is missing."""
        q_by_year: dict[int, dict[int, float]] = {}
        for key, val in self.quarterly.items():
            # key format: "2024Q1"
            year = int(key[:4])
            quarter = int(key[5:])
            q_by_year.setdefault(year, {})[quarter] = val

        for year, quarters in q_by_year.items():
            if year not in self.annual and len(quarters) == 4:
                self.annual[year] = round(sum(quarters.values()), 2)

    def _try_fetch_eastmoney(self) -> bool:
        """
        拉取东方财富（转引国家统计局）的 GDP 并写入本类。

        接口返回「第1-N季度」累计值（亿元），本类内部统一存单季值（万亿），
        因此同年内逐级相减；「第1-4季度」的累计值即官方全年 GDP。
        返回是否成功拿到可用数据。
        """
        params = {
            "reportName": "RPT_ECONOMY_GDP",
            "columns": "ALL",
            "pageSize": "100",
            "sortColumns": "REPORT_DATE",
            "sortTypes": "-1",
        }
        try:
            resp = http_get(_EM_GDP_URL, params=params, timeout=15)
            payload = resp.json()
        except Exception as e:
            logger.warning("GDP 刷新失败（东方财富接口不可用）：%s", e)
            return False

        rows = (payload.get("result") or {}).get("data") or []
        if not rows:
            logger.warning("GDP 刷新失败（东方财富接口返回空数据）")
            return False

        cumulative: dict[int, dict[int, float]] = {}
        for row in rows:
            year, quarter = _parse_em_quarter(row.get("TIME"))
            raw = row.get("DOMESTICL_PRODUCT_BASE")
            if year is None or quarter is None:
                continue
            if not isinstance(raw, (int, float)) or raw <= 0:
                continue
            cumulative.setdefault(year, {})[quarter] = raw / 10000  # 亿元 → 万亿

        if not cumulative:
            logger.warning("GDP 刷新失败（东方财富返回的数据无法解析）")
            return False

        updated = 0
        for year, quarters in cumulative.items():
            previous = 0.0
            for quarter in sorted(quarters):
                current = quarters[quarter]
                single = round(current - previous, 2)
                previous = current
                if not 2 < single < 100:  # sanity: 单季 GDP 2~100 万亿
                    continue
                self.quarterly[f"{year}Q{quarter}"] = single
                if quarter == 4 and 10 < current < 300:
                    self.annual[year] = round(current, 2)
                updated += 1

        if not updated:
            logger.warning("GDP 刷新失败（没有通过校验的季度数据）")
            return False

        latest_year = max(self.annual) if self.annual else None
        latest_quarter = max(self.quarterly) if self.quarterly else None
        logger.info(
            "GDP 已从东方财富刷新：最新年度 %s=%s万亿，最新季度 %s=%s万亿",
            latest_year, self.annual.get(latest_year) if latest_year else None,
            latest_quarter, self.quarterly.get(latest_quarter) if latest_quarter else None,
        )
        return True

    def get_annual(self, year: int) -> Optional[float]:
        """Get known annual GDP for a given year."""
        return self.annual.get(year)

    def get_quarterly(self, year: int, quarter: int) -> Optional[float]:
        """Get quarterly GDP for a specific quarter."""
        return self.quarterly.get(f"{year}Q{quarter}")

    @staticmethod
    def _quarter_release_date(year: int, quarter: int) -> DateType:
        """
        季度GDP数据发布时间（point-in-time）：约季后17天由统计局发布。
        Q4与次年1月中旬的全年初步核算一同发布。
        """
        if quarter == 4:
            return DateType(year + 1, 1, 17)
        return {
            1: DateType(year, 4, 17),
            2: DateType(year, 7, 17),
            3: DateType(year, 10, 19),
        }[quarter]

    def get_extrapolated_gdp(self, target_date: DateType) -> tuple[float, str]:
        """
        Compute the best GDP available *as of target_date* (point-in-time).

        Extrapolation strategy (order of preference, honoring release dates):
          1. 当年已发布季度外推：按去年同期占比折算（缺去年同期数据时退回
             Q1+Q2+Q3 → /3×4；Q1+Q2 → ×2；Q1 → ×4）
          2. 上年全年GDP（当年1月17日发布后）
          3. 去年已发布季度外推（当年1月17日前，全年未发布时）
          4. 更早年份全年GDP（按各自发布时间）

        Returns:
          (gdp_in_trillion_rmb, source_description)
        """
        y = target_date.year

        def _extrapolate(qs: list[float], year: int) -> tuple[float, str] | None:
            if not qs:
                return None
            n, total = len(qs), sum(qs)
            if n == 3:
                return round(total / 3 * 4, 2), f"{year}年前三季度GDP线性外推({total:.1f}/3×4)"
            if n == 2:
                return round(total * 2, 2), f"{year}年上半年GDP线性外推({total:.1f}×2)"
            return round(total * 4, 2), f"{year}年Q1 GDP线性外推({total:.1f}×4)"

        # 1. 当年已发布季度外推
        #    优先按「去年同期累计值占上年全年」的比例外推：Q1 季节性明显
        #    （遇上疫情这类异常季更会失真），直接 ×4 的偏差可达 10% 以上。
        cur_qs: list[float] = []
        for q in (1, 2, 3):
            if target_date < self._quarter_release_date(y, q):
                break
            value = self.get_quarterly(y, q)
            if value is None:
                break
            cur_qs.append(value)

        if cur_qs:
            prev_annual = self.get_annual(y - 1)
            prev_qs: list[float] = []
            for q in range(1, len(cur_qs) + 1):
                prev_value = self.get_quarterly(y - 1, q)
                if prev_value is None:
                    prev_qs = []
                    break
                prev_qs.append(prev_value)
            prev_total = sum(prev_qs)
            if prev_annual is not None and prev_total > 0:
                cur_total = sum(cur_qs)
                estimate = round(cur_total / prev_total * prev_annual, 2)
                return estimate, (
                    f"{y}年前{len(cur_qs)}季GDP按去年同期占比外推"
                    f"({cur_total:.1f}/{prev_total:.1f}×{prev_annual:.1f})"
                )
            hit = _extrapolate(cur_qs, y)
            if hit:
                return hit

        # 2. 上年全年GDP（y年1月17日起可得）
        if target_date >= DateType(y, 1, 17):
            prev = self.get_annual(y - 1)
            if prev is not None:
                return prev, f"{y - 1}年全年GDP"

        # 3. 去年已发布季度外推（当年1月17日前，去年全年尚未发布）
        prev_qs = [
            self.get_quarterly(y - 1, q)
            for q in (1, 2, 3)
            if target_date >= self._quarter_release_date(y - 1, q)
        ]
        prev_qs = [v for v in prev_qs if v is not None]
        hit = _extrapolate(prev_qs, y - 1)
        if hit:
            return hit

        # 4. 更早年份全年GDP（按发布时间过滤）
        for offset in range(2, 6):
            py = y - offset
            val = self.get_annual(py)
            if val is not None and target_date >= DateType(py + 1, 1, 17):
                return val, f"{py}年全年GDP"

        # 5. 极端兜底：数据缺口时用最早年度的全年GDP（并提示）
        if self.annual:
            oldest = min(self.annual)
            logger.warning(
                f"{target_date} 早于可用GDP发布日，使用{oldest}年全年GDP近似"
            )
            return self.annual[oldest], f"{oldest}年全年GDP(数据缺口近似)"

        raise RuntimeError(f"No GDP data available for year {y} or prior.")


# ── Convenience function ─────────────────────────────────────────────
def fetch_gdp(target_date: Optional[DateType] = None) -> tuple[float, str]:
    """
    Fetch the best available GDP for the Buffett Indicator.
    Returns (gdp_in_trillion_rmb, source_description).
    """
    target_date = target_date or DateType.today()
    gdp_data = GDPData().load()
    return gdp_data.get_extrapolated_gdp(target_date)
