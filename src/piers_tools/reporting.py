"""Create the PIERS daily HTML table."""

from __future__ import annotations

from datetime import date, datetime, timezone
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd

from .processing import REPORT_GROUP_ORDER
from .platform_plotting import platform_plot_details


INPUT_ALIASES = {
    "record_count": "Packets",
    "battery_voltage_min": "Volts_min",
    "battery_voltage_max": "Volts_max",
    "rssi_min": "RSSI_min",
    "rssi_max": "RSSI_max",
    "# Tips_A": "Tips_A",
    "# Tips_B": "Tips_B",
}

INPUT_COLUMNS = [
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
    "Tips_A",
    "Tips_B",
    "Accum_A [mm]",
    "Accum_B [mm]",
    "Accum_A [in]",
    "Accum_B [in]",
    "Bias [%]",
]

OUTPUT_COLUMNS = [
    "Group",
    "GaugeID",
    "Station Location",
    "Packets",
    "Voltage",
    "RSSI",
    "Tips A/B",
    "Accum_A [mm]",
    "Accum_B [mm]",
    "Accum_A [in]",
    "Accum_B [in]",
    "Bias [%]",
]

ACCUM_COLUMNS = [
    "Accum_A [mm]",
    "Accum_B [mm]",
    "Accum_A [in]",
    "Accum_B [in]",
]

HEADER_STYLE = (
    "background-color:#1F4E78;color:#FFFFFF;font-weight:bold;"
    "padding:6px 10px;border:1px solid #B7C9D6;text-align:center"
)
GROUP_HEADER_STYLE = (
    "background-color:#D9EAF7;color:#1F1F1F;font-weight:bold;"
    "padding:6px 10px;border:1px solid #9FBAD0;text-align:left"
)
CELL_STYLE = "padding:5px 10px;border:1px solid #D9E2E8"
LIGHT_RED = "background-color:#FFC7CE"
LIGHT_GREEN = "background-color:#C6EFCE"
BRIGHT_RED = "background-color:#FF0000;color:#FFFFFF"


def _display_value(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, (float, np.floating)):
        return f"{value:.2f}"
    return str(value)


def _display_gauge_id(gauge_id: object, gauge_type: object) -> str:
    """Return the visible ID suffix implied by the location Gauge type."""
    canonical_id = str(gauge_id).strip()
    normalized_type = str(gauge_type).strip().upper()
    suffix = {"PIERS+": "+", "PIERS++": "++"}.get(normalized_type, "")
    return f"{canonical_id}{suffix}"


def _plot_href(
    plot_link_root: str,
    category: str,
    gauge_id: str,
    coverage_date: date,
    suffix: str,
) -> str:
    root = plot_link_root.rstrip("/")
    filename = (
        f"{gauge_id}_{coverage_date.year:04d}_"
        f"{coverage_date.month:02d}{coverage_date.day:02d}_{suffix}.png"
    )
    return (
        f"{root}/{category}/{coverage_date.year:04d}/"
        f"{coverage_date.month:02d}/{coverage_date.day:02d}/{filename}"
    )


def gauge_report_to_html(
    dataframe: pd.DataFrame,
    output_path: str | Path = "Gauge_Report.html",
    *,
    coverage_date: date,
    plot_link_root: str = "../Plots",
    enable_maps: bool = False,
) -> Path:
    """Write a highlighted HTML table for one explicit data-coverage date."""
    report = dataframe.rename(
        columns={
            source: destination
            for source, destination in INPUT_ALIASES.items()
            if source in dataframe.columns and destination not in dataframe.columns
        }
    )
    missing = [column for column in INPUT_COLUMNS if column not in report.columns]
    if missing:
        raise ValueError(f"Missing required report columns: {missing}")

    report = report.loc[:, INPUT_COLUMNS].copy()
    report["Group"] = report["Group"].fillna("").astype(str).str.strip().str.upper()
    group_rank = {group: rank for rank, group in enumerate(REPORT_GROUP_ORDER)}
    report["_group_rank"] = report["Group"].map(group_rank).fillna(
        len(REPORT_GROUP_ORDER)
    )
    report["_unknown_group"] = report["Group"].where(
        ~report["Group"].isin(REPORT_GROUP_ORDER), ""
    )
    report = report.sort_values(
        ["_group_rank", "_unknown_group", "GaugeID"], kind="stable"
    ).drop(columns=["_group_rank", "_unknown_group"]).reset_index(drop=True)
    text_columns = {"Group", "Gauge type", "GaugeID", "Station Location"}
    numeric_columns = [
        column for column in INPUT_COLUMNS if column not in text_columns
    ]
    numeric = report.loc[:, numeric_columns].apply(pd.to_numeric, errors="coerce")
    accum_maxima = numeric.loc[:, ACCUM_COLUMNS].max()

    generated_local = datetime.now().astimezone()
    generated_utc = generated_local.astimezone(timezone.utc)
    lines = ["<TABLE>"]
    lines.append(
        '  <CAPTION style="caption-side:top;text-align:left;font-weight:bold;'
        'padding:6px 0">'
        f"<DIV>Report Generated: Local "
        f"{escape(generated_local.strftime('%Y-%m-%d %H:%M:%S %Z'))}"
        f" or "
        f"{escape(generated_utc.strftime('%Y-%m-%d %H:%M:%S UTC'))}</DIV>"
        f"<DIV>Data Coverage for {coverage_date.isoformat()}</DIV>"
        "</CAPTION>"
    )
    lines.extend(["  <THEAD>", "    <TR>"])
    for column in OUTPUT_COLUMNS:
        lines.append(f'      <TH style="{HEADER_STYLE}">{escape(column)}</TH>')
    lines.extend(["    </TR>", "  </THEAD>", "  <TBODY>"])

    previous_group: str | None = None
    for row_position, (_, row) in enumerate(report.iterrows()):
        current_group = str(row["Group"]).strip()
        if current_group != previous_group:
            group_label = current_group or "Unassigned"
            lines.extend(
                [
                    '    <TR class="group-header">',
                    f'      <TH colspan="{len(OUTPUT_COLUMNS)}" '
                    f'style="{GROUP_HEADER_STYLE}">{escape(group_label)}</TH>',
                    "    </TR>",
                ]
            )
            previous_group = current_group
        lines.append("    <TR>")
        gauge_id = str(row["GaugeID"])
        gauge_type = row["Gauge type"]
        for column in OUTPUT_COLUMNS:
            raw_value = row[column] if column in report.columns else ""
            text = _display_value(raw_value)
            extra_style = ""

            if column == "GaugeID":
                text = _display_gauge_id(gauge_id, gauge_type)
            elif column == "Packets":
                count = numeric["Packets"].iloc[row_position]
                text = f"{_display_value(count)}/96"
                if pd.notna(count) and count < 45:
                    extra_style = LIGHT_RED
            elif column == "Voltage":
                minimum = numeric["Volts_min"].iloc[row_position]
                maximum = numeric["Volts_max"].iloc[row_position]
                text = f"{_display_value(minimum)}/{_display_value(maximum)}"
                if (
                    pd.notna(minimum) and minimum < 12
                ) or (pd.notna(maximum) and maximum < 12):
                    extra_style = LIGHT_RED
            elif column == "RSSI":
                minimum = numeric["RSSI_min"].iloc[row_position]
                maximum = numeric["RSSI_max"].iloc[row_position]
                text = f"{_display_value(minimum)}/{_display_value(maximum)}"
            elif column == "Tips A/B":
                tips_a = numeric["Tips_A"].iloc[row_position]
                tips_b = numeric["Tips_B"].iloc[row_position]
                text = f"{_display_value(tips_a)}/{_display_value(tips_b)}"
            elif column in ACCUM_COLUMNS:
                value = numeric[column].iloc[row_position]
                if pd.notna(value) and value == accum_maxima[column]:
                    extra_style = LIGHT_GREEN
            elif column == "Bias [%]":
                bias = numeric["Bias [%]"].iloc[row_position]
                if pd.notna(bias) and (bias > 10 or bias < -10):
                    extra_style = BRIGHT_RED

            style = f"{CELL_STYLE};{extra_style}" if extra_style else CELL_STYLE
            alignment = "left" if column in text_columns else "right"
            cell_html = escape(text)
            if enable_maps and column == "Station Location":
                latitude = numeric["latitude"].iloc[row_position]
                longitude = numeric["longitude"].iloc[row_position]
                if pd.notna(latitude) and pd.notna(longitude):
                    map_url = (
                        "https://maps.google.com/maps?output=embed&z=16&q="
                        f"{latitude:.6f},{longitude:.6f}"
                    )
                    escaped_map_url = escape(map_url, quote=True)
                    cell_html = (
                        f'<A href="{escaped_map_url}" target="_blank" '
                        'rel="noopener noreferrer" '
                        "onclick=\"window.open(this.href,'stationMap',"
                        "'width=700,height=500,resizable=yes,scrollbars=yes');"
                        f'return false;\">{cell_html}</A>'
                    )
            link_details = {
                "Voltage": ("Battery", "voltage"),
                "RSSI": ("RSSI", "rssi"),
            }
            if column == "GaugeID":
                link_details[column] = platform_plot_details(gauge_type)
            if column in link_details:
                category, suffix = link_details[column]
                href = _plot_href(
                    plot_link_root,
                    category,
                    gauge_id,
                    coverage_date,
                    suffix,
                )
                cell_html = (
                    f'<A href="{escape(href, quote=True)}" target="_blank" '
                    f'rel="noopener noreferrer">{cell_html}</A>'
                )
            lines.append(
                f'      <TD style="{style};text-align:{alignment}">'
                f"{cell_html}</TD>"
            )
        lines.append("    </TR>")

    lines.extend(["  </TBODY>", "</TABLE>"])
    output_path = Path(output_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def gauge_csv_to_html(
    csv_path: str | Path,
    output_path: str | Path | None = None,
    *,
    coverage_date: date,
    plot_link_root: str = "../Plots",
    enable_maps: bool = False,
) -> Path:
    """Read a daily report CSV and create its highlighted HTML table."""
    csv_path = Path(csv_path).expanduser().resolve()
    if output_path is None:
        output_path = csv_path.with_suffix(".html")
    return gauge_report_to_html(
        pd.read_csv(csv_path),
        output_path,
        coverage_date=coverage_date,
        plot_link_root=plot_link_root,
        enable_maps=enable_maps,
    )
