"""Read PIERS tipping-bucket gauge packets and turn tip counters into rain.

:func:`read_gauge` decodes the packets exactly as recorded. :func:`tipping_bucket_rain`
(and :func:`read_tipping_bucket`, which combines both) converts tip counters into
tips, depths and rates on a regular grid, handling counter resets, duplicate
records and reporting gaps. Nothing is written to disk.
"""

from __future__ import annotations

import csv
import fnmatch
import re
import warnings
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd

_STATION = re.compile(r"^Station(?:_|\s+)Name\s*:", re.I)


def _value(line: str, *labels: str) -> str:
    key, separator, value = line.partition(":")
    valid = {label.casefold().replace("_", " ") for label in labels}
    if not separator or key.strip().casefold().replace("_", " ") not in valid:
        raise ValueError(f"invalid metadata line: {line!r}")
    return value.strip()


def _resolve_gauge_files(
    source: str | Path | Sequence[str | Path], gauge_id: str | None
) -> list[Path]:
    items = [source] if isinstance(source, (str, Path)) else list(source)
    if not items:
        raise ValueError("source must contain at least one fully qualified path")
    pattern = f"{gauge_id.strip()}*TB*.csv" if gauge_id else "*TB*.csv"
    found: list[Path] = []
    for item in items:
        path = Path(item).expanduser()
        if not path.is_absolute():
            raise ValueError(f"each input path must be fully qualified: {path}")
        if path.is_file():
            found.append(path.resolve())
        elif path.is_dir():
            found.extend(
                candidate.resolve()
                for candidate in sorted(path.rglob("*.csv"))
                if fnmatch.fnmatch(candidate.name, pattern)
            )
        else:
            raise FileNotFoundError(f"input path does not exist: {path}")
    unique = list(dict.fromkeys(found))
    if not unique:
        raise FileNotFoundError(f"no gauge files matching {pattern!r}")
    # Read daily files AND packets (0.50.0 dropped every packet as soon as one
    # daily file was present). Daily files come first so that exact repeats
    # of a daily record are the ones removed.
    daily = [path for path in unique if "_daily." in path.name.casefold()]
    return daily + [path for path in unique if path not in set(daily)]


def _measurement(line: str, source: Path, number: int, station: str):
    try:
        row = [item.strip() for item in next(csv.reader([line], strict=True))]
    except csv.Error as exc:
        return None, f"line {number}: malformed CSV ({exc})"
    padded = (row + [None] * 6)[:6]
    timestamp = pd.to_datetime(
        f"{padded[0]} {padded[1]}", format="%m/%d/%Y %H:%M:%S", errors="coerce"
    )
    value = pd.to_numeric(padded[3], errors="coerce")
    if pd.isna(timestamp) or padded[3] in (None, "") or pd.isna(value):
        return None, f"line {number}: invalid measurement"
    return {
        "timestamp": timestamp,
        "station_name": station,
        "source_file": source.name,
        "source_path": str(source),
        "source_line": number,
        "measurement": padded[2],
        "value": value,
        "unit": padded[4],
        "quality": padded[5],
        "extra_fields": row[6:] or None,
    }, None


def _parse_file(path: Path) -> tuple[list[dict], list[dict]]:
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    if not any(line.strip() for line in lines):
        raise ValueError(f"{path.name} is empty")
    station = ""
    latitude = longitude = None
    packet = None
    packet_data: list[dict] = []
    metadata: list[dict] = []
    observations: list[dict] = []
    issues: list[str] = []

    def finish_packet() -> None:
        nonlocal packet, packet_data
        if packet is not None and packet_data:
            packet["timestamp"] = packet_data[0]["timestamp"]
            packet["record_count"] = len(packet_data)
            metadata.append(packet)
            observations.extend(packet_data)
        packet, packet_data = None, []

    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line:
            continue
        if _STATION.match(line):
            station = _value(line, "Station Name", "Station_Name")
        elif line.casefold().startswith("latitude/longitude"):
            try:
                latitude, longitude = (
                    float(item.strip()) for item in _value(line, "Latitude/Longitude").split(",")
                )
            except (TypeError, ValueError):
                issues.append(f"line {number}: invalid latitude/longitude")
        elif line.casefold().startswith("rssi"):
            finish_packet()
            packet = {
                "station_name": station,
                "latitude": latitude,
                "longitude": longitude,
                "rssi": pd.to_numeric(_value(line, "RSSI"), errors="coerce"),
                "battery_voltage": float("nan"),
                "source_file": path.name,
                "source_path": str(path),
            }
        elif line.casefold().startswith("battery_voltage") and packet is not None:
            packet["battery_voltage"] = pd.to_numeric(
                _value(line, "Battery_Voltage"), errors="coerce"
            )
        elif packet is not None:
            record, problem = _measurement(line, path, number, station)
            if problem:
                issues.append(problem)
            else:
                packet_data.append(record)
    finish_packet()
    if not metadata:
        raise ValueError(f"{path.name} contains no valid packets")
    if issues:
        warnings.warn(
            f"{path.name} parsed with {len(issues)} issue(s)", RuntimeWarning, stacklevel=2
        )
    return metadata, observations


def read_gauge(
    source: str | Path | Sequence[str | Path],
    *,
    gauge_id: str | None = None,
    measurement: str | None = None,
    start=None,
    end=None,
    return_metadata: bool = False,
):
    """Read gauge packets into a pandas DataFrame without resampling or writing.

    ``source`` may be one full-path filename, a directory, or an explicit
    sequence of files/directories. Optional filters never aggregate the data.
    Set ``return_metadata=True`` to return ``(observations, packet_metadata)``.
    """
    metadata_rows: list[dict] = []
    observations: list[dict] = []
    errors: list[str] = []
    paths = _resolve_gauge_files(source, gauge_id)
    for path in paths:
        try:
            file_metadata, file_observations = _parse_file(path)
            metadata_rows.extend(file_metadata)
            observations.extend(file_observations)
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"{path.name}: {exc}")
    if not observations:
        raise ValueError("no input files could be parsed: " + "; ".join(errors))
    if errors:
        warnings.warn("skipped input files: " + "; ".join(errors), RuntimeWarning, stacklevel=2)
    frame = pd.DataFrame(observations)
    key = ["timestamp", "measurement", "value", "unit", "quality"]
    duplicates = int(frame.duplicated(key).sum())
    frame = frame.drop_duplicates(key, keep="first")
    frame = frame.set_index("timestamp").sort_index(kind="stable")
    packet_metadata = pd.DataFrame(metadata_rows).set_index("timestamp").sort_index(kind="stable")
    if measurement is not None:
        frame = frame.loc[frame["measurement"].eq(measurement)]
    if start is not None:
        frame = frame.loc[frame.index >= pd.Timestamp(start)]
    if end is not None:
        frame = frame.loc[frame.index <= pd.Timestamp(end)]
    frame.attrs.update(
        instrument_type="tipping_bucket_gauge",
        source_files=[p.name for p in paths],
        duplicate_records=duplicates,
        time_reference="as recorded by the PIERS logger (UTC)",
    )
    return (frame, packet_metadata) if return_metadata else frame


FLAG_COUNTER_RESET = 1
FLAG_AFTER_GAP = 2
FLAG_SUSPECT_RATE = 4
FLAG_MULTI_INTERVAL = 8
FLAG_GLITCH_REMOVED = 16
FLAG_MEANINGS = (
    "1 counter_reset_or_impossible_jump, 2 tips_accumulated_over_reporting_gap, 4 rate_above_max_rate_mm_h, "
    "8 tips_of_a_report_spanning_several_intervals, 16 bad_counter_value_or_dropout_removed"
)


# How much calmer a dip or spike reading must be than a reset before a drop
# is taken for bad values: a drop to less than half the old level looks like
# a reset (the counter cleared) and needs strong evidence; a smaller drop looks
# like a stale or garbled value.
_RESET_LIKE_FACTOR = 3.0
_RESET_LIKE_MARGIN_TIPS = 2.0
_STALE_LIKE_MARGIN_TIPS = 0.0


def _possible_tips(tips_per_second: float, seconds: float) -> float:
    """Most tips a gauge can report in ``seconds`` at the maximum rate.

    A generous Poisson bound (mean + 3 sigma + 2), so bursts of real heavy
    rain in short reports are never taken for counter faults.
    """
    mean = tips_per_second * max(seconds, 0.0)
    return mean + 3.0 * np.sqrt(mean) + 2.0


def _tip_measurements(frame: pd.DataFrame, measurements) -> list[str]:
    if measurements is not None:
        names = [measurements] if isinstance(measurements, str) else list(measurements)
        missing = sorted(set(names).difference(frame["measurement"].unique()))
        if missing:
            raise ValueError(f"gauge data contain no measurement(s) {missing}")
        return names
    names = sorted(name for name in frame["measurement"].dropna().unique() if "tip" in str(name).casefold())
    if not names:
        raise ValueError("no tip-counter measurements found; pass measurements=... explicitly")
    return names


def _glitch_free(values: np.ndarray, seconds: np.ndarray, window: int, tips_per_second: float) -> np.ndarray:
    """Mask of counter records to keep after removing bad values and dropouts.

    A running counter only grows, apart from resets. At every drop three
    readings are weighed:

    * reset -- the new value counts the tips since the reset;
    * dip -- the records until the counter is back at its old level (within
      ``window`` records) are bad, e.g. a dropout to 0 or a stale value;
    * spike -- the record before the drop was bad.

    A reading that needs tips faster than the maximum rate
    (``tips_per_second``, with a Poisson allowance for bursts) is impossible.
    Each possible reading implies a rain rate for the records involved; a
    dip or spike is taken only when its highest implied rate is lower than
    the reset's by more than two tips per usual report interval, so a reset
    wins when the two are close. A rise that is impossible and comes back
    down within ``window`` records is a spike. When the counter jumps
    impossibly fast back to the level it had before an accepted reset, and
    the records since that reset stayed flat, the reset was a dropout: those
    records are removed and the tips count from the old level.
    """
    size = values.size
    keep = np.ones(size, dtype=bool)
    if size < 2 or window < 1:
        return keep  # glitch_window=0: every drop is a reset
    spacing = np.diff(seconds)
    usual = float(np.median(spacing[spacing > 0])) if np.any(spacing > 0) else 60.0
    kept: list[int] = [0]
    dropout: tuple[int, int] | None = None  # (level kept before the last reset, first record after it)

    def possible(tips: float, start: int, stop: int) -> bool:
        return tips <= _possible_tips(tips_per_second, seconds[stop] - seconds[start])

    def rate(tips: float, start: int, stop: int) -> float:
        span = seconds[stop] - seconds[start]
        return tips / span if span > 0 else (0.0 if tips <= 0 else np.inf)

    def climb(level: int, start: int, strict: bool) -> float | None:
        """Highest rate of the climb from record ``level`` through the next records.

        An impossible step refutes a reset (``strict``: None); for the other
        readings it is a separate bad value, judged when it is reached.
        """
        worst, previous = 0.0, level
        for later in range(start, min(start + window, size)):
            step = values[later] - values[previous]
            if step < 0:
                break  # a further drop is judged on its own
            if not possible(step, previous, later):
                if strict:
                    return None
                break
            worst, previous = max(worst, rate(step, previous, later)), later
        return worst

    def worst_of(first: float, rest: float | None) -> float | None:
        return None if rest is None else max(first, rest)

    index = 1
    while index < size:
        previous = kept[-1]
        if values[index] < values[previous]:
            reset = None
            if possible(values[index], previous, index):
                reset = worst_of(rate(values[index], previous, index), climb(index, index + 1, True))
            readings = []  # (highest implied rate, kind, detail)
            before = kept[-2] if len(kept) >= 2 else None
            if (before is not None and values[before] <= values[index]
                    and possible(values[index] - values[before], before, index)):
                spike = worst_of(rate(values[index] - values[before], before, index), climb(index, index + 1, False))
                if spike is not None:
                    readings.append((spike, "spike", None))
            for step in range(1, window + 1):
                later = index + step
                if later >= size:
                    break
                if values[later] >= values[previous] and possible(values[later] - values[previous], previous, later):
                    dip = worst_of(rate(values[later] - values[previous], previous, later), climb(later, later + 1, False))
                    readings.append((dip, "dip", step))
                    break
            best = min(readings, key=lambda item: item[0]) if readings else None
            if values[index] <= values[previous] / 2:  # the counter cleared, or a dropout
                calmer = best is not None and (
                    reset is None or reset > _RESET_LIKE_FACTOR * best[0] + _RESET_LIKE_MARGIN_TIPS / usual
                )
            else:  # a small drop: a stale or garbled value, or a reset just after a small count
                calmer = best is not None and (reset is None or best[0] + _STALE_LIKE_MARGIN_TIPS / usual < reset)
            if calmer:
                if best[1] == "spike":
                    keep[previous] = False  # the record before the drop was bad
                    kept.pop()
                    continue
                keep[index:index + best[2]] = False  # bad records until the counter is back
                index += best[2]
                continue
            dropout = (previous, index)  # a reset (decided when counting)
        elif not possible(values[index] - values[previous], previous, index):
            back = next(
                (step for step in range(1, window + 1)
                 if index + step < size and values[index + step] >= values[previous]
                 and possible(values[index + step] - values[previous], previous, index + step)),
                None,
            )
            if back is not None:
                keep[index:index + back] = False  # an impossible jump that comes back down
                index += back
                continue
            if dropout is not None:
                level, first = dropout
                low = values[first:index]
                if (values[index] >= values[level] and possible(values[index] - values[level], level, index)
                        and low.max() - low.min() <= 1):
                    keep[first:index] = False  # the 'reset' was a dropout
                    while kept[-1] >= first:
                        kept.pop()
                    dropout = None
                    continue
        kept.append(index)
        index += 1
    return keep


def tipping_bucket_rain(
    observations: pd.DataFrame,
    *,
    tip_depth_mm: float,
    measurements: str | Sequence[str] | None = None,
    counter: str = "cumulative",
    freq: str = "1min",
    max_gap=None,
    counter_max: int | None = None,
    max_rate_mm_h: float | None = 300.0,
    glitch_window: int = 3,
) -> pd.DataFrame:
    """Convert tipping-bucket tip records into tips, depth and rate per ``freq`` interval.

    Parameters
    ----------
    observations
        The DataFrame returned by :func:`read_gauge` (index ``timestamp``,
        columns ``measurement`` and ``value``).
    tip_depth_mm
        Rain depth of one tip in mm (the gauge's calibration, e.g. 0.254 for
        a 0.01 in bucket). Required: GV Tools never assumes a bucket size.
    measurements
        Tip-counter measurement names; default: every measurement whose name
        contains ``"tip"`` (``TB_A_tips``, ``TB_B_tips``).
    counter
        ``"cumulative"`` (default): ``value`` is a running tip counter and a
        record's tips are its increase since the previous record. A decrease
        is read as a counter reset (the new value counts the tips since it;
        with ``counter_max``, a wrap-around when that increase is plausible),
        as a dip (bad records until the counter is back at its old level --
        a dropout to 0, a stale value) or as a spike (the record before was
        bad), whichever implies the calmest rain, a reset when they are close
        (flag 16 for removed records). A dropout longer than
        ``glitch_window`` records is recognised when the counter jumps back
        to its old level. A reset on the last record cannot be confirmed by a
        later one, and a jump no rain can make is a re-based counter: their
        tips are NaN (flag 1). ``glitch_window=0`` turns the bad-value
        rules off, so every drop is a reset -- use it for a logger that clears
        its counter on a schedule (every packet, say), whose small counts make
        resets and dropouts hard to tell apart.
        ``"incremental"``: ``value`` already holds the tips since the previous
        record.
    freq
        Output interval (pandas frequency, default one minute); intervals are
        labelled by their start. A report covers the time since the previous
        report and is put in the interval whose centre it covers.
    max_gap
        Longest spacing between reports still treated as continuous; default
        2.5 x the median spacing (at least 1.5 x ``freq``).
    max_rate_mm_h
        Intervals above this rate are flagged suspect and their depth and rate
        set to NaN (the tips are kept). The same rate (300 mm/h when None),
        with a Poisson allowance for bursts, decides whether a counter change
        is possible at all.

    Returns
    -------
    pandas.DataFrame
        One row per interval from the first to the last report. For each
        measurement ``m``: ``m_tips``, ``m_depth_mm``, ``m_rate_mm_h`` and
        ``m_flag`` (see ``attrs["flag_meanings"]``). Intervals no report
        covers -- before the first report, inside reporting gaps, and inside
        a report spanning several intervals in which tips fell -- are NaN, not
        dry. A report spanning several intervals puts its tips in the last of
        them (flag 8, rate NaN), together with any tips already counted in the
        intervals it makes unknown, so no tip is lost; one that saw no tips
        makes all of them 0. Accounting is in ``attrs``.
    """
    if not isinstance(observations, pd.DataFrame) or "measurement" not in observations or "value" not in observations:
        raise TypeError("observations must be the DataFrame returned by read_gauge")
    tip_depth_mm = float(tip_depth_mm)
    if not np.isfinite(tip_depth_mm) or tip_depth_mm <= 0:
        raise ValueError("tip_depth_mm must be a positive depth in mm")
    mode = str(counter).strip().lower()
    if mode not in {"cumulative", "incremental"}:
        raise ValueError("counter must be 'cumulative' or 'incremental'")
    step = pd.Timedelta(pd.tseries.frequencies.to_offset(freq)).total_seconds()
    if step <= 0:
        raise ValueError("freq must be positive")
    names = _tip_measurements(observations, measurements)
    rate_limit = float(max_rate_mm_h) if max_rate_mm_h is not None else 300.0

    # Pass 1: one (begin, end, tips) interval per report, per measurement.
    reports: dict[str, dict] = {}
    for name in names:
        rows = pd.to_numeric(observations.loc[observations["measurement"].eq(name), "value"], errors="coerce")
        rows = rows.dropna().sort_index(kind="stable")
        duplicated = rows.index.duplicated(keep="first")
        rows = rows.loc[~duplicated]
        if rows.empty:
            raise ValueError(f"measurement {name!r} has no numeric records")
        seconds = rows.index.values.astype("datetime64[ns]").astype(np.int64) / 1e9
        values = rows.to_numpy(dtype=float)
        glitch_times = np.empty(0)
        if mode == "cumulative":
            keep = _glitch_free(values, seconds, int(glitch_window), rate_limit / 3600.0 / tip_depth_mm)
            glitch_times = seconds[~keep]
            seconds, values = seconds[keep], values[keep]
        spacing = np.diff(seconds)
        typical = float(np.median(spacing)) if spacing.size else step
        intervals = []  # (begin, end, tips, counter_flag)
        resets = wraps = jumps = 0
        if mode == "incremental":
            intervals.append((seconds[0] - typical, seconds[0], values[0], False))
        for k in range(1, values.size):
            begin, end = seconds[k - 1], seconds[k]
            reset = False
            plausible = _possible_tips(rate_limit / 3600.0 / tip_depth_mm, end - begin)
            if mode == "incremental":
                count = values[k]
            else:
                count = values[k] - values[k - 1]
                if count < 0:
                    reset = True
                    wrapped = values[k] + (counter_max + 1 - values[k - 1]) if counter_max is not None else None
                    if wrapped is not None and wrapped <= plausible:
                        count, wraps = wrapped, wraps + 1
                    else:
                        resets += 1
                        # the new value counts the tips since the reset; unknown when
                        # no later record confirms the reset or the value is impossible
                        count = values[k] if k + 1 < values.size and values[k] <= plausible else np.nan
                elif count > plausible:
                    # a jump no rain can make and no bad-value rule explains:
                    # the counter was re-based, the tips are unknown
                    reset, count, jumps = True, np.nan, jumps + 1
            intervals.append((begin, end, count, reset))
        reports[name] = {
            "intervals": intervals, "glitch_times": glitch_times, "typical": typical,
            "records": int(rows.size), "duplicates": int(duplicated.sum()),
            "glitches": int(glitch_times.size), "resets": resets, "wraps": wraps, "jumps": jumps,
            "first": seconds[0], "last": seconds[-1],
        }
    starts = [item["intervals"][0][0] if item["intervals"] else item["first"] for item in reports.values()]
    ends = [item["last"] for item in reports.values()]
    first_bin = int(np.floor(min(starts) / step))
    last_bin = int(np.floor((max(ends) - 1e-6) / step))
    last_bin = max(last_bin, int(np.floor(max(ends) / step)))
    bins = np.arange(first_bin, last_bin + 1)
    index = pd.DatetimeIndex(pd.to_datetime((bins * step * 1e9).astype(np.int64)), name="time")
    size = bins.size

    def position(moment: float) -> int:
        return min(max(int(np.floor(moment / step)) - first_bin, 0), size - 1)

    # Pass 2: put each report's tips on the grid.
    columns: dict[str, np.ndarray] = {}
    accounting: dict[str, dict] = {}
    for name, item in reports.items():
        limit = (
            pd.Timedelta(max_gap).total_seconds() if max_gap is not None
            else max(2.5 * item["typical"], 1.5 * step)
        )
        tips = np.zeros(size)
        observed = np.zeros(size, dtype=bool)
        unknown = np.zeros(size, dtype=bool)
        no_rate = np.zeros(size, dtype=bool)
        flags = np.zeros(size, dtype=np.int64)
        gaps = multi = 0
        for begin, end, count, reset in item["intervals"]:
            target = position(end - 1e-6)
            if reset:
                flags[target] |= FLAG_COUNTER_RESET
            low = int(np.floor((begin - step / 2) / step)) + 1 - first_bin  # bins whose centre lies in (begin, end]
            high = int(np.floor((end - step / 2) / step)) - first_bin
            low, high = max(low, 0), min(high, size - 1)
            if end - begin > limit:
                gaps += 1
                moved = 0.0
                if high >= low:
                    # tips already counted in the intervals this report makes
                    # unknown move with it, so none are lost
                    span = np.arange(low, high + 1)
                    span = span[span != target]
                    moved = tips[span].sum()
                    tips[span] = 0.0
                    unknown[span] = True
                tips[target] += count + moved
                observed[target] = no_rate[target] = True
                flags[target] |= FLAG_AFTER_GAP
            elif high < low:  # the report lies inside one interval: use its centre
                where = position((begin + end) / 2)
                tips[where] += count
                observed[where] = True
            elif high == low:
                tips[low] += count
                observed[low] = True
            elif count == 0:
                observed[low:high + 1] = True  # no tip in any of them
            else:
                multi += 1
                moved = tips[low:high].sum()
                tips[low:high] = 0.0
                unknown[low:high] = True
                tips[high] += count + moved
                observed[high] = no_rate[high] = True
                flags[high] |= FLAG_MULTI_INTERVAL
        for moment in item["glitch_times"]:
            flags[position(moment)] |= FLAG_GLITCH_REMOVED
        valid = observed & ~unknown
        tips_out = np.where(valid, tips, np.nan)
        depth = tips_out * tip_depth_mm
        rate = np.where(no_rate, np.nan, depth * (3600.0 / step))
        if max_rate_mm_h is not None:
            suspect = valid & ~no_rate & (np.nan_to_num(rate, nan=0.0) > rate_limit)
        else:
            suspect = np.zeros(size, dtype=bool)
        flags[suspect] |= FLAG_SUSPECT_RATE
        depth[suspect] = np.nan
        rate[suspect] = np.nan
        columns[f"{name}_tips"] = tips_out
        columns[f"{name}_depth_mm"] = depth
        columns[f"{name}_rate_mm_h"] = rate
        columns[f"{name}_flag"] = flags
        accounting[name] = {
            "records": item["records"],
            "duplicate_timestamps": item["duplicates"],
            "bad_values_removed": item["glitches"],
            "counter_resets": item["resets"],
            "counter_wraps": item["wraps"],
            "impossible_jumps": item["jumps"],
            "gaps": gaps,
            "multi_interval_reports": multi,
            "suspect_intervals": int(suspect.sum()),
            "median_report_interval_s": item["typical"],
            "max_gap_s": limit,
        }
    result = pd.DataFrame(columns, index=index)
    result.attrs.update(
        observations.attrs,
        tip_depth_mm=tip_depth_mm,
        counter=mode,
        freq=str(freq),
        time_coordinate="start of each interval; a report is counted in the interval whose centre it covers",
        flag_meanings=FLAG_MEANINGS,
        accounting=accounting,
    )
    return result


def read_tipping_bucket(
    source: str | Path | Sequence[str | Path],
    *,
    tip_depth_mm: float,
    gauge_id: str | None = None,
    measurements: str | Sequence[str] | None = None,
    start=None,
    end=None,
    **options,
) -> pd.DataFrame:
    """Read PIERS gauge packets and return tips, depth and rate per interval.

    Combines :func:`read_gauge` and :func:`tipping_bucket_rain`; ``options``
    (``counter``, ``freq``, ``max_gap``, ``counter_max``, ``max_rate_mm_h``)
    go to :func:`tipping_bucket_rain`.
    """
    observations = read_gauge(source, gauge_id=gauge_id, start=start, end=end)
    return tipping_bucket_rain(observations, tip_depth_mm=tip_depth_mm, measurements=measurements, **options)
