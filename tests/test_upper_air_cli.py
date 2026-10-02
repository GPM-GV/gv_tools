import pytest

from gv_tools.util import upper_air_cli


def test_cli_latest(monkeypatch, tmp_path, capsys):
    output = tmp_path / "profile.grib2"
    result = type("Result", (), {"path": output})()
    monkeypatch.setattr(
        upper_air_cli, "download_model_soundings", lambda *args, **kwargs: [result]
    )

    assert upper_air_cli.main(
        ["38.9", "-77.0", "--latest", "--output-dir", str(tmp_path)]
    ) == 0
    assert capsys.readouterr().out.strip() == str(output)


def test_cli_range_requires_end():
    with pytest.raises(SystemExit, match="2"):
        upper_air_cli.main(["38.9", "-77.0", "--start", "2026-09-30T00:00Z"])
