"""Frequency-dependent radar products derived from Parsivel PSDs."""

from __future__ import annotations

import numpy as np
import pandas as pd


RADAR_BAND_FREQUENCIES_GHZ = {
    "S": 3.0,
    "C": 5.6,
    "X": 9.4,
    "Ku": 13.6,
    "K": 24.0,
    "Ka": 35.5,
}

_BAND_LOOKUP = {name.upper(): name for name in RADAR_BAND_FREQUENCIES_GHZ}
_SPEED_OF_LIGHT_MM_GHZ = 299.792458


def _normalize_bands(bands):
    if bands is None or bands == "all":
        return list(RADAR_BAND_FREQUENCIES_GHZ)
    if isinstance(bands, str):
        bands = [item.strip() for item in bands.split(",") if item.strip()]
    else:
        bands = [
            item.strip()
            for value in bands
            for item in str(value).split(",")
            if item.strip()
        ]
    if len(bands) == 1 and bands[0].lower() == "all":
        return list(RADAR_BAND_FREQUENCIES_GHZ)
    normalized = []
    for band in bands:
        try:
            normalized.append(_BAND_LOOKUP[str(band).upper()])
        except KeyError as exc:
            raise ValueError(
                f"Unknown radar band {band!r}; choose from {list(RADAR_BAND_FREQUENCIES_GHZ)}"
            ) from exc
    return list(dict.fromkeys(normalized))


def _diameter_widths(diameters, diameter_widths=None):
    if diameter_widths is not None:
        widths = np.asarray(diameter_widths, dtype=float)
    else:
        centers = np.asarray(diameters, dtype=float)
        if len(centers) == 1:
            widths = np.array([max(abs(centers[0]) * 0.1, 0.1)])
        else:
            edges = np.concatenate((
                [centers[0] - (centers[1] - centers[0]) / 2],
                (centers[:-1] + centers[1:]) / 2,
                [centers[-1] + (centers[-1] - centers[-2]) / 2],
            ))
            widths = np.diff(edges)
    if widths.shape != np.asarray(diameters).shape or np.any(widths <= 0):
        raise ValueError("diameter_widths must contain one positive width per PSD column")
    return widths


def compute_band_reflectivity(
    psd: pd.DataFrame,
    *,
    bands="all",
    water_temperature=20.0,
    permittivity_model="Liebe1991",
    diameter_widths=None,
    frequencies=None,
    minimum_dbz=None,
):
    """Compute intrinsic liquid-water Mie equivalent reflectivity by radar band.

    The PSD must have drop-diameter centers in millimetres as columns and
    concentrations in m^-3 mm^-1. Drops are modeled as homogeneous spheres.
    Results exclude atmospheric/rain-path attenuation and nonspherical-drop
    polarization effects.
    """
    if not isinstance(psd, pd.DataFrame) or psd.empty:
        raise ValueError("psd must be a non-empty pandas DataFrame")
    selected = _normalize_bands(bands)
    frequency_map = dict(RADAR_BAND_FREQUENCIES_GHZ)
    if frequencies:
        for band, frequency in frequencies.items():
            canonical = _normalize_bands([band])[0]
            frequency_map[canonical] = float(frequency)
    if any(not np.isfinite(frequency_map[band]) or frequency_map[band] <= 0 for band in selected):
        raise ValueError("Radar frequencies must be finite and positive")
    diameters = psd.columns.to_numpy(dtype=float)
    if np.any(diameters <= 0) or not np.all(np.diff(diameters) > 0):
        raise ValueError("PSD diameter columns must be positive and increasing")
    concentrations = psd.to_numpy(dtype=float)
    concentrations = np.where(np.isfinite(concentrations) & (concentrations > 0), concentrations, 0.0)
    widths = _diameter_widths(diameters, diameter_widths)
    try:
        import miepython
        from disdrodb.scattering.permittivity import (
            get_rayleigh_dielectric_factor,
            get_refractive_index,
        )
    except ImportError as exc:
        raise RuntimeError(
            "Band reflectivity requires miepython and disdrodb; install with "
            "python -m pip install miepython disdrodb"
        ) from exc
    output = pd.DataFrame(index=psd.index)
    for band in selected:
        frequency = frequency_map[band]
        wavelength = _SPEED_OF_LIGHT_MM_GHZ / frequency
        refractive_index = complex(np.asarray(get_refractive_index(
            temperature=water_temperature,
            frequency=frequency,
            permittivity_model=permittivity_model,
        )).item())
        # miepython uses n - ik; DISDRODB permittivity models return n + ik.
        mie_index = complex(refractive_index.real, -abs(refractive_index.imag))
        kw_squared = float(np.asarray(get_rayleigh_dielectric_factor(refractive_index)).item())
        qback = np.array([
            miepython.efficiencies(mie_index, diameter, wavelength)[2]
            for diameter in diameters
        ])
        sigma_back_mm2 = np.pi * (diameters / 2) ** 2 * qback
        eta_mm2_m3 = (concentrations * widths[None, :] * sigma_back_mm2[None, :]).sum(axis=1)
        ze = wavelength**4 / (np.pi**5 * kw_squared) * eta_mm2_m3
        dbz = np.full_like(ze, np.nan, dtype=float)
        positive = ze > 0
        dbz[positive] = 10 * np.log10(ze[positive])
        if minimum_dbz is not None:
            dbz[positive] = np.maximum(dbz[positive], float(minimum_dbz))
        output[f"Z_{band}"] = ze
        output[f"dBZ_{band}"] = dbz
    output.attrs = {
        "model": "Mie homogeneous liquid-water spheres",
        "water_temperature_C": float(water_temperature),
        "permittivity_model": permittivity_model,
        "frequencies_GHz": {band: frequency_map[band] for band in selected},
        "attenuation_included": False,
    }
    return output


def add_band_reflectivities(parms, psd, **kwargs):
    """Return a copy of ``parms`` with band-specific Z and dBZ columns added."""
    if not isinstance(parms, pd.DataFrame) or parms.empty:
        raise ValueError("parms must be a non-empty pandas DataFrame")
    if not parms.index.equals(psd.index):
        raise ValueError("parms and psd must have identical time indexes")
    radar = compute_band_reflectivity(psd, **kwargs)
    result = parms.copy()
    for column in radar.columns:
        result[column] = radar[column]
    result.attrs = {**getattr(parms, "attrs", {}), "band_reflectivity": radar.attrs}
    return result
