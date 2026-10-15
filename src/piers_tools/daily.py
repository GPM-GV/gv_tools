"""One-day PIERS++ discovery, ingestion, processing, and output orchestration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import json
from pathlib import Path
import shutil
import tempfile

import pandas as pd

from .aio import aio_one_minute, read_aio_day


DEFAULT_GAUGE_STATUS_PATH = Path(
    "/Users/dwolff/PIERS_Reporting/PIERS_gauges_status.xlsx"
)
DEFAULT_INPUT_ROOT = Path("/Volumes/TBH/distro/PIERS_Gauges_Daily")


@dataclass(frozen=True)
class DailyResult:
    site: str
    day: date
    input_dir: Path
    output_dir: Path
    files: dict[str, int]
    rows: dict[str, int]
    rejected_rows: dict[str, int]
    missing_instruments: tuple[str, ...]
    gauge_tip_mm: tuple[float, float] | None
    aio_configuration: str


def _write(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, date_format="%Y-%m-%dT%H:%M:%S")


def _prefer_daily_files(paths: list[Path]) -> list[Path]:
    """Prefer consolidated ``*_daily.*`` files over packet files when present."""
    daily = [path for path in paths if path.stem.endswith("_daily")]
    return daily or paths


def _read_gauge(paths: list[Path], site: str):
    try:
        from .parsing import parse_one_file
    except ImportError as exc:
        raise RuntimeError("Gauge processing requires the piers-reporting package") from exc
    metadata_rows = []
    observation_rows = []
    for path in paths:
        metadata, observations = parse_one_file(path)
        metadata_rows.append(metadata)
        observation_rows.extend(observations)
    metadata = pd.DataFrame(metadata_rows).set_index("timestamp").sort_index(kind="stable")
    observations = pd.DataFrame(observation_rows).set_index("timestamp").sort_index(kind="stable")
    return metadata.reset_index(), observations.reset_index()


def _gauge_calibration(gauge_status_path, site: str):
    if gauge_status_path is None:
        return None
    from .pipeline import load_locations

    locations = load_locations(gauge_status_path)
    ids = locations["PIERS Station Name"].astype(str).str.strip().str.upper()
    matches = locations.loc[ids.eq(site.upper())]
    if len(matches) != 1:
        raise ValueError(f"Expected one calibration row for {site}; found {len(matches)}")
    parts = str(matches.iloc[0][locations.columns[-1]]).strip().split(",")
    if len(parts) != 2:
        raise ValueError(f"Invalid two-bucket Gauge tip calibration for {site}: {parts}")
    return tuple(float(part.strip()) for part in parts)


def _gauge_one_minute(observations: pd.DataFrame, calibration) -> pd.DataFrame:
    """Apply piers_reporting counter-change tip identification by minute."""
    if observations.empty:
        return pd.DataFrame(columns=["timestamp"])
    from .processing import get_bucket_tips

    source = observations.copy().set_index("timestamp").sort_index(kind="stable")
    buckets = []
    for bucket, label in (("TB_A_tips", "A"), ("TB_B_tips", "B")):
        tips = get_bucket_tips(source, bucket)
        counts = tips["Single_Tip"].resample("1min").sum().rename(f"TB_{label}_tip_count")
        buckets.append(counts)
    result = pd.concat(buckets, axis=1, join="outer").fillna(0)
    if calibration is not None:
        for label, amount in zip(("A", "B"), calibration):
            result[f"rain_{label}_mm"] = result[f"TB_{label}_tip_count"] * amount
            result[f"rain_{label}_cumulative_mm"] = result[f"rain_{label}_mm"].cumsum()
    return result.reset_index()


def _read_parsivel(paths: list[Path], site: str, stamp: date):
    try:
        from process_parsivel.core import process_input
    except ImportError as exc:
        raise RuntimeError("The bundled process_parsivel module could not be imported") from exc
    # process_input recursively accepts several suffixes, so isolate ZIPs to
    # prevent Gauge/AIO CSV packets from entering the Parsivel concatenation.
    with tempfile.TemporaryDirectory(prefix="piers_parsivel_") as staging_text:
        staging = Path(staging_text)
        for archive in paths:
            shutil.copy2(archive, staging / archive.name)
        return process_input(
            staging, site, f"{stamp.year:04d}", f"{stamp.month:02d}", f"{stamp.day:02d}",
            temp_root=staging,
        )


def process_day(
    input_root, site: str, year: int, month: int, day: int, *, output_dir="output",
    gauge_status_path=DEFAULT_GAUGE_STATUS_PATH,
):
    """Ingest a site/day using a caller-selectable gauge-location workbook."""
    stamp = date(year, month, day)
    root = Path(input_root).expanduser()
    # Accept either the common PIERS_Gauges root or an already site-specific root.
    site_root = root if root.name == site else root / site
    day_dir = site_root / f"{year:04d}" / f"{month:02d}" / f"{day:02d}"
    if not day_dir.is_dir():
        raise FileNotFoundError(f"PIERS++ day directory does not exist: {day_dir}")
    expected_prefix = f"{site}_"
    groups = {
        "gauge": sorted(day_dir.glob(f"{expected_prefix}TB_{year:04d}{month:02d}{day:02d}*.csv")),
        "parsivel": sorted(day_dir.glob(f"{expected_prefix}Parsivel_{year:04d}{month:02d}{day:02d}*.zip")),
        "wind": sorted(day_dir.glob(f"{expected_prefix}wind_{year:04d}{month:02d}{day:02d}*.csv")),
        "wx": sorted(day_dir.glob(f"{expected_prefix}WX_{year:04d}{month:02d}{day:02d}*.csv")),
    }
    groups = {name: _prefer_daily_files(paths) for name, paths in groups.items()}
    missing = [name for name, paths in groups.items() if not paths]

    target = Path(output_dir).expanduser() / site / stamp.isoformat()
    target.mkdir(parents=True, exist_ok=True)
    if groups["gauge"]:
        gauge_meta, gauge_obs = _read_gauge(groups["gauge"], site)
    else:
        gauge_meta = pd.DataFrame(columns=["timestamp", "station_name", "latitude", "longitude"])
        gauge_obs = pd.DataFrame(columns=["timestamp", "measurement", "value"])
    start = pd.Timestamp(stamp)
    stop = start + pd.Timedelta(days=1)
    gauge_obs = gauge_obs[(gauge_obs["timestamp"] >= start) & (gauge_obs["timestamp"] < stop)]
    calibration = _gauge_calibration(gauge_status_path, site) if groups["gauge"] else None
    gauge_minute = _gauge_one_minute(gauge_obs, calibration)
    wind, wx, aio, stats = read_aio_day(groups["wind"], groups["wx"])
    aio_minute = aio_one_minute(wind, wx)
    if groups["parsivel"]:
        parms, psd, moments = _read_parsivel(groups["parsivel"], site, stamp)
    else:
        parms, psd, moments = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    for frame, name in (
        (gauge_meta, "gauge_metadata.csv"), (gauge_obs, "gauge_observations.csv"),
        (gauge_minute, "gauge_one_minute.csv"),
        (wind, "aio_wind.csv"), (wx, "aio_wx.csv"), (aio, "aio_combined.csv"),
        (aio_minute, "aio_one_minute.csv"),
        (parms.reset_index(names="timestamp"), "parsivel_parameters.csv"),
        (psd.reset_index(names="timestamp"), "parsivel_psd.csv"),
        (moments.reset_index(names="timestamp"), "parsivel_moments.csv"),
    ):
        _write(frame, target / name)
    result = DailyResult(
        site, stamp, day_dir, target,
        {name: len(paths) for name, paths in groups.items()},
        {"gauge": len(gauge_obs), "wind": len(wind), "wx": len(wx),
         "aio_combined": len(aio), "aio_minutes": len(aio_minute),
         "gauge_minutes": len(gauge_minute), "parsivel_minutes": len(parms)},
        {"wind": stats["wind"].rejected_rows, "wx": stats["wx"].rejected_rows},
        tuple(missing),
        calibration,
        stats["configuration"],
    )
    manifest = asdict(result)
    manifest.update(day=stamp.isoformat(), input_dir=str(day_dir), output_dir=str(target))
    manifest["source_files"] = {name: [path.name for path in paths] for name, paths in groups.items()}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return result
