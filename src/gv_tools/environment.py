"""Dependency availability checks that work before optional packages are installed."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from importlib import import_module
import re


DEPENDENCY_GROUPS = {
    "required": {"numpy": "1.24", "pandas": "2.0", "xarray": "2023.1"},
    "parsivel": {"process-parsivel": "1.2.1"},
    "radar": {"arm-pyart": "2.1", "xradar": "0.10"},
    "netcdf": {"h5netcdf": "1.3", "h5py": "3.10"},
    "plot": {"matplotlib": "3.7"},
    "notebook": {"jupyterlab": "4", "ipykernel": "6"},
}


def _version_key(value: str) -> tuple[int, ...]:
    """Extract the numeric release portion without requiring packaging."""
    return tuple(int(part) for part in re.match(r"\d+(?:\.\d+)*", value).group().split("."))


def dependency_report(groups=("required", "parsivel", "netcdf")) -> list[dict[str, str | bool]]:
    """Return installed versions for the selected dependency groups."""
    report = []
    for group in groups:
        if group not in DEPENDENCY_GROUPS:
            raise ValueError(f"unknown dependency group: {group}")
        for package, minimum in DEPENDENCY_GROUPS[group].items():
            try:
                installed = version(package)
            except PackageNotFoundError:
                # Process Parsivel is bundled in the unified GV Tools wheel.
                module_name = package.replace("-", "_")
                try:
                    installed = str(import_module(module_name).__version__)
                except (ImportError, AttributeError):
                    installed = "not installed"
            available = installed != "not installed"
            compatible = available and _version_key(installed) >= _version_key(minimum)
            report.append(
                {
                    "group": group,
                    "package": package,
                    "minimum": minimum,
                    "installed": installed,
                    "available": available,
                    "compatible": compatible,
                }
            )
    return report
