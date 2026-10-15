"""Unified PIERS gauge, platform, and comparison tools.

The public API combines the former :mod:`piers_gauge_tools` daily-report
package with the former ``comp_standalone_gauges`` range-comparison package.
Application code should import from this module or from the documented
submodules; the two legacy package names are intentionally not installed.
"""

__version__ = "0.9.0"

from .parsing import parse_piers_files, parse_piers_multiple_files
from .pipeline import build_daily_report, load_locations
from .plotting import generate_gauge_plots
from .reporting import gauge_csv_to_html, gauge_report_to_html
from .comparison import (
    InputDataError,
    circular_mean,
    event_totals,
    load_day,
    process_range,
    read_standalone,
    read_wind,
    save_day,
)
from .daily import DailyResult, process_day
from .gauge import ingest_gauge_range

__all__ = [
    "build_daily_report",
    "gauge_csv_to_html",
    "gauge_report_to_html",
    "generate_gauge_plots",
    "load_locations",
    "parse_piers_files",
    "parse_piers_multiple_files",
    "InputDataError",
    "circular_mean",
    "event_totals",
    "load_day",
    "process_range",
    "read_standalone",
    "read_wind",
    "save_day",
    "DailyResult",
    "process_day",
    "ingest_gauge_range",
]
