"""Interface implemented by GV instrument adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import xarray as xr

from ..metadata import InstrumentMetadata


class InstrumentAdapter(ABC):
    """Translate instrument-specific input into normalized GV products."""

    name: str

    def __init__(self, metadata: InstrumentMetadata):
        self.metadata = metadata

    @abstractmethod
    def discover(self, input_path: str | Path) -> list[str]:
        """Return the dates available below *input_path* as YYYY-MM-DD."""

    @abstractmethod
    def read(
        self,
        input_path: str | Path,
        **options,
    ) -> dict[str, xr.Dataset]:
        """Read and normalize products keyed by YYYY-MM-DD."""


_UTC_NAMES = {"utc", "etc/utc", "gmt", "etc/gmt", "z", "zulu"}


def localize_to_utc(times, timezone: str) -> tuple[pd.Series, int]:
    """Convert naive local times to naive UTC; return them and the number left unresolved.

    Local times that a daylight-saving change makes ambiguous are resolved
    from their order when possible (``ambiguous="infer"``); times that remain
    ambiguous, and times that do not exist (the skipped hour), become NaT
    instead of aborting the whole read. Fixed-offset zones such as
    ``Etc/GMT+5`` never need this.
    """
    series = pd.Series(pd.to_datetime(times)).reset_index(drop=True)
    if str(timezone).strip().lower() in _UTC_NAMES:
        return series, 0
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown source timezone: {timezone!r}") from exc
    try:
        localized = series.dt.tz_localize(zone, ambiguous="infer", nonexistent="NaT")
    except Exception:  # pandas raises AmbiguousTimeError/ValueError when order cannot resolve it
        localized = series.dt.tz_localize(zone, ambiguous="NaT", nonexistent="NaT")
    unresolved = int(localized.isna().sum() - series.isna().sum())
    return localized.dt.tz_convert("UTC").dt.tz_localize(None), unresolved
