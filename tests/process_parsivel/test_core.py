import numpy as np
import pandas as pd
import xarray as xr

from process_parsivel.core import (
    discover_input_dates,
    get_integral_parameters,
    load_tables,
    save_dataframes_to_netcdf,
)
from process_parsivel.workflow import date_range
from process_parsivel.plotting import plot_dsd, plot_integral_parameters, plot_parameters
from process_parsivel.radar import add_band_reflectivities, compute_band_reflectivity
from process_parsivel.cli import parse_args
from process_parsivel.daily import discover_apu_days, run_daily_netcdf
from process_parsivel.location import resolve_location


def test_packaged_tables_load():
    dv, mask = load_tables()
    assert len(dv) == 32
    assert mask.shape[0] == 32


def test_cli_accepts_input_dir_and_space_separated_radar_bands():
    args = parse_args([
        "--inst", "apu07",
        "--input-dir", "/data/parsivel",
        "--output-dir", "Output/apu07",
        "--radar-bands", "S", "C", "X", "Ku", "K", "Ka",
    ])
    assert args.input_path == "/data/parsivel"
    assert args.radar_bands == ["S", "C", "X", "Ku", "K", "Ka"]


def test_cli_accepts_comma_separated_radar_bands():
    args = parse_args([
        "--inst", "apu07", "--input", "input.zip",
        "--output-dir", "Output", "--radar-bands", "S,C,X,Ku,K,Ka",
    ])
    assert args.radar_bands == ["S,C,X,Ku,K,Ka"]


def test_zero_drops_produce_finite_zero_outputs():
    dv, mask = load_tables()
    ds = xr.Dataset(
        {"drops": (["time", "Diam", "Vel"], np.zeros((1, 32, 32)))},
        coords={"time": pd.to_datetime(["2024-01-01"]), "Diam": dv.Drop_bin, "Vel": dv.Measured_Vt},
    )
    parms, psd, moments = get_integral_parameters("apu01", ds, mask, dv)
    assert np.isfinite(parms.to_numpy()).all()
    assert (parms.to_numpy() == 0).all()
    assert (psd.to_numpy() == 0).all()
    assert (moments.to_numpy() == 0).all()


def test_discover_dates_recursively(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "apu02_20240131_part.zip").touch()
    (nested / "apu02_20240201.dat").touch()
    (nested / "notes.txt").touch()
    found = discover_input_dates(tmp_path)
    assert [stamp.strftime("%Y%m%d") for stamp in found] == ["20240131", "20240201"]


def test_workflow_date_range_uses_python_values(tmp_path):
    dates = date_range(tmp_path, "2024-02-28", "2024-03-01")
    assert [stamp.strftime("%Y%m%d") for stamp in dates] == ["20240228", "20240229", "20240301"]


def test_plot_parameters_accumulation_uses_y2():
    index = pd.date_range("2024-01-01", periods=3, freq="min")
    parms = pd.DataFrame({"Rain": [1.0, 2.0, 3.0], "dBZ": [10.0, 11.0, 12.0]}, index=index)
    figure, axes, y2 = plot_parameters(
        parms, columns=["Rain", "dBZ"], accumulate=True, show=False
    )
    assert len(axes) == 2
    assert set(y2) == {"Rain"}
    assert list(y2["Rain"].lines[0].get_ydata()) == [1.0, 3.0, 6.0]
    import matplotlib.pyplot as plt
    plt.close(figure)


def test_plot_dsd_masks_zeros_and_saves(tmp_path):
    index = pd.date_range("2024-01-01", periods=3, freq="min")
    psd = pd.DataFrame([[0, 0], [0, 2], [1, 0]], index=index, columns=[0.1, 0.2])
    output = tmp_path / "dsd.png"
    figure, axis, colorbar, saved = plot_dsd(psd, save_path=output, show=False)
    assert colorbar is not None
    assert saved == str(output)
    assert output.is_file()
    import matplotlib.pyplot as plt
    plt.close(figure)


def test_plot_dsd_all_zero_data_is_annotated():
    index = pd.date_range("2024-01-01", periods=2, freq="min")
    psd = pd.DataFrame(0.0, index=index, columns=[0.1, 0.2])
    figure, axis, colorbar, saved = plot_dsd(psd, show=False)
    assert colorbar is None
    assert saved is None
    assert axis.texts[0].get_text() == "No positive DSD values"
    import matplotlib.pyplot as plt
    plt.close(figure)


def test_plot_dsd_pcolormesh_preserves_bin_cells():
    from matplotlib.collections import QuadMesh
    index = pd.date_range("2024-01-01", periods=3, freq="min")
    psd = pd.DataFrame([[1, 2], [3, 4], [5, 6]], index=index, columns=[0.1, 0.2])
    figure, axis, colorbar, saved = plot_dsd(psd, method="pcolormesh", show=False)
    assert any(isinstance(item, QuadMesh) for item in axis.collections)
    assert colorbar is not None
    assert axis.collections[0].norm.vmin == 1.0
    import matplotlib.pyplot as plt
    plt.close(figure)


def test_mie_band_reflectivities_are_added():
    index = pd.date_range("2024-01-01", periods=2, freq="min")
    diameters = [0.5, 1.0, 2.0, 4.0]
    psd = pd.DataFrame([[10, 20, 30, 40], [0, 0, 0, 0]], index=index, columns=diameters)
    radar = compute_band_reflectivity(psd, bands=["S", "X", "Ku", "K", "Ka"])
    assert list(radar.columns) == [
        "Z_S", "dBZ_S", "Z_X", "dBZ_X", "Z_Ku", "dBZ_Ku",
        "Z_K", "dBZ_K", "Z_Ka", "dBZ_Ka",
    ]
    assert np.isfinite(radar.loc[index[0], ["dBZ_S", "dBZ_X", "dBZ_Ka"]]).all()
    assert np.isnan(radar.loc[index[1], "dBZ_S"])
    parms = pd.DataFrame({"Rain": [1.0, 0.0]}, index=index)
    augmented = add_band_reflectivities(parms, psd, bands=["C"])
    assert {"Z_C", "dBZ_C"}.issubset(augmented.columns)


def test_integral_parameter_layout_and_scaled_accumulation():
    index = pd.date_range("2024-01-01", periods=3, freq="min")
    parms = pd.DataFrame({
        "Rain": [60.0, 120.0, 0.0], "dBZ": [10, 20, 0], "LWC": [1, 2, 0],
        "Dm": [1, 2, 0], "Dmax": [2, 3, 0], "Total Drops": [10, 20, 0],
        "Concentration": [100, 200, 0],
    }, index=index)
    figure, axes, y2, saved = plot_integral_parameters(
        parms, accumulate=True, accumulation_scale=1 / 60, show=False
    )
    assert len(axes) == 6
    assert axes[0].get_subplotspec().rowspan.start == 0
    assert axes[0].get_subplotspec().colspan.start == 0
    assert axes[1].get_subplotspec().rowspan.start == 0
    assert axes[1].get_subplotspec().colspan.start == 1
    assert axes[5].get_subplotspec().rowspan.start == 2
    assert axes[5].get_subplotspec().colspan.start == 1
    assert len(axes[3].lines) == 2
    assert list(y2["Rain"].lines[0].get_ydata()) == [1.0, 3.0, 3.0]
    assert saved is None
    import matplotlib.pyplot as plt
    plt.close(figure)


def test_netcdf_writer_produces_nonempty_file(tmp_path):
    index = pd.date_range("2024-01-01", periods=2, freq="min")
    parms = pd.DataFrame({"Rain": [1.0, 2.0], "Total Drops": [1, 2]}, index=index)
    psd = pd.DataFrame([[1.0, 0.0], [2.0, 3.0]], index=index, columns=[0.1, 0.2])
    moments = pd.DataFrame([[1.0, 2.0], [3.0, 4.0]], index=index, columns=["M0", "M1"])
    output = save_dataframes_to_netcdf(
        parms, psd, moments, tmp_path, "WFF", "apu07", "2024", "01", "01"
    )
    from pathlib import Path
    assert Path(output).is_file()
    assert Path(output).parent == tmp_path / "NetCDF" / "apu07" / "2024" / "01"
    assert Path(output).stat().st_size > 0
    dataset = xr.open_dataset(output, engine="h5netcdf")
    assert dataset.attrs["writer_engine"] == "h5netcdf"
    dataset.close()


def test_discover_apu_days_combines_hourly_archives(tmp_path):
    month = tmp_path / "apu01" / "202601"
    month.mkdir(parents=True)
    (month / "apu01_2026010100.zip").touch()
    (month / "apu01_2026010123.zip").touch()
    (month / "apu01_2026010200.zip").touch()
    (month / "wrong_20260101.zip").touch()
    assert [
        (instrument, stamp.strftime("%Y-%m-%d"))
        for instrument, stamp in discover_apu_days(tmp_path)
    ] == [("apu01", "2026-01-01"), ("apu01", "2026-01-02")]


def test_daily_batch_writes_netcdf_and_removes_extracted_files(tmp_path):
    from zipfile import ZipFile

    source = tmp_path / "input" / "apu01" / "202401"
    source.mkdir(parents=True)
    row = "20240101000000;" + ",".join(["0"] * 1034) + "\n"
    archive = source / "apu01_2024010100.zip"
    with ZipFile(archive, "w") as handle:
        handle.writestr("apu01_2024010100.dat", row)
    temp_root = tmp_path / "working"
    result = run_daily_netcdf(
        tmp_path / "input",
        tmp_path / "output",
        instruments=["apu01"],
        start_date="2024-01-01",
        site="TEST",
        temp_dir=temp_root,
    )
    output = result.outputs[("apu01", "2024-01-01")]
    from pathlib import Path
    assert Path(output).is_file()
    assert Path(output).parent == (
        tmp_path / "output" / "NetCDF" / "apu01" / "2024" / "01"
    )
    assert archive.is_file()
    assert not (temp_root / "tmp" / "apu01" / "20240101").exists()
    assert result.errors == {}
    with xr.open_dataset(output, engine="h5netcdf") as dataset:
        assert dataset.attrs["location_status"] == "matched_date_range"
        assert float(dataset.latitude) == 37.9289333333


def test_location_timeline_exact_and_latest_recorded_matches(tmp_path):
    locations = tmp_path / "locations"
    locations.mkdir()
    (locations / "apu01_locations.csv").write_text(
        "instrument,latitude,longitude,elevation,city,state,date_range,num_files\n"
        "apu01,10,-20,100,Alpha,AA,2024-01-01 - 2024-01-10,10\n"
        "apu01,11,-21,101,Beta,BB,2024-01-20 - 2024-01-31,12\n",
        encoding="utf-8",
    )
    exact = resolve_location("apu01", "2024-01-05", locations)
    assert exact["location_status"] == "matched_date_range"
    assert exact["latitude"] == 10.0
    gap = resolve_location("apu01", "2024-01-15", locations)
    assert gap["location_status"] == "latest_recorded_location"
    assert gap["city"] == "Alpha"
    current = resolve_location("apu01", "2024-02-01", locations)
    assert current["location_status"] == "latest_recorded_location"
    assert current["city"] == "Beta"
    before = resolve_location("apu01", "2023-12-31", locations)
    assert before["location_status"] == "earliest_recorded_location"
    assert before["city"] == "Alpha"
    assert before["latitude"] == 10.0


def test_missing_location_timeline_is_recorded(tmp_path):
    result = resolve_location("apu22", "2026-01-01", tmp_path)
    assert result["location_status"] == "timeline_not_found"
    assert result["location_source"].endswith("apu22_locations.csv")
