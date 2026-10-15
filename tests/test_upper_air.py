from datetime import datetime, timezone

import pytest

from gv_tools.util import ModelUnavailableError, download_model_soundings
from gv_tools.util import upper_air


UTC = timezone.utc


def test_single_rap_cycle_download(monkeypatch, tmp_path):
    seen = []

    def fake_fetch(url, timeout):
        seen.append((url, timeout))
        return b"GRIB" + b"x" * 20

    monkeypatch.setattr(upper_air, "_fetch", fake_fetch)
    result = download_model_soundings(
        38.9,
        -77.0,
        model="rap",
        when=datetime(2026, 9, 30, 18, tzinfo=UTC),
        output_dir=tmp_path,
    )

    assert len(result) == 1
    assert result[0].path.read_bytes().startswith(b"GRIB")
    assert "filter_rap.pl" in seen[0][0]
    assert "rap.t18z.awp130pgrbf00.grib2" in seen[0][0]
    assert "var_TMP=on" in seen[0][0]
    assert "all_lev=on" in seen[0][0]


def test_gfs_range_selects_only_model_cycles(monkeypatch, tmp_path):
    monkeypatch.setattr(upper_air, "_fetch", lambda url, timeout: b"GRIB" + b"x" * 20)
    result = download_model_soundings(
        0,
        0,
        model="gfs",
        start=datetime(2026, 9, 29, 2),
        end=datetime(2026, 9, 29, 13),
        output_dir=tmp_path,
        pause=0,
    )

    assert [item.cycle.hour for item in result] == [6, 12]


def test_latest_falls_back_to_previous_cycle(monkeypatch, tmp_path):
    calls = []

    def fake_fetch(url, timeout):
        calls.append(url)
        if len(calls) == 1:
            raise upper_air.SoundingDownloadError("not ready")
        return b"GRIB" + b"x" * 20

    monkeypatch.setattr(upper_air, "_fetch", fake_fetch)
    result = download_model_soundings(
        40,
        -105,
        model="rap",
        latest=True,
        output_dir=tmp_path,
        _now=datetime(2026, 10, 1, 10, 30, tzinfo=UTC),
    )

    assert len(calls) == 2
    assert result[0].cycle == datetime(2026, 10, 1, 9, tzinfo=UTC)


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"latest": True, "when": datetime(2026, 1, 1)},
        {"start": datetime(2026, 1, 1)},
    ],
)
def test_requires_one_complete_selection_mode(tmp_path, kwargs):
    with pytest.raises(ValueError):
        download_model_soundings(0, 0, output_dir=tmp_path, **kwargs)


def test_ruc_has_actionable_retirement_error(tmp_path):
    with pytest.raises(ModelUnavailableError, match="use model='rap'"):
        download_model_soundings(0, 0, model="ruc", latest=True, output_dir=tmp_path)


def test_rejects_non_cycle_hour_for_gfs(tmp_path):
    with pytest.raises(ValueError, match="00Z, 06Z, 12Z, 18Z"):
        download_model_soundings(
            0,
            0,
            model="gfs",
            when=datetime(2026, 1, 1, 3),
            output_dir=tmp_path,
        )
