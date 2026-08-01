"""
Fetch China GDP data with multi-source fallback and linear extrapolation.

Data sources:
  1. 国家统计局 (NBS) easyquery API — authoritative, public
  2. Hardcoded baseline — fallback with known official values

GDP extrapolation logic (for current year):
  - If annual GDP exists → use directly
  - If Q1+Q2+Q3 available → (Q1+Q2+Q3) / 3 * 4
  - If Q1+Q2 available        → (Q1+Q2) * 2
  - If Q1 available            → Q1 * 4
  - Else                        → last year's annual GDP

Units: 万亿 RMB
"""

import json
import logging
from datetime import date as DateType
from typing import Optional

from core.cache import Cache
from core.data_fetcher import http_get

logger = logging.getLogger(__name__)

# ── Hardcoded baseline GDP data (万亿 RMB) ──────────────────────────
# Source: National Bureau of Statistics official releases.
# Update quarterly as new data is published (usually ~15 days after quarter end).
_GDP_BASELINE = {
    "_version": 5,
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
        # 2025: estimate ~141 based on ~5% nominal growth.
        2025: 141.0,
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
        # "2025Q2": ?,  # usually released mid-July
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

        # 3. Try NBS API to refresh
        try:
            self._try_fetch_nbs()
        except Exception as e:
            logger.info(f"NBS API fetch failed (using baseline): {e}")

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

    def _try_fetch_nbs(self):
        """
        Try to fetch GDP from National Bureau of Statistics easyquery API.
        Updates self.annual and self.quarterly with fresh data.
        """
        # NBS easyquery API — indicator A020101 = GDP
        # Try annual data first
        url = "https://data.stats.gov.cn/easyquery/api"
        params = {
            "m": "QueryData",
            "dbcode": "fsnd",
            "rowcode": "zb",
            "colcode": "sj",
            "wds": "[]",
            "dfwds": json.dumps([
                {"wdcode": "zb", "valuecode": "A020101"},
                {"wdcode": "reg", "valuecode": "000000"},
            ]),
        }
        try:
            resp = http_get(url, params=params, timeout=15)
            data = resp.json()
            records = data.get("returndata", {}).get("datanodes", [])
            for rec in records:
                code_info = rec.get("code", "")
                val = rec.get("data", {}).get("data")
                if val and "strdata" in val:
                    try:
                        year = int(code_info.split(",")[-1].strip().strip('"'))
                        gdp = float(val["strdata"]) / 10000  # NBS gives 亿元
                        if gdp > 10:  # sanity check: > 10万亿
                            self.annual[year] = round(gdp, 2)
                            logger.info(f"NBS: {year} GDP = {gdp:.2f}万亿")
                    except (ValueError, IndexError):
                        continue
        except Exception as e:
            logger.debug(f"NBS annual fetch: {e}")

        # Try quarterly data
        params["dbcode"] = "fsjd"
        try:
            resp = http_get(url, params=params, timeout=15)
            data = resp.json()
            records = data.get("returndata", {}).get("datanodes", [])
            for rec in records:
                code_info = rec.get("code", "")
                val = rec.get("data", {}).get("data")
                if val and "strdata" in val:
                    try:
                        parts = code_info.split(",")
                        year_str = parts[-1].strip().strip('"')
                        # Could be "2024A" or similar
                        year = int(year_str[:4])
                        gdp = float(val["strdata"]) / 10000
                        if gdp > 2:  # sanity: quarterly GDP > 2万亿
                            quarter = 4  # default, NBS fsjd might aggregate
                            key = f"{year}Q{quarter}"
                            self.quarterly[key] = round(gdp, 2)
                    except (ValueError, IndexError):
                        continue
        except Exception as e:
            logger.debug(f"NBS quarterly fetch: {e}")

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
          1. 当年已发布季度外推：Q1+Q2+Q3 → /3×4；Q1+Q2 → ×2；Q1 → ×4
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
        cur_qs = [
            self.get_quarterly(y, q)
            for q in (1, 2, 3)
            if target_date >= self._quarter_release_date(y, q)
        ]
        cur_qs = [v for v in cur_qs if v is not None]
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
