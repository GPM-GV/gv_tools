"""Parsivel disdrometer processing."""

from .core import (
    get_dataset_from_parsivel,
    get_integral_parameters,
    discover_input_dates,
    load_tables,
    process_input,
    process_parsivel_day,
    save_dataframes,
    save_dataframes_to_netcdf,
)
from .workflow import run
from .daily import DailyNetCDFResult, discover_apu_days, run_daily_netcdf
from .location import load_location_timeline, resolve_location
from .plotting import get_dsd_colormap, plot_dsd, plot_integral_parameters, plot_parameters
from .radar import (
    RADAR_BAND_FREQUENCIES_GHZ,
    add_band_reflectivities,
    compute_band_reflectivity,
)

__version__ = "1.2.1"

__all__ = [
    "get_dataset_from_parsivel",
    "get_integral_parameters",
    "discover_input_dates",
    "load_tables",
    "process_input",
    "process_parsivel_day",
    "run",
    "DailyNetCDFResult",
    "discover_apu_days",
    "run_daily_netcdf",
    "load_location_timeline",
    "resolve_location",
    "plot_parameters",
    "plot_dsd",
    "get_dsd_colormap",
    "plot_integral_parameters",
    "RADAR_BAND_FREQUENCIES_GHZ",
    "add_band_reflectivities",
    "compute_band_reflectivity",
    "save_dataframes",
    "save_dataframes_to_netcdf",
]
