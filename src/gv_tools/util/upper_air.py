"""Download point subsets of NOAA model pressure-level data.

The downloaded GRIB2 files contain the fields normally needed to construct an
upper-air sounding: height, temperature, relative humidity, and the horizontal
wind components on all available pressure levels.  Downloads use NOAA NCEP's
NOMADS grib-filter service and do not require an API key.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


NOMADS_BASE_URL = "https://nomads.ncep.noaa.gov/cgi-bin"
_UTC = timezone.utc


class SoundingDownloadError(RuntimeError):
    """Raised when a requested model sounding cannot be downloaded."""


class ModelUnavailableError(ValueError):
    """Raised when a retired or unsupported model is requested."""


@dataclass(frozen=True)
class _Model:
    endpoint: str
    cycle_hours: tuple[int, ...]
    directory: Callable[[datetime], str]
    filename: Callable[[datetime, int], str]
    half_width: float


@dataclass(frozen=True)
class DownloadedSounding:
    """Metadata for one downloaded model profile file."""

    model: str
    cycle: datetime
    forecast_hour: int
    valid_time: datetime
    latitude: float
    longitude: float
    path: Path
    url: str


_MODELS = {
    "rap": _Model(
        "filter_rap.pl",
        tuple(range(24)),
        lambda cycle: f"rap.{cycle:%Y%m%d}",
        lambda cycle, forecast: f"rap.t{cycle:%H}z.awp130pgrbf{forecast:02d}.grib2",
        0.15,
    ),
    "hrrr": _Model(
        "filter_hrrr_2d.pl",
        tuple(range(24)),
        lambda cycle: f"hrrr.{cycle:%Y%m%d}/conus",
        lambda cycle, forecast: f"hrrr.t{cycle:%H}z.wrfprsf{forecast:02d}.grib2",
        0.08,
    ),
    "gfs": _Model(
        "filter_gfs_0p25.pl",
        (0, 6, 12, 18),
        lambda cycle: f"gfs.{cycle:%Y%m%d}/{cycle:%H}/atmos",
        lambda cycle, forecast: f"gfs.t{cycle:%H}z.pgrb2.0p25.f{forecast:03d}",
        0.30,
    ),
    "nam": _Model(
        "filter_nam.pl",
        (0, 6, 12, 18),
        lambda cycle: f"nam.{cycle:%Y%m%d}",
        lambda cycle, forecast: f"nam.t{cycle:%H}z.awphys{forecast:02d}.tm00.grib2",
        0.15,
    ),
}

_VARIABLES = ("HGT", "RH", "TMP", "UGRD", "VGRD")


def available_models() -> tuple[str, ...]:
    """Return model identifiers supported by the downloader."""

    return tuple(_MODELS)


def _as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("times must be datetime objects")
    if value.tzinfo is None:
        return value.replace(tzinfo=_UTC)
    return value.astimezone(_UTC)


def _validate_location(latitude: float, longitude: float) -> tuple[float, float]:
    latitude = float(latitude)
    longitude = float(longitude)
    if not -90.0 <= latitude <= 90.0:
        raise ValueError("latitude must be between -90 and 90 degrees")
    if not -180.0 <= longitude <= 180.0:
        raise ValueError("longitude must be between -180 and 180 degrees")
    return latitude, longitude


def _model(name: str) -> tuple[str, _Model]:
    key = str(name).strip().lower()
    if key == "ruc":
        raise ModelUnavailableError(
            "RUC ended in 2012 and its public Soundings service was retired in 2024; "
            "use model='rap' for its operational successor"
        )
    try:
        return key, _MODELS[key]
    except KeyError as exc:
        choices = ", ".join(available_models())
        raise ModelUnavailableError(f"unsupported model {name!r}; choose one of: {choices}") from exc


def _cycles(start: datetime, end: datetime, hours: Iterable[int]) -> list[datetime]:
    start = _as_utc(start).replace(minute=0, second=0, microsecond=0)
    end = _as_utc(end).replace(minute=0, second=0, microsecond=0)
    if end < start:
        raise ValueError("end must not precede start")
    allowed = set(hours)
    result: list[datetime] = []
    cursor = start
    while cursor <= end:
        if cursor.hour in allowed:
            result.append(cursor)
        cursor += timedelta(hours=1)
    return result


def _url(config: _Model, cycle: datetime, forecast_hour: int, latitude: float, longitude: float) -> str:
    width = config.half_width
    query: list[tuple[str, str]] = [
        ("file", config.filename(cycle, forecast_hour)),
        ("all_lev", "on"),
        *((f"var_{variable}", "on") for variable in _VARIABLES),
        ("subregion", ""),
        ("toplat", f"{min(90.0, latitude + width):.4f}"),
        ("leftlon", f"{longitude - width:.4f}"),
        ("rightlon", f"{longitude + width:.4f}"),
        ("bottomlat", f"{max(-90.0, latitude - width):.4f}"),
        ("dir", f"/{config.directory(cycle)}"),
    ]
    return f"{NOMADS_BASE_URL}/{config.endpoint}?{urlencode(query)}"


def _fetch(url: str, timeout: float) -> bytes:
    request = Request(url, headers={"User-Agent": "gv-tools-upper-air/0.32"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except (HTTPError, URLError, TimeoutError) as exc:
        raise SoundingDownloadError(f"NOAA NOMADS request failed: {exc}") from exc
    if len(payload) < 16 or not payload.startswith(b"GRIB"):
        message = payload[:200].decode("utf-8", errors="replace").strip()
        raise SoundingDownloadError(
            "NOAA NOMADS did not return GRIB2 data"
            + (f": {message}" if message else "")
        )
    return payload


def _latest_candidates(config: _Model, now: datetime, lookback_hours: int) -> list[datetime]:
    if lookback_hours < 1:
        raise ValueError("latest_lookback_hours must be at least 1")
    end = _as_utc(now).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=lookback_hours - 1)
    return list(reversed(_cycles(start, end, config.cycle_hours)))


def download_model_soundings(
    latitude: float,
    longitude: float,
    *,
    model: str = "rap",
    output_dir: str | Path = ".",
    latest: bool = False,
    when: datetime | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    forecast_hour: int = 0,
    overwrite: bool = False,
    timeout: float = 60.0,
    pause: float = 0.25,
    latest_lookback_hours: int = 12,
    _now: datetime | None = None,
) -> list[DownloadedSounding]:
    """Download one or more model upper-air profiles as subsetted GRIB2 files.

    Select exactly one mode: ``latest=True``, ``when=<UTC datetime>``, or both
    ``start`` and ``end`` for an inclusive range. Naive datetimes are treated as
    UTC. Range requests include model cycles supported by the selected model;
    RAP and HRRR are hourly, while GFS and NAM use 00/06/12/18 UTC cycles.

    ``forecast_hour=0`` downloads analyses. A positive forecast hour downloads
    that lead from every selected initialization cycle. NOMADS normally keeps
    only recent operational data, so old cycles can return
    :class:`SoundingDownloadError`.
    """

    latitude, longitude = _validate_location(latitude, longitude)
    model_name, config = _model(model)
    if not isinstance(forecast_hour, int) or forecast_hour < 0:
        raise ValueError("forecast_hour must be a non-negative integer")
    modes = int(bool(latest)) + int(when is not None) + int(start is not None or end is not None)
    if modes != 1:
        raise ValueError("select exactly one of latest=True, when=..., or start=... and end=...")
    if (start is None) != (end is None):
        raise ValueError("range mode requires both start and end")

    if latest:
        now = _now or datetime.now(_UTC)
        candidates = _latest_candidates(config, now, latest_lookback_hours)
    elif when is not None:
        cycle = _as_utc(when)
        if cycle.minute or cycle.second or cycle.microsecond:
            raise ValueError("when must identify an exact UTC model cycle hour")
        if cycle.hour not in config.cycle_hours:
            hours = ", ".join(f"{hour:02d}Z" for hour in config.cycle_hours)
            raise ValueError(f"{model_name.upper()} cycles are available at {hours}")
        candidates = [cycle]
    else:
        candidates = _cycles(start, end, config.cycle_hours)  # type: ignore[arg-type]
        if not candidates:
            raise ValueError("the range does not contain a model cycle")

    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    downloaded: list[DownloadedSounding] = []
    failures: list[str] = []
    for index, cycle in enumerate(candidates):
        valid = cycle + timedelta(hours=forecast_hour)
        filename = (
            f"{model_name}_{cycle:%Y%m%d_%H}z_f{forecast_hour:03d}_"
            f"{latitude:+08.3f}_{longitude:+09.3f}.grib2"
        )
        path = destination / filename
        url = _url(config, cycle, forecast_hour, latitude, longitude)
        if not path.exists() or overwrite:
            try:
                payload = _fetch(url, timeout)
            except SoundingDownloadError as exc:
                failures.append(f"{cycle:%Y-%m-%d %HZ}: {exc}")
                if latest:
                    continue
                raise
            path.write_bytes(payload)
        downloaded.append(
            DownloadedSounding(
                model_name, cycle, forecast_hour, valid, latitude, longitude, path, url
            )
        )
        if latest:
            break
        if pause and index + 1 < len(candidates):
            time.sleep(pause)

    if latest and not downloaded:
        detail = "; ".join(failures[-3:])
        raise SoundingDownloadError(
            f"no recent {model_name.upper()} cycle was available"
            + (f" ({detail})" if detail else "")
        )
    return downloaded
