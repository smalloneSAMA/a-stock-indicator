"""
Abstract base class for all indicators. New indicators just need to:
1. Inherit from BaseIndicator
2. Define name, columns, and compute()
3. Place in the indicators/ directory (auto-discovered)
"""

import logging
from abc import ABC, abstractmethod
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from core.excel_writer import load_excel, save_excel
from core.trading_calendar import get_trading_days

logger = logging.getLogger(__name__)


class BaseIndicator(ABC):
    """One indicator = one Excel file in output/. Auto-discovered by main.py."""

    # ── Subclasses must define these ──────────────────────────────────
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique indicator name, used as Excel filename stem."""
        ...

    @property
    @abstractmethod
    def columns(self) -> list[str]:
        """Excel column names, first must be the date column."""
        ...

    @abstractmethod
    def compute(self, target_date: date) -> dict:
        """
        Compute one day's indicator values.
        Returns a dict with keys matching self.columns (including date).
        Return None if computation should be skipped for this day.
        """
        ...

    # ── Common infrastructure ─────────────────────────────────────────
    @property
    def output_dir(self) -> Path:
        return Path("output")

    @property
    def output_file(self) -> Path:
        return self.output_dir / f"{self.name}.xlsx"

    @property
    def date_col(self) -> str:
        return self.columns[0] if self.columns else "日期"

    def load_history(self) -> pd.DataFrame:
        """Load existing Excel data for this indicator."""
        return load_excel(self.output_file, self.date_col)

    def save_result(self, result: dict):
        """Save one row (append or update) to this indicator's Excel file."""
        df = pd.DataFrame([result])
        save_excel(self.output_file, df, self.date_col)

    def resolve_target_date(self, target_date: date) -> date | None:
        """
        Map a run date to the date actually recorded (e.g. weekend/holiday →
        last trading day). Return None to skip this run.
        Default: record the given date as-is.
        """
        return target_date

    def run(self, target_date: date | None = None,
            backfill_start: date | None = None) -> dict | None:
        """
        Compute and save, backfilling missing trading days.

        - If the Excel has history and target_date is newer than the last row,
          every missing trading day between the last row and target_date is
          computed and saved (previously only the target day was written,
          leaving gaps).
        - If backfill_start is given, all missing trading days in
          [backfill_start, target_date] are computed, filling older gaps too
          (e.g. between old bi-weekly sample rows).
        - Days that already exist in the Excel are skipped (no duplicate API
          calls). If the Excel is empty and no backfill_start is given, only
          target_date is computed.

        Returns the last computed result dict, or None if nothing was written.
        """
        target_date = target_date or date.today()

        # 非交易日（周末/节假日）没有当日行情：对齐到最近交易日，
        # 避免把上一交易日的收盘市值记到非交易日名下。
        resolved = self.resolve_target_date(target_date)
        if resolved is None:
            logger.warning(f"✗ {self.name}: {target_date} 无法定位交易日，跳过")
            return None
        if resolved != target_date:
            logger.info(f"  {self.name}: {target_date} 非交易日 → 改用最近交易日 {resolved}")
            target_date = resolved

        # Normalize existing dates (load_history returns date objects)
        existing = self.load_history()
        existing_dates: set[str] = set()
        last_date: date | None = None
        if not existing.empty and self.date_col in existing.columns:
            dates = pd.to_datetime(existing[self.date_col], errors="coerce").dt.date
            dates = dates.dropna()
            if len(dates):
                existing_dates = {d.isoformat() for d in dates}
                last_date = max(dates)

        # Decide which dates to compute
        if last_date is None and backfill_start is None:
            # First run: compute only the target day
            dates_to_compute = [target_date]
        else:
            # Backfill missing trading days in [start, target_date]
            start = backfill_start if backfill_start is not None else (
                last_date + timedelta(days=1) if last_date is not None else target_date
            )
            if start > target_date:
                dates_to_compute = []
            else:
                trading_days = get_trading_days(start, target_date)
                if trading_days is None:
                    # Calendar unavailable → fall back to every weekday;
                    # non-trading days are skipped naturally by compute() returning None
                    trading_days = [
                        start + timedelta(days=i)
                        for i in range((target_date - start).days + 1)
                        if (start + timedelta(days=i)).weekday() < 5
                    ]
                dates_to_compute = [
                    d for d in trading_days if d.isoformat() not in existing_dates
                ]
                # target 当天可能因K线未更新而不在交易日历中（如盘中运行），
                # 但 target == today 时走实时市值路径，必须补算当天；
                # 若为未来/数据未覆盖日期，compute() 会自行返回 None
                if (target_date.isoformat() not in existing_dates
                        and target_date not in dates_to_compute):
                    dates_to_compute.append(target_date)

        if not dates_to_compute:
            logger.info(
                f"✓ {self.name}: {target_date.isoformat()} already exists in "
                f"{self.output_file.name}, skipping"
            )
            return None

        if len(dates_to_compute) > 1:
            logger.info(
                f"{self.name}: backfilling {len(dates_to_compute)} missing trading day(s) "
                f"{dates_to_compute[0]} → {dates_to_compute[-1]}"
            )

        # Compute each day; a single-day failure must not abort the batch
        results: list[dict] = []
        for d in dates_to_compute:
            try:
                result = self.compute(d)
            except Exception as e:
                logger.warning(f"{self.name}: {d} compute failed: {e}")
                continue
            if result is not None:
                results.append(result)

        if not results:
            return None

        # Save all rows in one write (append or update)
        df = pd.DataFrame(results)
        save_excel(self.output_file, df, self.date_col)
        return results[-1]
