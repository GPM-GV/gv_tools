from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import numpy as np
import pytest
import xarray as xr

from gv_tools import read_mrr


MRR2_VARIABLES = {
    "MRR_H": (("time", "MRR rangegate"), [[100.0, 200.0]]),
    "MRR_TF": (("time", "MRR rangegate"), [[1.0, 1.0]]),
    "MRR_F": (("time", "MRR rangegate", "MRR spectralclass"), [[[1.0], [2.0]]]),
    "MRR_D": (("time", "MRR rangegate", "MRR spectralclass"), [[[1.0], [2.0]]]),
    "MRR_N": (("time", "MRR rangegate", "MRR spectralclass"), [[[1.0], [2.0]]]),
    "MRR_K": (("time", "MRR rangegate"), [[1.0, 2.0]]),
    "MRR_Capital_Z": (("time", "MRR rangegate"), [[1.0, 2.0]]),
    "MRR_Small_z": (("time", "MRR rangegate"), [[1.0, 2.0]]),
    "MRR_PIA": (("time", "MRR rangegate"), [[1.0, 2.0]]),
    "MRR_RR": (("time", "MRR rangegate"), [[1.0, 2.0]]),
    "MRR_LWC": (("time", "MRR rangegate"), [[1.0, 2.0]]),
    "MRR_W": (("time", "MRR rangegate"), [[1.0, 2.0]]),
}


def _write_mrr2(path):
    dataset = xr.Dataset(
        MRR2_VARIABLES,
        coords={
            "time": ("time", np.array([1784678401], dtype="int32"), {"units": "UNIX Time Stamp"}),
            "MRR rangegate": (("time", "MRR rangegate"), [[100.0, 200.0]]),
            "MRR spectralclass": [0],
        },
        attrs={"description": "MRR Averaged or Processed Data"},
    )
    dataset.to_netcdf(path, engine="scipy")


def test_reads_mrr2_netcdf_and_decodes_time(tmp_path):
    source = tmp_path / "sample.nc"
    _write_mrr2(source)

    result = read_mrr(source)

    assert isinstance(result, xr.Dataset)
    assert result.sizes == {"time": 1, "MRR rangegate": 2, "MRR spectralclass": 1}
    assert result.time.dtype == np.dtype("datetime64[ns]")
    assert result.time.values[0] == np.datetime64("2026-07-22T00:00:01")
    assert result.attrs["mrr_model"] == "MRR2"
    result.close()


def test_reads_mrr2_zip_without_retaining_archive_handle(tmp_path):
    netcdf = tmp_path / "sample.nc"
    archive = tmp_path / "sample.nc.zip"
    _write_mrr2(netcdf)
    with ZipFile(archive, "w", ZIP_DEFLATED) as output:
        output.write(netcdf, "sample.nc")

    result = read_mrr(archive)
    archive.unlink()

    assert result.MRR_RR.values.tolist() == [[1.0, 2.0]]


def test_rejects_non_mrr2_product(tmp_path):
    source = tmp_path / "other.nc"
    xr.Dataset({"rain_rate": ("time", [1.0])}).to_netcdf(source, engine="scipy")

    with pytest.raises(ValueError, match="matches neither"):
        read_mrr(source)


def test_reads_mrrpro_netcdf4_zip(tmp_path):
    pytest.importorskip("h5netcdf")
    netcdf = tmp_path / "mrrpro.nc"
    archive = tmp_path / "mrrpro.nc.zip"
    time = np.array([1784703600.0, 1784703660.0])
    shape = (2, 2)
    spectrum_shape = (2, 2, 1)
    dataset = xr.Dataset(
        {
            "Za": (("time", "range"), np.ones(shape, dtype="float32")),
            "Z": (("time", "range"), np.ones(shape)),
            "Zea": (("time", "range"), np.ones(shape)),
            "Ze": (("time", "range"), np.ones(shape)),
            "RR": (("time", "range"), np.ones(shape)),
            "LWC": (("time", "range"), np.ones(shape)),
            "PIA": (("time", "range"), np.ones(shape)),
            "VEL": (("time", "range"), np.ones(shape, dtype="float32")),
            "WIDTH": (("time", "range"), np.ones(shape)),
            "SNR": (("time", "range"), np.ones(shape, dtype="float32")),
            "spectrum_raw": (("time", "n_spectra", "spectrum_n_samples"), np.ones(spectrum_shape)),
            "N": (("time", "n_spectra", "spectrum_n_samples"), np.ones(spectrum_shape)),
            "D": (("n_spectra", "spectrum_n_samples"), np.ones((2, 1))),
        },
        coords={
            "time": ("time", time, {"units": "seconds since 1970-01-01T00:00:00Z"}),
            "range": ("range", [0.0, 35.0]),
        },
        attrs={"Conventions": "CF/Radial", "title": "METEK MRR Pro 1.2.5 Data"},
    )
    dataset.to_netcdf(netcdf, engine="h5netcdf")
    with ZipFile(archive, "w", ZIP_DEFLATED) as output:
        output.write(netcdf, "mrrpro.nc")

    result = read_mrr(archive)

    assert result.attrs["mrr_model"] == "MRRPro"
    assert result.time.dtype == np.dtype("datetime64[ns]")
    assert result.RR.shape == shape


def _write_postprocessed_mrrpro(path, start):
    times = np.array([start, start + np.timedelta64(10, "s")])
    shape = (2, 3)
    dataset = xr.Dataset(
        {
            "base_time": ("single_value", [start]),
            "seconds_since_epoch": ("time", times),
            "latitude": ("single_value", [27.71]),
            "longitude": ("single_value", [-97.32]),
            "altitude": ("single_value", [10.0]),
            "calibration_constant": ("single_value", [0.0]),
            "lowest_clutter_free_gate": ("single_value", [4.0]),
            "noise_power_profile": ("range", np.ones(3, dtype="float32")),
            "signal_to_noise_ratio": (("time", "range"), np.ones(shape)),
            "reflectivity_factor": (("time", "range"), np.ones(shape)),
            "radial_velocity": (("time", "range"), np.ones(shape)),
            "spectrum_width": (("time", "range"), np.ones(shape)),
            "spectrum_skewness": (("time", "range"), np.ones(shape)),
            "spectrum_kurtosis": (("time", "range"), np.ones(shape)),
        },
        coords={"time": times, "range": [5.0, 40.0, 75.0]},
        attrs={
            "source": "METEK MRRPro Data",
            "history": "created by Christopher Williams",
        },
    )
    dataset.to_netcdf(path, engine="scipy")


@pytest.mark.parametrize("input_kind", ["directory", "glob", "sequence"])
def test_reads_postprocessed_mrrpro_collection(tmp_path, input_kind):
    _write_postprocessed_mrrpro(tmp_path / "hour_01.nc", np.datetime64("2023-08-22T01:00:00"))
    _write_postprocessed_mrrpro(tmp_path / "hour_00.nc", np.datetime64("2023-08-22T00:00:00"))
    sources = {
        "directory": tmp_path,
        "glob": str(tmp_path / "*.nc"),
        "sequence": [tmp_path / "hour_01.nc", tmp_path / "hour_00.nc"],
    }

    result = read_mrr(sources[input_kind])

    assert result.attrs["mrr_model"] == "MRRPro"
    assert result.attrs["mrr_product"] == "post_processed_moments"
    assert result.attrs["mrr_source_file_count"] == 2
    assert result.sizes == {"single_value": 1, "time": 4, "range": 3}
    assert result.time.values[0] == np.datetime64("2023-08-22T00:00:00")
    assert result.time.values[-1] == np.datetime64("2023-08-22T01:00:10")
    assert result.reflectivity_factor.shape == (4, 3)


def test_reads_real_postprocessed_mrrpro_day_when_available():
    source = Path(
        "/Volumes/36TB/MRR/TAMU-CC/reprocessed/nc_files/"
        "nc_files_c01_mom/2023/08/22"
    )
    if not source.is_dir():
        pytest.skip("C. Williams MRRPro sample directory is not mounted")

    result = read_mrr(source)

    assert result.attrs["mrr_model"] == "MRRPro"
    assert result.attrs["mrr_product"] == "post_processed_moments"
    assert result.attrs["mrr_source_file_count"] == 24
    assert result.sizes["time"] == 8640
    assert result.sizes["range"] == 256
    assert result.time.values[0].astype("datetime64[s]") == np.datetime64("2023-08-22T00:00:00")
    assert result.time.values[-1].astype("datetime64[s]") == np.datetime64("2023-08-22T23:59:50")
