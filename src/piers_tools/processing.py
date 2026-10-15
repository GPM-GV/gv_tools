"""Transform parsed PIERS records into daily gauge statistics."""

from __future__ import annotations

import numpy as np
import pandas as pd


REPORT_GROUP_ORDER = ["GPM", "WFF", "PCMK", "IPMSI", "INCUS"]


def id_tips(values: list[float]) -> list[int]:
    """Count positive counter increments while ignoring resets and duplicates."""
    if not values:
        return []
    tips = [0]
    for previous, current in zip(values, values[1:]):
        try:
            increment = float(current) - float(previous)
        except (TypeError, ValueError):
            increment = 0.0
        tips.append(int(increment) if np.isfinite(increment) and increment > 0 else 0)
    return tips


def get_bucket_tips(data_df: pd.DataFrame, bucket: str) -> pd.DataFrame:
    """Return one bucket's records with a derived ``Single_Tip`` column."""
    required = {"station_name", "measurement", "value", "quality"}
    missing = sorted(required.difference(data_df.columns))
    if missing:
        raise ValueError(f"Tip data is missing required columns: {missing}")

    result = data_df.loc[
        data_df["measurement"].eq(bucket),
        ["station_name", "measurement", "value", "quality"],
    ].copy()
    result = result.rename(
        columns={
            "station_name": "GaugeID",
            "measurement": "Bucket",
            "value": "Tip_#",
            "quality": "Quality",
        }
    )
    result = result.sort_index(kind="stable")
    result["Single_Tip"] = np.asarray(id_tips(result["Tip_#"].tolist()))
    return result


def summarize_gauge_metadata(
    location_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
    rain_tip_column: str | None = None,
) -> pd.DataFrame:
    """Return location and metadata statistics for exactly one gauge."""
    if metadata_df.empty:
        raise ValueError("The metadata DataFrame contains no records")

    required_metadata = {"station_name", "rssi", "battery_voltage"}
    missing_metadata = sorted(required_metadata.difference(metadata_df.columns))
    if missing_metadata:
        raise ValueError(f"Metadata is missing required columns: {missing_metadata}")
    if "PIERS Station Name" not in location_df.columns:
        raise ValueError("Location table lacks 'PIERS Station Name'")

    station_names = (
        metadata_df["station_name"].dropna().astype(str).str.strip().unique()
    )
    if len(station_names) != 1:
        raise ValueError(
            "Expected metadata for exactly one station; "
            f"found {station_names.tolist()}"
        )
    gauge_id = station_names[0].split("_", maxsplit=1)[0]

    location_ids = (
        location_df["PIERS Station Name"].astype(str).str.strip().str.upper()
    )
    matches = location_df.loc[location_ids.eq(gauge_id.upper())]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one location for {gauge_id}; found {len(matches)}"
        )
    location = matches.iloc[0]

    if rain_tip_column is None:
        rain_tip_column = location_df.columns[-1]
    if rain_tip_column not in location_df.columns:
        raise ValueError(f"Unknown rain-tip column: {rain_tip_column}")

    rain_tip_parts = str(location[rain_tip_column]).strip().split(",")
    if len(rain_tip_parts) != 2:
        raise ValueError(
            f"Invalid rain-tip value for {gauge_id}: {location[rain_tip_column]!r}"
        )
    try:
        rain_tip_a, rain_tip_b = (float(part.strip()) for part in rain_tip_parts)
    except ValueError as exc:
        raise ValueError(f"Rain-tip values for {gauge_id} must be numeric") from exc

    rssi = pd.to_numeric(metadata_df["rssi"], errors="coerce")
    voltage = pd.to_numeric(metadata_df["battery_voltage"], errors="coerce")
    timestamps = pd.to_datetime(metadata_df.index, errors="coerce")

    return pd.DataFrame(
        [
            {
                "Group": (
                    ""
                    if "Group" not in location.index or pd.isna(location["Group"])
                    else str(location["Group"]).strip().upper()
                ),
                "Gauge type": (
                    "PIERS"
                    if "Gauge type" not in location.index
                    or pd.isna(location["Gauge type"])
                    else str(location["Gauge type"]).strip()
                ),
                "GaugeID": gauge_id,
                "Station Location": (
                    ""
                    if "Station Location" not in location.index
                    or pd.isna(location["Station Location"])
                    else str(location["Station Location"]).strip()
                ),
                "record_count": len(metadata_df),
                "start_date": timestamps.min(),
                "end_date": timestamps.max(),
                "latitude": float(location["Latitude"]),
                "longitude": float(location["Longitude"]),
                "Rain_Tip_A": rain_tip_a,
                "Rain_Tip_B": rain_tip_b,
                "battery_voltage_min": voltage.min(),
                "battery_voltage_mean": voltage.mean(),
                "battery_voltage_std": voltage.std(),
                "battery_voltage_max": voltage.max(),
                "rssi_min": rssi.min(),
                "rssi_mean": rssi.mean(),
                "rssi_std": rssi.std(),
                "rssi_max": rssi.max(),
            }
        ]
    )


REPORT_RENAME_MAP = {
    "record_count": "Packets",
    "Rain_Tip_A": "Rain/Tip_A",
    "Rain_Tip_B": "Rain/Tip_B",
    "battery_voltage_min": "Volts_min",
    "battery_voltage_max": "Volts_max",
    "rssi_min": "RSSI_min",
    "rssi_max": "RSSI_max",
    "Tips_A": "# Tips_A",
    "Tips_B": "# Tips_B",
}

REPORT_COLUMNS = [
    "Group",
    "Gauge type",
    "GaugeID",
    "Station Location",
    "latitude",
    "longitude",
    "Packets",
    "Volts_min",
    "Volts_max",
    "RSSI_min",
    "RSSI_max",
    "Rain/Tip_A",
    "Rain/Tip_B",
    "# Tips_A",
    "# Tips_B",
    "Accum_A [mm]",
    "Accum_B [mm]",
    "Accum_A [in]",
    "Accum_B [in]",
    "Bias [%]",
]


def clean_merged_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Rename, select, and order report rows by group then station name."""
    result = dataframe.rename(columns=REPORT_RENAME_MAP)
    missing = [column for column in REPORT_COLUMNS if column not in result.columns]
    if missing:
        raise ValueError(f"Merged data is missing report columns: {missing}")
    result = result.loc[:, REPORT_COLUMNS].copy()
    normalized_groups = result["Group"].fillna("").astype(str).str.strip().str.upper()
    result["Group"] = normalized_groups
    group_rank = {group: rank for rank, group in enumerate(REPORT_GROUP_ORDER)}
    result["_group_rank"] = normalized_groups.map(group_rank).fillna(
        len(REPORT_GROUP_ORDER)
    )
    result["_unknown_group"] = normalized_groups.where(
        ~normalized_groups.isin(REPORT_GROUP_ORDER), ""
    )
    result = result.sort_values(
        ["_group_rank", "_unknown_group", "GaugeID"],
        kind="stable",
    )
    return result.drop(columns=["_group_rank", "_unknown_group"]).reset_index(drop=True)
