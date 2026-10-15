"""Publish completed PIERS reports."""

from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path


def publish_with_scp(
    report_path: str | Path,
    *,
    user: str,
    server: str,
    remote_directory: str,
) -> None:
    """Copy one completed report with the native ``scp`` command."""
    report = Path(report_path).expanduser().resolve()
    if not report.is_file():
        raise FileNotFoundError(f"Report does not exist: {report}")
    destination = f"{user}@{server}:{remote_directory.rstrip('/')}/"
    subprocess.run(["scp", str(report), destination], check=True)


def publish_report_and_plots(
    report_path: str | Path,
    plot_root: str | Path,
    data_date: date,
    *,
    user: str,
    server: str,
    remote_report_directory: str = "/d1/wallops-prf/Gauge",
    remote_plot_directory: str = "/d1/wallops-prf/Gauge/Plots",
) -> None:
    """Copy the HTML report and one day's PNG plots to the web server."""
    report = Path(report_path).expanduser().resolve()
    if not report.is_file():
        raise FileNotFoundError(f"Report does not exist: {report}")

    plot_root = Path(plot_root).expanduser().resolve()
    remote_host = f"{user}@{server}"
    dated_directories: list[tuple[Path, str]] = []
    required_categories = ("Rain", "Battery", "RSSI")
    for category in (*required_categories, "Platform"):
        relative_date = (
            Path(category)
            / f"{data_date.year:04d}"
            / f"{data_date.month:02d}"
            / f"{data_date.day:02d}"
        )
        local_directory = plot_root / relative_date
        image_files = sorted(local_directory.glob("*.png"))
        if not image_files and category in required_categories:
            raise FileNotFoundError(
                f"No plot images found for publication: {local_directory}"
            )
        if not image_files:
            continue
        remote_directory = (
            f"{remote_plot_directory.rstrip('/')}/{relative_date.as_posix()}"
        )
        dated_directories.append((local_directory, remote_directory))

    remote_directories = [
        remote_report_directory.rstrip("/"),
        *(remote for _, remote in dated_directories),
    ]
    subprocess.run(
        ["ssh", remote_host, "mkdir", "-p", *remote_directories],
        check=True,
    )
    subprocess.run(
        [
            "scp",
            str(report),
            f"{remote_host}:{remote_report_directory.rstrip('/')}/",
        ],
        check=True,
    )
    for local_directory, remote_directory in dated_directories:
        image_files = sorted(local_directory.glob("*.png"))
        subprocess.run(
            [
                "scp",
                *(str(image) for image in image_files),
                f"{remote_host}:{remote_directory}/",
            ],
            check=True,
        )
