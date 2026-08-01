"""
Fetch A-share total market cap: SSE + SZSE + BSE.

Data sources (multi-tier fallback):
  1. 腾讯财经 qt.gtimg.cn — 不封IP, scans multiple fields for per-exchange market cap
  2. Eastmoney push2 API — backup with rate limiting

Historical market cap via index-scaling:
  The real-time API only returns today's values. For historical dates, we scale
  each exchange's today-market-cap by the ratio of its composite index closing
  price on that date vs today.
    historical_mcap = today_mcap × (index_close[date] / index_close[today])
"""

import logging
import re
from datetime import date, timedelta
from typing import Optional

from core.data_fetcher import http_get

logger = logging.getLogger(__name__)

# Tolerances — reject values clearly out of range (reasonable A-share total: 50–150万亿)
_MIN_TOTAL_TRILLION = 30
_MAX_TOTAL_TRILLION = 200

# Index codes for each exchange
_INDEX_CODES = {
    "sse":  ("sh", "000001"),   # 上证综指
    "szse": ("sz", "399106"),   # 深证综指
    "bse":  ("bj", "899050"),   # 北证50
}

# ── Numeric parsing helpers ──────────────────────────────────────────

def _parse_numeric(val) -> float:
    """Parse a value that may be str / int / float / None into float, or 0."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        cleaned = re.sub(r"[^\d.\-]", "", val)
        try:
            return float(cleaned)
        except ValueError:
            return 0.0
    return 0.0


# ── Per-exchange market cap from today's Tencent query ───────────────

def _parse_exchange_mcaps_from_tencent() -> dict[str, float] | None:
    """
    Query Tencent for each exchange index and extract the total market cap.
    Returns {exchange_name: mcap_in_yuan} or None if all fail.
    """
    result: dict[str, float] = {}

    for exchange, (prefix, code) in _INDEX_CODES.items():
        full_code = f"{prefix}{code}"
        url = f"https://qt.gtimg.cn/q={full_code}"

        try:
            resp = http_get(url, timeout=10)
            resp.encoding = "gbk"
            text = resp.text
        except Exception as e:
            logger.warning(f"Tencent HTTP error for {exchange}: {e}")
            continue

        for line in text.strip().split(";"):
            if "=" not in line or '"' not in line:
                continue
            vals = line.split('"')[1].split("~")
            if len(vals) < 55:
                continue

            best_val = 0.0
            for pos in (44, 45, 46, 20, 21):
                if pos >= len(vals):
                    continue
                v = _parse_numeric(vals[pos])
                if v <= 0:
                    continue
                if 1e4 < v < 1e6:         # ~1万—100万 亿 → convert 亿→元
                    v_yuan = v * 1e8
                elif 1e13 < v < 1e16:     # raw 元
                    v_yuan = v
                else:
                    continue
                if v_yuan > best_val:
                    best_val = v_yuan

            if best_val > 0:
                result[exchange] = best_val
                logger.debug(f"Tencent {exchange}: {best_val/1e12:.2f}万亿")

    return result if result else None


def _parse_exchange_mcaps_from_eastmoney() -> dict[str, float] | None:
    """
    Fallback: per-exchange market cap from Eastmoney push2.
    """
    index_map = {
        "sse":  "1.000001",
        "szse": "0.399106",
        "bse":  "0.899050",
    }
    result: dict[str, float] = {}

    for exchange, secid in index_map.items():
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {
            "secid": secid,
            "fields": "f20,f21,f44,f45,f46,f116,f117,f118,f119",
            "invt": "2",
            "fltt": "2",
        }
        headers = {"Referer": "https://quote.eastmoney.com/"}

        try:
            resp = http_get(url, params=params, headers=headers, timeout=15)
            data = resp.json().get("data") or {}
        except Exception as e:
            logger.warning(f"Eastmoney HTTP error for {exchange}: {e}")
            continue

        best_val = 0.0
        for field in ("f20", "f44", "f116", "f117", "f118", "f119", "f21", "f45", "f46"):
            raw = data.get(field)
            v = _parse_numeric(raw)
            if 5e11 < v < 1e16:
                best_val = max(best_val, v)

        if best_val > 0:
            result[exchange] = best_val
            logger.debug(f"Eastmoney {exchange}: {best_val/1e12:.2f}万亿")
        else:
            logger.warning(f"Eastmoney {exchange}: no mcap field found")

    return result if result else None


# Cache today's per-exchange caps so batch processing doesn't re-fetch
_EXCHANGE_CACHE: dict[str, float] = {}
_EXCHANGE_CACHE_DATE: Optional[date] = None


def _get_today_exchange_mcaps() -> dict[str, float]:
    """
    Get today's per-exchange market cap in 元.
    Cached for the current date to avoid repeated HTTP requests.
    Returns {exchange: mcap_yuan}.
    """
    global _EXCHANGE_CACHE, _EXCHANGE_CACHE_DATE
    today = date.today()
    if _EXCHANGE_CACHE and _EXCHANGE_CACHE_DATE == today:
        return _EXCHANGE_CACHE

    result = _parse_exchange_mcaps_from_tencent()
    if result is not None:
        _EXCHANGE_CACHE = result
        _EXCHANGE_CACHE_DATE = today
        return result

    result = _parse_exchange_mcaps_from_eastmoney()
    if result is not None:
        _EXCHANGE_CACHE = result
        _EXCHANGE_CACHE_DATE = today
        return result

    raise RuntimeError("All market cap data sources failed.")


# ── Historical index close prices ────────────────────────────────────
# Multiple fallbacks: Tencent → Eastmoney
_INDEX_KLINE_CACHE: dict[str, dict[str, float]] = {}
_INDEX_KLINE_DAYS = 5000


def _fetch_index_klines_tencent(index_code: str, prefix: str) -> dict[str, float] | None:
    """
    Fetch K-lines via Tencent fqkline endpoint (3 batches to cover ~2002~today).
    The count param is capped at ~2000 per request; we pull 3 overlapping
    ranges to get ~25 years.

    Returns {date_str: close_price}.
    """
    cache_key = f"{prefix}{index_code}"
    all_results: dict[str, float] = {}

    def _fetch_batch(end_date: str = "") -> list:
        """Make one batch request. Empty end_date means 'to today'."""
        if end_date:
            url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={cache_key},day,,{end_date},2000,qfq"
        else:
            url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={cache_key},day,,,2000,qfq"
        resp = http_get(url, timeout=10)
        data = resp.json()
        if not isinstance(data, dict):
            return []
        d = data.get("data", {})
        if not isinstance(d, dict):
            return []
        return d.get(index_code, {}).get("day", []) or d.get(cache_key, {}).get("day", [])

    def _extract(klines: list):
        for k in klines:
            if isinstance(k, (list, tuple)) and len(k) >= 3:
                ds, c = str(k[0])[:10], _parse_numeric(k[2])
                if c > 0:
                    all_results[ds] = c

    # Phase 1: latest 2000 days (no end_date)
    try:
        _extract(_fetch_batch())
    except Exception as e:
        logger.warning(f"Tencent K-line phase 1 failed: {e}")

    if not all_results:
        return None

    # Phase 2: up to 1 day before phase 1's earliest
    dates = sorted(all_results.keys())
    for _ in range(2):  # up to 2 more batches
        earliest = dates[0]
        from datetime import datetime as _dt, timedelta as _td
        prev = (_dt.strptime(earliest, "%Y-%m-%d") - _td(days=1)).strftime("%Y-%m-%d")
        try:
            batch = _fetch_batch(prev)
            _extract(batch)
            if not batch:
                break
            dates = sorted(all_results.keys())
        except Exception as e:
            logger.warning(f"Tencent K-line phase (≤{prev}) failed: {e}")
            break

    return all_results


def _fetch_index_klines_eastmoney(secid: str) -> dict[str, float] | None:
    """Fetch index K-lines via Eastmoney push2his API."""
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "klt": "101",                # daily
        "fqt": "1",                  # forward adjusted
        "fields1": "f1,f2,f3,f4,f5",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
        "lmt": str(_INDEX_KLINE_DAYS),
    }
    headers = {"Referer": "https://quote.eastmoney.com/"}

    try:
        resp = http_get(url, params=params, headers=headers, timeout=10)
        data = resp.json()
    except Exception as e:
        logger.warning(f"Eastmoney K-line fetch failed for {secid}: {e}")
        return None

    klines = data.get("data", {}).get("klines", [])
    if not klines:
        return None

    result: dict[str, float] = {}
    for k in klines:
        parts = str(k).split(",")
        if len(parts) >= 3:
            ds = parts[0][:10]
            close = _parse_numeric(parts[2])
            if close > 0:
                result[ds] = close

    return result if result else None


def _fetch_index_klines(index_code: str, prefix: str) -> dict[str, float]:
    """
    Fetch daily K-line close prices for an index.
    Returns {date_str: close_price} for all available trading days.
    """
    cache_key = f"{prefix}{index_code}"
    if cache_key in _INDEX_KLINE_CACHE:
        return _INDEX_KLINE_CACHE[cache_key]

    # Tier 1: Tencent (不封IP)
    result = _fetch_index_klines_tencent(index_code, prefix)

    # Tier 2: Eastmoney push2his (blocked on some networks; kept as fallback)
    if result is None:
        em_secid = f"1.{index_code}" if prefix == "sh" else f"0.{index_code}"
        result = _fetch_index_klines_eastmoney(em_secid)

    if result is None:
        logger.warning(f"All K-line sources failed for {cache_key}")
        result = {}

    _INDEX_KLINE_CACHE[cache_key] = result
    logger.debug(f"Fetched {len(result)} K-lines for {cache_key}")
    return result


def _find_nearest_trading_day(target_date: date, klines: dict[str, float]) -> tuple[Optional[str], Optional[float]]:
    """
    Look up a date in the klines dict. If not found (weekend/holiday),
    walk backwards up to 7 days to find the nearest trading day.
    """
    target_str = target_date.isoformat()
    close = klines.get(target_str)
    if close is not None:
        return target_str, close

    for offset in range(1, 8):
        d = target_date - timedelta(days=offset)
        s = d.isoformat()
        close = klines.get(s)
        if close is not None:
            return s, close

    return None, None


# ── Historical real market-cap anchors (万亿, 沪深A股总市值) ───────
# 来源：交易所官方统计/权威公开报道。
# 作用：校正“指数缩放法”未考虑 IPO 扩容导致的系统性高估。
#   在相邻锚点区间内，市值随上证综指点位线性插值。
_MCAP_ANCHORS = [
    ("2005-06-06", 3.2),    # 998点历史大底
    ("2007-10-16", 36.0),   # 6124点历史大顶
    ("2008-10-28", 11.0),   # 1664点
    ("2009-12-31", 24.4),
    ("2013-06-25", 18.9),   # 1849点
    ("2014-12-31", 37.3),
    ("2015-06-12", 71.0),   # 5178点
    ("2016-12-30", 50.8),
    ("2018-12-28", 43.4),
    ("2019-01-04", 43.9),   # 2440点
    ("2020-12-31", 79.7),
    ("2021-12-31", 91.9),
    ("2024-02-05", 75.0),   # 2635点
    ("2024-10-08", 94.0),   # 3674点
]


def _estimate_historical_mcap(target_date: date, today_total: float,
                              sse_klines: dict[str, float]) -> Optional[float]:
    """
    锚点插值法估算历史总市值（万亿）。

    1. 用真实历史市值锚点 + 上证综指收盘点位构建锚点序列（含今日实时锚点）
    2. 目标日期落在某锚点区间内 → 市值随指数点位线性插值
    3. 早于首个锚点 → 用首个锚点按指数比例外推
    """
    today = date.today()

    # 构建锚点序列: (date, mcap万亿, 上证收盘)
    points: list[tuple[date, float, float]] = []
    for ds, m in _MCAP_ANCHORS:
        d = date.fromisoformat(ds)
        _, idx = _find_nearest_trading_day(d, sse_klines)
        if idx:
            points.append((d, m, idx))

    # 追加今日实时锚点
    _, today_idx = _find_nearest_trading_day(today, sse_klines)
    if today_idx:
        points.append((today, today_total, today_idx))

    points.sort()
    if len(points) < 2:
        return None

    _, target_idx = _find_nearest_trading_day(target_date, sse_klines)
    if target_idx is None:
        return None

    # 早于首个锚点 → 外推
    if target_date < points[0][0]:
        d0, m0, i0 = points[0]
        return m0 * (target_idx / i0)

    # 找到所在锚点区间 → 线性插值
    for i in range(len(points) - 1):
        d0, m0, i0 = points[i]
        d1, m1, i1 = points[i + 1]
        if d0 <= target_date <= d1:
            if i1 == i0:
                return m0
            return m0 + (m1 - m0) * (target_idx - i0) / (i1 - i0)

    return None


# ── Main entry point ─────────────────────────────────────────────────

def fetch_total_market_cap(target_date: Optional[date] = None) -> float:
    """
    Fetch A-share total market cap (万亿 RMB) for a specific date.

    - If target_date is None or today, returns the real-time market cap.
    - If target_date is a past date:
        Tier 1: 锚点插值法（历史真实市值锚点 + 指数点位插值，校正IPO扩容）
        Tier 2: 指数缩放法（旧方法，锚点数据缺失时兜底）

    Raises RuntimeError if all sources fail.
    """
    target_date = target_date or date.today()
    today = date.today()

    # 1. Get today's per-exchange market caps
    exchange_mcaps = _get_today_exchange_mcaps()
    today_total = round(sum(exchange_mcaps.values()) / 1e12, 4)

    # If querying today, return directly
    if target_date == today:
        logger.info(f"Total A-share market cap: {today_total:.4f}万亿 (today)")
        return today_total

    # 2. Historical — Tier 1: anchor interpolation (corrects IPO expansion)
    sse_klines = _fetch_index_klines("000001", "sh")
    est = _estimate_historical_mcap(target_date, today_total, sse_klines)
    if est is not None:
        logger.info(f"Historical A-share mcap for {target_date}: {est:.4f}万亿 (anchor interpolation)")
        return round(est, 4)

    # 3. Historical — Tier 2: index scaling (old method, fallback)
    szse_klines = _fetch_index_klines("399106", "sz")

    _, today_sse_close = _find_nearest_trading_day(today, sse_klines)
    _, target_sse_close = _find_nearest_trading_day(target_date, sse_klines)
    _, today_szse_close = _find_nearest_trading_day(today, szse_klines)
    _, target_szse_close = _find_nearest_trading_day(target_date, szse_klines)

    # If we can't get index data, this is likely a non-trading day (holiday).
    # Do NOT fabricate today's value for a historical date — skip instead.
    if not (today_sse_close and target_sse_close and today_szse_close and target_szse_close):
        raise RuntimeError(
            f"No index K-line data for {target_date} "
            f"(likely non-trading day). Skipping."
        )

    # Scale each exchange
    sse_mcap = exchange_mcaps.get("sse", 0)
    szse_mcap = exchange_mcaps.get("szse", 0)
    bse_mcap = exchange_mcaps.get("bse", 0)  # BSE unchanged (tiny <1%)

    sse_historical = sse_mcap * (target_sse_close / today_sse_close)
    szse_historical = szse_mcap * (target_szse_close / today_szse_close)
    historical_total = round((sse_historical + szse_historical + bse_mcap) / 1e12, 4)

    logger.info(
        f"Historical A-share mcap for {target_date}: {historical_total:.4f}万亿 "
        f"(index scaling fallback)"
    )
    return historical_total
