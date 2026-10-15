"""Orchestrate daily PIERS processing across all configured gauges."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from .parsing import parse_piers_files
from .plotting import generate_gauge_plots
from .platform_plotting import (
    create_platform_fallback,
    generate_platform_plot,
    normalize_platform_type,
)
from .processing import get_bucket_tips, summarize_gauge_metadata


def load_locations(excel_path: str | Path) -> pd.DataFrame:
    """Load gauge rows, excluding blanks and the ``LastUpdate`` footer."""
    location_file = Path(excel_path).expanduser().resolve()
    if not location_file.is_file():
        raise FileNotFoundError(f"Location workbook does not exist: {location_file}")
    locations = pd.read_excel(location_file)
    if "PIERS Station Name" not in locations.columns:
        raise ValueError("Location workbook lacks 'PIERS Station Name'")
    station_names = locations["PIERS Station Name"].astype("string").str.strip()
    valid = station_names.notna() & station_names.ne("")
    valid &= ~station_names.str.casefold().str.startswith("lastupdate", na=False)
    return locations.loc[valid].copy()


def _bias_percent(rainfall_a_mm: float, rainfall_b_mm: float) -> float:
    """Preserve the established PIERS A-referenced bias calculation."""
    if rainfall_a_mm > 0:
        return 100.0 * (rainfall_a_mm - rainfall_b_mm) / rainfall_a_mm
    if rainfall_b_mm > 0:
        return 100.0 * (rainfall_b_mm - rainfall_a_mm) / rainfall_b_mm
    return 0.0


def _records_for_date(dataframe: pd.DataFrame, data_date: date) -> pd.DataFrame:
    """Return only records timestamped within the requested calendar date."""
    timestamps = pd.to_datetime(dataframe.index, errors="coerce")
    start = pd.Timestamp(data_date)
    end = start + pd.Timedelta(days=1)
    valid = timestamps.notna() & (timestamps >= start) & (timestamps < end)
    result = dataframe.loc[valid].copy()
    result.index = timestamps[valid]
    return result.sort_index(kind="stable")


def build_daily_report(
    data_date: date,
    locations: pd.DataFrame,
    input_base_dir: str | Path,
    *,
    continue_on_gauge_error: bool = True,
    plot_root: str | Path | None = None,
    publish_plots: bool = False,
    ingest_mode: str = "daily",
    input_paths: list[str | Path] | None = None,
) -> pd.DataFrame:
    """Build the full finalized Daily_DF without writing intermediate files."""
    base_dir = Path(input_base_dir).expanduser().resolve()

    gauge_ids = locations["PIERS Station Name"].dropna().astype(str).str.strip()
    rows: list[pd.DataFrame] = []
    gauge_errors: list[str] = []
    platform_issues: list[str] = []

    for gauge_id in gauge_ids:
        input_dir = (
            base_dir
            / gauge_id
            / str(data_date.year)
            / f"{data_date.month:02d}"
            / f"{data_date.day:02d}"
        )
        try:
            if ingest_mode not in {"daily", "packets"}:
                raise ValueError("ingest_mode must be 'daily' or 'packets'")
            if input_paths:
                gauge_inputs = [
                    path for path in input_paths
                    if Path(path).name.upper().startswith(gauge_id.upper())
                ]
                if not gauge_inputs:
                    raise FileNotFoundError("No explicitly supplied file for gauge")
            elif ingest_mode == "daily":
                gauge_inputs = [
                    input_dir
                    / f"{gauge_id}_TB_{data_date.year:04d}"
                    f"{data_date.month:02d}{data_date.day:02d}_daily.csv"
                ]
            else:
                gauge_inputs = [input_dir]
            metadata_df, tip_data = parse_piers_files(gauge_inputs, gauge_id)
            metadata_df = _records_for_date(metadata_df, data_date)
            tip_data = _records_for_date(tip_data, data_date)
            tips_a_df = get_bucket_tips(tip_data, "TB_A_tips")
            tips_b_df = get_bucket_tips(tip_data, "TB_B_tips")
            summary = summarize_gauge_metadata(locations, metadata_df)
            platform_type = normalize_platform_type(summary.at[0, "Gauge type"])

            tips_a = int(tips_a_df["Single_Tip"].sum())
            tips_b = int(tips_b_df["Single_Tip"].sum())
            rain_tip_a = float(summary.at[0, "Rain_Tip_A"])
            rain_tip_b = float(summary.at[0, "Rain_Tip_B"])
            rainfall_a_mm = tips_a * rain_tip_a
            rainfall_b_mm = tips_b * rain_tip_b

            if plot_root is not None:
                gauge_plots = generate_gauge_plots(
                    gauge_id,
                    data_date,
                    metadata_df,
                    tip_data,
                    station_location=summary.at[0, "Station Location"],
                    rain_tip_a_mm=rain_tip_a,
                    rain_tip_b_mm=rain_tip_b,
                    publish=publish_plots,
                    plot_root=plot_root,
                )
                if platform_type != "PIERS":
                    try:
                        generate_platform_plot(
                            gauge_id,
                            platform_type,
                            data_date,
                            input_dir,
                            tip_data,
                            station_location=summary.at[0, "Station Location"],
                            rain_tip_a_mm=rain_tip_a,
                            rain_tip_b_mm=rain_tip_b,
                            plot_root=plot_root,
                        )
                    except (FileNotFoundError, OSError, UnicodeError, ValueError, RuntimeError) as exc:
                        create_platform_fallback(
                            gauge_plots["rain"], gauge_id, platform_type,
                            data_date, plot_root, reason=str(exc),
                        )
                        platform_issues.append(
                            f"{gauge_id}: {platform_type} instrument plot contains "
                            f"an issue notice ({exc})"
                        )

            summary["Tips_A"] = tips_a
            summary["Tips_B"] = tips_b
            summary["Accum_A [mm]"] = rainfall_a_mm
            summary["Accum_B [mm]"] = rainfall_b_mm
            summary["Accum_A [in]"] = rainfall_a_mm / 25.4
            summary["Accum_B [in]"] = rainfall_b_mm / 25.4
            summary["Bias [%]"] = _bias_percent(rainfall_a_mm, rainfall_b_mm)
            rows.append(summary)
        except (FileNotFoundError, OSError, UnicodeError, ValueError) as exc:
            message = f"{gauge_id}: {exc}"
            if not continue_on_gauge_error:
                raise RuntimeError(message) from exc
            gauge_errors.append(message)

    if platform_issues or gauge_errors:
        print("PIERS report data notices:")
        for issue in platform_issues:
            print(f"  - {issue}")
        for issue in gauge_errors:
            print(f"  - Gauge skipped: {issue}")
    if not rows:
        raise RuntimeError("No gauges were processed successfully")

    return pd.concat(rows, ignore_index=True)
