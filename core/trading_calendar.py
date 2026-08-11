"""
交易日历：基于上证指数日K线（腾讯 ifzq 接口，不封IP）推导 A 股交易日集合。

用途：BaseIndicator.run() 回填缺失数据时，只对真实交易日计算，
避免对周末/节假日做无意义的请求和写入。

抓取失败时 get_trading_days() 返回 None，由调用方降级为
"逐日尝试（跳过周末）"，非交易日由 compute() 自行跳过。
"""

import logging
from datetime import date, timedelta

from core.data_fetcher import http_get

logger = logging.getLogger(__name__)

_BATCH_SIZE = 2000   # 腾讯接口单批上限（约 8 年日K）
_MAX_BATCHES = 3     # 最多抓 3 批（约 24 年，覆盖 2002 至今）

_CACHE: set[date] | None = None


def _fetch_batch(end_date: str = "") -> list:
    """抓一批上证指数日K。end_date 为空表示最新一批。"""
    code = "sh000001"
    if end_date:
        url = (f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
               f"?param={code},day,,{end_date},{_BATCH_SIZE},qfq")
    else:
        url = (f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
               f"?param={code},day,,,{_BATCH_SIZE},qfq")
    resp = http_get(url, timeout=10)
    data = resp.json()
    d = (data or {}).get("data", {}) if isinstance(data, dict) else {}
    if not isinstance(d, dict):
        return []
    return d.get("000001", {}).get("day", []) or d.get(code, {}).get("day", [])


def _load_all_trading_days() -> set[date] | None:
    """抓取全部可用交易日（模块级缓存，进程内）。失败返回 None。"""
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    all_days: set[date] = set()

    def _extract(klines: list) -> bool:
        """把一批K线里的日期加入集合，返回是否新增了日期。"""
        added = False
        for k in klines:
            if isinstance(k, (list, tuple)) and k:
                try:
                    all_days.add(date.fromisoformat(str(k[0])[:10]))
                    added = True
                except ValueError:
                    continue
        return added

    try:
        batch = _fetch_batch()
        _extract(batch)
        for _ in range(_MAX_BATCHES - 1):
            if not batch:
                break
            earliest = min(all_days)
            prev = (earliest - timedelta(days=1)).isoformat()
            batch = _fetch_batch(prev)
            if not _extract(batch):
                break
    except Exception as e:
        logger.warning(f"Trading calendar fetch failed (will retry later): {e}")
        return None

    if not all_days:
        logger.warning("Trading calendar: no trading days fetched.")
        return None

    _CACHE = all_days
    logger.debug(f"Trading calendar loaded: {len(all_days)} trading days")
    return all_days


def get_trading_days(start: date, end: date) -> list[date] | None:
    """
    返回 [start, end] 区间内的交易日（升序）。
    日历抓取失败返回 None（调用方应降级处理）。
    """
    if start > end:
        return []
    days = _load_all_trading_days()
    if days is None:
        return None
    return sorted(d for d in days if start <= d <= end)
