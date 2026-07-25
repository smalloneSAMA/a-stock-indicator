"""
Excel I/O: append-or-update rows in an indicator's output file.
"""

from pathlib import Path

import pandas as pd


def load_excel(filepath: Path, date_col: str = "日期") -> pd.DataFrame:
    """Load existing Excel file, or return empty DataFrame if missing."""
    if filepath.exists():
        try:
            df = pd.read_excel(filepath, engine="openpyxl")
            if date_col in df.columns:
                df[date_col] = pd.to_datetime(df[date_col]).dt.date
            return df
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def save_excel(filepath: Path, df: pd.DataFrame, date_col: str = "日期"):
    """
    Save DataFrame to Excel. If date_col exists in existing file,
    update matching row; otherwise append.
    """
    filepath.parent.mkdir(parents=True, exist_ok=True)

    existing = load_excel(filepath, date_col)

    if existing.empty:
        df.to_excel(filepath, index=False, engine="openpyxl")
        return

    # Normalize date columns
    if date_col in df.columns and date_col in existing.columns:
        existing_dates = set(existing[date_col].astype(str))
        new_rows = []
        updated_count = 0
        for _, row in df.iterrows():
            date_str = str(row[date_col])
            if date_str in existing_dates:
                # Update existing row
                mask = existing[date_col].astype(str) == date_str
                for col in df.columns:
                    if col in existing.columns:
                        existing.loc[mask, col] = row[col]
                updated_count += 1
            else:
                new_rows.append(row)
        if new_rows:
            new_df = pd.DataFrame(new_rows)
            existing = pd.concat([existing, new_df], ignore_index=True)
    else:
        existing = pd.concat([existing, df], ignore_index=True)

    existing = existing.sort_values(date_col, ascending=True).reset_index(drop=True)
    existing.to_excel(filepath, index=False, engine="openpyxl")
