#!/usr/bin/env python3
"""
A-stock Indicator Runner — extensible indicator computation engine.

Usage:
  python main.py                    # Run all indicators for today
  python main.py --date 2026-01-15  # Run all indicators for a specific date
  python main.py --list             # List all available indicators
  python main.py --indicator buffett_indicator  # Run only a specific indicator
"""

import argparse
import importlib
import logging
import pkgutil
import sys
from datetime import date, datetime
from pathlib import Path

from core.base_indicator import BaseIndicator

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


# ── Auto-discovery ───────────────────────────────────────────────────
def discover_indicators() -> dict[str, type[BaseIndicator]]:
    """
    Scan the indicators/ package for all BaseIndicator subclasses.
    Returns {name: IndicatorClass}.
    """
    import indicators as pkg

    discovered = {}
    pkg_path = Path(pkg.__path__[0])  # type: ignore[attr-defined]

    for _, module_name, _ in pkgutil.iter_modules([str(pkg_path)]):
        full_name = f"indicators.{module_name}"
        try:
            mod = importlib.import_module(full_name)
        except Exception as e:
            logger.warning(f"Failed to import {full_name}: {e}")
            continue

        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if (isinstance(attr, type)
                    and issubclass(attr, BaseIndicator)
                    and attr is not BaseIndicator):
                instance = attr()
                discovered[instance.name] = attr

    return discovered


# ── CLI ──────────────────────────────────────────────────────────────
def parse_date(date_str: str) -> date:
    """Parse YYYY-MM-DD string to date."""
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def main():
    parser = argparse.ArgumentParser(
        description="A-stock Indicator Runner — compute and save financial indicators.",
    )
    parser.add_argument(
        "--date", "-d",
        type=str,
        default=None,
        help="Target date (YYYY-MM-DD). Default: today.",
    )
    parser.add_argument(
        "--indicator", "-i",
        type=str,
        default=None,
        help="Run only a specific indicator by name.",
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all available indicators and exit.",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress non-error output.",
    )

    args = parser.parse_args()

    if args.quiet:
        logging.getLogger().setLevel(logging.WARNING)

    # Discover indicators
    indicators = discover_indicators()

    # --list
    if args.list:
        print(f"Available indicators ({len(indicators)}):")
        for name, cls in sorted(indicators.items()):
            inst = cls()
            cols = ", ".join(inst.columns[1:]) if len(inst.columns) > 1 else "(none)"
            print(f"  {name}")
            print(f"    Columns: {cols}")
            print(f"    Output:  {inst.output_file}")
        return

    if not indicators:
        logger.error("No indicators found in indicators/ directory.")
        sys.exit(1)

    # Filter by name
    if args.indicator:
        if args.indicator not in indicators:
            logger.error(
                f"Unknown indicator '{args.indicator}'. "
                f"Available: {', '.join(sorted(indicators))}"
            )
            sys.exit(1)
        selected = {args.indicator: indicators[args.indicator]}
    else:
        selected = indicators

    # Parse date
    target_date = parse_date(args.date) if args.date else date.today()

    # Run
    logger.info(f"Running {len(selected)} indicator(s) for {target_date}...")
    success = 0
    fail = 0

    for name, cls in sorted(selected.items()):
        try:
            inst = cls()
            result = inst.run(target_date)
            if result is not None:
                logger.info(f"  ✓ {name}: saved to {inst.output_file}")
                success += 1
            else:
                logger.info(f"  - {name}: skipped")
        except Exception as e:
            logger.error(f"  ✗ {name}: {e}", exc_info=True)
            fail += 1

    logger.info(f"Done: {success} succeeded, {fail} failed, {len(selected) - success - fail} skipped.")


if __name__ == "__main__":
    main()
