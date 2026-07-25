"""
Abstract base class for all indicators. New indicators just need to:
1. Inherit from BaseIndicator
2. Define name, columns, and compute()
3. Place in the indicators/ directory (auto-discovered)
"""

import logging
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

import pandas as pd

from core.excel_writer import load_excel, save_excel

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

    def run(self, target_date: date | None = None) -> dict | None:
        """
        Compute and save one day. If target_date already exists in the Excel,
        skip computation entirely (no API calls). Returns the result dict,
        or None if skipped due to existing data or compute failure.
        """
        target_date = target_date or date.today()
        date_str = target_date.isoformat()

        # Check if today's data already exists → skip
        existing = self.load_history()
        if not existing.empty and self.date_col in existing.columns:
            existing_dates = set(existing[self.date_col].astype(str))
            if date_str in existing_dates:
                logger.info(f"✓ {self.name}: {date_str} already exists in {self.output_file.name}, skipping")
                return None

        result = self.compute(target_date)
        if result is not None:
            self.save_result(result)
        return result
