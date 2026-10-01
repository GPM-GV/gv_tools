from importlib import import_module
import gzip
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest
import numpy as np

from gv_tools import ingest_radar, inspect_radar_file

module = import_module("gv_tools.ingest_radar")


def test_prepare_pyart_info_wraps_scalar_instrument_parameters():
    class ConvertedRadar:
        instrument_parameters = {"instrument_name": "NPOL", "frequency": 2.8e9}
        radar_calibration = {"calibration_name": "test"}

    radar = ConvertedRadar()
    module._prepare_pyart_info(radar)
    assert radar.instrument_parameters["instrument_name"]["data"].item() == "NPOL"
    assert radar.instrument_parameters["frequency"]["data"].item() == 2.8e9
    assert radar.radar_calibration["calibration_name"]["data"].item() == "test"
    assert callable(radar.info)


def test_prepared_xradar_result_supports_all_info_levels():
    from pyart.testing import make_empty_ppi_radar

    source = make_empty_ppi_radar(5, 4, 1)
    source.instrument_parameters = {"instrument_name": "NPOL"}

    class ConvertedRadar:
        pass

    radar = ConvertedRadar()
    radar.__dict__.update(source.__dict__)
    module._prepare_pyart_info(radar)
    for level in ("compact", "standard", "full"):
        output = StringIO()
        radar.info(level=level, out=output)
        assert "instrument_parameters:" in output.getvalue()


def test_inspect_raw_np1_by_sigmet_content_not_filename(tmp_path):
    source = tmp_path / "volume.no_extension"
    source.write_bytes(b"\x1b" + b"raw sigmet data")

    route = inspect_radar_file(source)

    assert route.family == "np1"
    assert route.file_format == "SIGMET"
    assert route.reader == "read_sigmet"


@pytest.mark.parametrize(
    ("signature", "file_format"),
    [(b"CDF\x02", "NetCDF3"), (b"\x89HDF\r\n\x1a\n", "NetCDF4/HDF5")],
)
def test_inspect_npol1_netcdf_content(tmp_path, signature, file_format):
    source = tmp_path / "misleading.np1"
    source.write_bytes(signature + b"payload")

    route = inspect_radar_file(source)

    assert route.family == "NPOL1"
    assert route.file_format == file_format
    assert route.reader == "read_cfradial"


@pytest.mark.parametrize("signature", [b"AR2V0006", b"ARCHIVE2."])
def test_inspect_nexrad_level2_content(tmp_path, signature):
    source = tmp_path / "KCRP20240821_000517_V06"
    source.write_bytes(signature + b"payload")

    route = inspect_radar_file(source)

    assert route.family == "WSR-88D"
    assert route.file_format == "NEXRAD Level II"
    assert route.reader == "read_nexrad_archive"


def test_ingest_dispatches_to_sigmet_reader(tmp_path, monkeypatch):
    source = tmp_path / "raw.np1"
    source.write_bytes(b"\x1braw")
    calls = []
    fake = SimpleNamespace(
        io=SimpleNamespace(
            read_sigmet=lambda path, **options: calls.append((path, options)) or "radar",
            read_cfradial=lambda path, **options: None,
        )
    )
    monkeypatch.setattr(module, "_pyart", lambda: fake)

    assert ingest_radar(source, file_field_names=True) == "radar"
    assert calls == [(str(source), {"file_field_names": True})]


def test_ingest_dispatches_npol1_to_cfradial_reader(tmp_path, monkeypatch):
    source = tmp_path / "NPOL1_20260827.nc"
    source.write_bytes(b"CDF\x02payload")
    calls = []
    fake = SimpleNamespace(
        io=SimpleNamespace(
            read_sigmet=lambda path, **options: None,
            read_cfradial=lambda path, **options: calls.append((path, options)) or "radar",
        )
    )
    monkeypatch.setattr(module, "_pyart", lambda: fake)

    assert ingest_radar(source, delay_field_loading=True) == "radar"
    assert calls == [(str(source), {"delay_field_loading": True})]


def test_ingest_dispatches_nexrad_to_archive_reader(tmp_path, monkeypatch):
    source = tmp_path / "KCRP20240821_000517_V06"
    source.write_bytes(b"AR2V0006payload")
    calls = []
    radar = SimpleNamespace(scan_type="ppi", metadata={})
    fake = SimpleNamespace(
        io=SimpleNamespace(
            read_nexrad_archive=lambda path, **options: calls.append(
                (path, options)
            ) or radar,
        )
    )
    monkeypatch.setattr(module, "_pyart", lambda: fake)

    assert ingest_radar(source, delay_field_loading=True) is radar
    assert calls == [(str(source), {"delay_field_loading": True})]


def test_ingest_xradar_dispatches_to_cfradial_datatree(tmp_path, monkeypatch, capsys):
    source = tmp_path / "volume.nc"
    source.write_bytes(b"CDF\x02payload")
    calls = []
    class FakeRadar:
        metadata = {}

    radar = FakeRadar()

    class FakeTree:
        children = {}
        pyart = SimpleNamespace(to_radar=lambda: calls.append("converted") or radar)

        def load(self):
            calls.append("loaded")

    tree = FakeTree()
    fake = SimpleNamespace(
        io=SimpleNamespace(
            open_cfradial1_datatree=lambda path, **options: calls.append(
                (path, options)
            ) or tree
        )
    )
    monkeypatch.setattr(module, "_xradar", lambda: fake)

    assert ingest_radar(source, XRADAR=True, first_dim="auto") is radar
    assert calls == [(str(source), {"first_dim": "auto"}), "loaded", "converted"]
    assert radar.metadata["gv_tools_scan_type"] == "UNKNOWN"
    assert radar.metadata["XRADAR"] == 1
    assert callable(radar.info)
    assert capsys.readouterr().out.endswith("Radar scan type: UNKNOWN\n")


def test_ingest_xradar_nexrad_falls_back_to_pyart(tmp_path, monkeypatch):
    source = tmp_path / "KCRP20240821_000517_V06"
    source.write_bytes(b"AR2V0006payload")
    calls = []

    radar = SimpleNamespace(scan_type="ppi", metadata={})
    fake = SimpleNamespace(
        io=SimpleNamespace(
            read_nexrad_archive=lambda path, **options: calls.append(
                (path, options)
            ) or radar
        )
    )
    monkeypatch.setattr(module, "_pyart", lambda: fake)

    with pytest.warns(UserWarning, match="using Py-ART read_nexrad_archive"):
        assert ingest_radar(source, XRADAR=True, file_field_names=True) is radar
    assert calls == [(str(source), {"file_field_names": True})]
    assert radar.metadata["XRADAR"] == 0


def test_ingest_xradar_warns_and_ignores_file_field_names(
    tmp_path, monkeypatch
):
    source = tmp_path / "volume.nc"
    source.write_bytes(b"CDF\x02payload")
    calls = []

    class FakeRadar:
        metadata = {}

    class FakeTree:
        children = {}
        pyart = SimpleNamespace(to_radar=FakeRadar)

        def load(self):
            pass

    fake = SimpleNamespace(
        io=SimpleNamespace(
            open_cfradial1_datatree=lambda path, **options: calls.append(options)
            or FakeTree()
        )
    )
    monkeypatch.setattr(module, "_xradar", lambda: fake)

    with pytest.warns(UserWarning, match="file_field_names.*ignored"):
        ingest_radar(
            source, XRADAR=True, file_field_names=True, first_dim="auto"
        )

    assert calls == [{"first_dim": "auto"}]


@pytest.mark.parametrize(
    ("declared", "elevation", "filename", "expected"),
    [
        ("ppi", [0.5, 1.0], "volume.nc", "PPI"),
        ("rhi", [0.0, 20.0], "volume.nc", "RHI"),
        ("ppi", [89.8, 90.0], "volume.nc", "BB"),
        ("ppi", [1.0], "volume_bb.nc", "BB"),
    ],
)
def test_ingest_prints_and_records_scan_type(
    tmp_path, monkeypatch, capsys, declared, elevation, filename, expected
):
    source = tmp_path / filename
    source.write_bytes(b"CDF\x02payload")
    radar = SimpleNamespace(
        scan_type=declared,
        elevation={"data": np.asarray(elevation)},
        metadata={},
    )
    fake = SimpleNamespace(io=SimpleNamespace(read_cfradial=lambda path: radar))
    monkeypatch.setattr(module, "_pyart", lambda: fake)

    assert ingest_radar(source) is radar
    assert capsys.readouterr().out == f"Radar scan type: {expected}\n"
    assert radar.metadata["gv_tools_scan_type"] == expected
    assert radar.metadata["XRADAR"] == 0


def test_ingested_radar_can_be_written_to_cfradial(tmp_path):
    import pyart
    from pyart.testing import make_empty_ppi_radar

    source = tmp_path / "source.cf"
    output = tmp_path / "roundtrip.cf"
    pyart.io.write_cfradial(source, make_empty_ppi_radar(5, 4, 1))

    radar = ingest_radar(source, file_field_names=True, XRADAR=False)
    assert radar.metadata["XRADAR"] == 0
    pyart.io.write_cfradial(output, radar, format="NETCDF4")

    assert output.is_file()
    assert pyart.io.read_cfradial(output).nrays == radar.nrays


def test_ingest_gzip_decompresses_before_pyart(tmp_path, monkeypatch):
    source = tmp_path / "volume.cf.gz"
    with gzip.open(source, "wb") as stream:
        stream.write(b"CDF\x02payload")
    calls = []
    fake = SimpleNamespace(
        io=SimpleNamespace(
            read_cfradial=lambda path, **options: calls.append(
                (Path(path).read_bytes(), options)
            ) or "radar"
        )
    )
    monkeypatch.setattr(module, "_pyart", lambda: fake)

    assert inspect_radar_file(source).reader == "read_cfradial"
    assert ingest_radar(source, delay_field_loading=True) == "radar"
    assert calls == [(b"CDF\x02payload", {"delay_field_loading": True})]


def test_ingest_single_member_zip_decompresses_before_pyart(tmp_path, monkeypatch):
    source = tmp_path / "volume.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("nested/raw.np1", b"\x1braw")
    calls = []
    fake = SimpleNamespace(
        io=SimpleNamespace(
            read_sigmet=lambda path, **options: calls.append(Path(path).read_bytes()) or "radar"
        )
    )
    monkeypatch.setattr(module, "_pyart", lambda: fake)

    assert inspect_radar_file(source).reader == "read_sigmet"
    assert ingest_radar(source) == "radar"
    assert calls == [b"\x1braw"]


def test_zip_requires_exactly_one_radar_file(tmp_path):
    source = tmp_path / "two-files.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("first", b"CDF\x02")
        archive.writestr("second", b"CDF\x02")

    with pytest.raises(ValueError, match="exactly one file"):
        inspect_radar_file(source)


def test_rejects_unknown_content_before_loading_pyart(tmp_path):
    source = tmp_path / "unknown.np1"
    source.write_bytes(b"not radar")

    with pytest.raises(ValueError, match="unsupported radar format"):
        ingest_radar(source)


def test_missing_file_has_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="radar input is not a file"):
        inspect_radar_file(tmp_path / "missing.np1")
