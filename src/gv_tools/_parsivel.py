"""OTT Parsivel / Parsivel2 telegram decoding and drop-size-distribution parameters.

How a day is built (changed in 0.65.0)
--------------------------------------
* Every input -- a plain ``.csv``/``.dat`` file or the ``.csv``/``.dat``/``.txt``
  members of a ``.zip`` archive -- is read in memory. Nothing is extracted to
  disk and nothing is written to the working directory.
* Each source is first scanned for its earliest and latest telegram stamp (a
  byte-level look at the 14 characters before every ``;``). Sources are then
  decoded in that order and a UTC day is produced once no unread source can
  hold a telegram for it. File names are never trusted for dates, so any name
  works and a file holding parts of several days is handled correctly. Only
  the days spanned by the files being read are held in memory, and inside a
  file whose stamps never go backwards a day is produced as soon as the file
  is 30 minutes past its end, so a long time-ordered file costs about one day
  of memory.
* A telegram is accepted only when it is whole: a valid 14-digit
  ``YYYYMMDDhhmmss`` stamp, ``;``, exactly ``spectrum_offset`` header fields
  plus 1024 non-negative integer counts (a trailing comma is allowed). A line
  with one header field more or less is rejected instead of being read with
  every count shifted into the neighbouring class. A missing final newline,
  a stray quote or a non-UTF-8 byte can only cost the telegram it touches.
* Telegrams are keyed by their own time stamp, so a telegram that appears in
  more than one file (a ``*_daily`` file and its packets, overlapping
  archives) is counted once.
* Each telegram holds the drops of the measuring interval that ends at its
  stamp. The interval is inferred per telegram from the spacing of its
  neighbours (largest spacing that most neighbouring spacings are whole
  multiples of; robust to any loss rate and to a change of interval) and the
  telegram is counted in the minute that holds the centre of its interval
  (``time_binning="stamp"`` restores 0.50.0's stamp binning).
* One-minute sums are reported on a complete minute grid. Minutes without a
  telegram are missing (NaN), not dry. ``telegram_count`` and
  ``sample_duration`` (sum of the telegrams' intervals) are reported for every
  minute and every rate uses ``sample_duration``, not a fixed 60 s.

Science (changed in 0.65.0)
---------------------------
The number concentration in diameter class *i* is::

    N(D_i) dD_i = sum_j n_ij / (A_i * dt * V_ij)            [m-3]
    A_i         = 180 mm * (30 mm - D_i / 2)                (effective beam area)
    V_ij        = V_j      (measured velocity class centre, default) or
                  Vt(D_i)  (Gunn-Kinzer terminal velocity, fall_speed="theoretical")

0.50.0 divided every count by the terminal velocity of *diameter class j*
broadcast along the *velocity* axis, which mixed the two axes. Moments,
liquid water content, reflectivity, Dm, sigma_m and Nw all follow from
``N(D)`` and the flux-based rain rate uses the counted drop volume over the
effective area and the sampled time.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from importlib.resources import files as resource_files
import io
import logging
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import warnings
import zlib
from zipfile import BadZipFile, ZipFile

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)

N_CLASSES = 32
N_SPECTRUM = N_CLASSES * N_CLASSES
SPECTRUM_OFFSET = 9
SAMPLING_LENGTH_MM = 180.0
SAMPLING_WIDTH_MM = 30.0
SECONDS_PER_DAY = 86_400
MINUTES_PER_DAY = 1_440
_UNIX_EPOCH_ORDINAL = 719_163  # date(1970, 1, 1).toordinal()
_EARLIEST_STAMP = 1_104_537_600  # 2005-01-01 UTC: earlier stamps come from a logger whose clock was not set
_FUTURE_MARGIN = 30 * 86_400  # stamps more than 30 days ahead of the computer clock are impossible
_NEAR_DUPLICATE_S = 2  # equal spectra stamped this close together are one telegram logged twice

SUPPORTED_INPUT_SUFFIXES = {".zip", ".csv", ".dat"}
_MEMBER_SUFFIXES = {".csv", ".dat", ".txt"}

# A stand-alone run of 8, 10, 12 or 14 digits that begins with a valid
# 20YYMMDD date: _20260810_daily, apu04_2026081000, PIERS..._20260810001005.
FILENAME_STAMP = re.compile(
    r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])((?:\d{2}){0,3})(?!\d)"
)
# Kept for callers of 0.50.x. Accepts a stand-alone date with an optional
# joined or underscore-separated hour, preserving the 0.50.1 filename fix.
DATE_PATTERN = re.compile(
    r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])"
    r"(?:_?(?:[01]\d|2[0-3]))?(?!\d)"
)
_TELEGRAM_START = re.compile(r"(?<!\d)(\d{14});", re.ASCII)

FALL_SPEED_METHODS = ("measured", "theoretical")
CLASS_TABLES = ("ott", "legacy")


# ---------------------------------------------------------------------------
# Class definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParsivelClasses:
    """Diameter/velocity class definitions and the velocity-diameter filter."""

    name: str
    diameter: np.ndarray
    diameter_width: np.ndarray
    velocity: np.ndarray
    velocity_width: np.ndarray
    terminal_velocity: np.ndarray
    mask: np.ndarray  # bool, (diameter, velocity)
    description: str = ""
    settings: dict = field(default_factory=dict)

    @property
    def sampling_area_mm2(self) -> np.ndarray:
        """Effective Parsivel sampling area for each diameter class (mm2)."""
        return SAMPLING_LENGTH_MM * (SAMPLING_WIDTH_MM - self.diameter / 2.0)


def _data_root():
    return resource_files("gv_tools").joinpath("data", "parsivel")


def _read_two_columns(name: str) -> tuple[np.ndarray, np.ndarray]:
    text = _data_root().joinpath(name).read_text(encoding="ascii")
    values = np.loadtxt(io.StringIO(text), comments="#", dtype=float)
    return values[:, 0], values[:, 1]


def terminal_velocity(diameter_mm) -> np.ndarray:
    """Raindrop terminal fall speed (m s-1) near sea level after Gunn & Kinzer (1949).

    Values are linearly interpolated from the bundled 0.2 mm table. Below
    0.1 mm the Stokes-regime scaling ``V ~ D**2`` is used and above the table
    (11.9 mm) the speed stays at its 9.175 m s-1 plateau.
    """
    text = _data_root().joinpath("terminal_velocity_gunn_kinzer.txt").read_text(encoding="ascii")
    table = np.loadtxt(io.StringIO(text), comments="#", dtype=float)
    d_table, v_table = table[:, 0], table[:, 2]
    diameter = np.asarray(diameter_mm, dtype=float)
    speed = np.interp(diameter, d_table, v_table)
    small = diameter < d_table[0]
    speed = np.where(small, v_table[0] * (diameter / d_table[0]) ** 2, speed)
    return np.where(diameter > 0, speed, 0.0)


def velocity_filter_mask(
    diameter, velocity, terminal, *, tolerance: float | None = 0.5, max_diameter_mm: float | None = 10.0
) -> np.ndarray:
    """Return the boolean (diameter, velocity) mask of plausible raindrop cells.

    A cell is kept when its velocity class centre lies within
    ``(1 - tolerance) * Vt(D) .. (1 + tolerance) * Vt(D)`` and the diameter class
    centre is below ``max_diameter_mm``. ``tolerance=None`` keeps every
    velocity; ``max_diameter_mm=None`` keeps every diameter.
    """
    diameter = np.asarray(diameter, dtype=float)
    velocity = np.asarray(velocity, dtype=float)
    terminal = np.asarray(terminal, dtype=float)
    if tolerance is None:
        mask = np.ones((diameter.size, velocity.size), dtype=bool)
    else:
        tolerance = float(tolerance)
        if not 0 < tolerance:
            raise ValueError("velocity_filter must be positive or None")
        lower = (1.0 - tolerance) * terminal[:, None]
        upper = (1.0 + tolerance) * terminal[:, None]
        mask = (velocity[None, :] >= lower) & (velocity[None, :] <= upper)
    if max_diameter_mm is not None:
        mask &= (diameter < float(max_diameter_mm))[:, None]
    return mask


def _ott_classes(velocity_filter, max_diameter_mm) -> ParsivelClasses:
    diameter, diameter_width = _read_two_columns("diameter.dat")
    velocity, velocity_width = _read_two_columns("velocity.dat")
    terminal = terminal_velocity(diameter)
    mask = velocity_filter_mask(
        diameter, velocity, terminal, tolerance=velocity_filter, max_diameter_mm=max_diameter_mm
    )
    return ParsivelClasses(
        name="ott",
        diameter=diameter,
        diameter_width=diameter_width,
        velocity=velocity,
        velocity_width=velocity_width,
        terminal_velocity=terminal,
        mask=mask,
        description=(
            "OTT Parsivel2 class centres and widths (manual); velocity filter "
            f"+/-{velocity_filter} x Gunn-Kinzer Vt(D); classes below {max_diameter_mm} mm"
        ),
        settings={"velocity_filter": velocity_filter, "max_diameter_mm": max_diameter_mm},
    )


def _legacy_mask_frame(table_dir=None) -> pd.DataFrame:
    root = Path(table_dir) if table_dir else _data_root()
    return pd.read_csv(root.joinpath("parsivel_conditional_matrix.txt"), header=None)


def _legacy_table_frame(table_dir=None) -> pd.DataFrame:
    root = Path(table_dir) if table_dir else _data_root()
    return pd.read_csv(root.joinpath("parsivel_diameter_py.txt"), sep=r"\s+")


def classes_from_tables(dv_parms: pd.DataFrame, df_mask: pd.DataFrame, *, name="table") -> ParsivelClasses:
    """Build class definitions from 0.50.0-style tables (``load_tables`` output)."""
    required = {"Drop_bin", "Measured_Vt", "Theoretical_Vt", "Delta-D"}
    missing = required.difference(dv_parms.columns)
    if missing:
        raise ValueError(f"Diameter table is missing columns: {sorted(missing)}")
    matrix = np.nan_to_num(df_mask.to_numpy(dtype=float)[:, :N_CLASSES], nan=0.0)
    if len(dv_parms) != N_CLASSES or matrix.shape != (N_CLASSES, N_CLASSES):
        raise ValueError(
            f"Expected 32 bins and a 32x32 mask; got {len(dv_parms)} and {df_mask.shape}"
        )
    _, velocity_width = _read_two_columns("velocity.dat")
    # The mask file is stored with velocity classes in rows and diameter
    # classes in columns; transpose to (diameter, velocity).
    mask = matrix.T != 0
    return ParsivelClasses(
        name=name,
        diameter=dv_parms["Drop_bin"].to_numpy(float),
        diameter_width=dv_parms["Delta-D"].to_numpy(float),
        velocity=dv_parms["Measured_Vt"].to_numpy(float),
        velocity_width=velocity_width,
        terminal_velocity=dv_parms["Theoretical_Vt"].to_numpy(float),
        mask=mask,
        description="Classes and mask read from parsivel_diameter_py.txt / parsivel_conditional_matrix.txt",
    )


def _legacy_classes(table_dir=None) -> ParsivelClasses:
    table = _legacy_table_frame(table_dir)
    mask_frame = _legacy_mask_frame(table_dir)
    classes = classes_from_tables(table, mask_frame, name="legacy")
    mask = classes.mask.copy()
    if table_dir is None and mask[24, 20]:
        # The bundled 0.50.0 matrix keeps one isolated cell, 9.5 mm drops at
        # 4.4 m s-1, outside the +/-50 % band every other cell follows.
        mask[24, 20] = False
    return ParsivelClasses(
        name="legacy",
        diameter=classes.diameter,
        diameter_width=classes.diameter_width,
        velocity=classes.velocity,
        velocity_width=classes.velocity_width,
        terminal_velocity=classes.terminal_velocity,
        mask=mask,
        description=(
            "0.50.0 tables: diameters and widths scaled by 1.03 from the OTT classes, "
            "the table's Measured_Vt column as velocity centres, bundled conditional matrix"
        ),
    )


def get_parsivel_classes(
    classes: str = "ott",
    *,
    velocity_filter: float | None = 0.5,
    max_diameter_mm: float | None = 10.0,
    table_dir: str | os.PathLike[str] | None = None,
) -> ParsivelClasses:
    """Return the class definitions used to integrate Parsivel spectra.

    ``classes="ott"`` (default) uses the OTT Parsivel2 class centres/widths and
    rebuilds the velocity filter from ``velocity_filter`` and
    ``max_diameter_mm``. ``classes="legacy"`` reproduces the 0.50.0 tables. A
    ``table_dir`` holding 0.50.0-format tables overrides both.
    """
    if table_dir is not None:
        return _legacy_classes(table_dir)
    key = str(classes).strip().lower()
    if key == "ott":
        return _ott_classes(velocity_filter, max_diameter_mm)
    if key == "legacy":
        return _legacy_classes()
    raise ValueError(f"classes must be one of {CLASS_TABLES}")


def load_tables(table_dir: str | os.PathLike[str] | None = None, *, classes: str = "ott"):
    """Return ``(dv_parms, mask)`` in the 0.50.0 table layout.

    ``dv_parms`` has the columns ``Drop_bin``, ``Delta-D``, ``Theoretical_Vt``,
    ``Measured_Vt`` (velocity class centre), ``50%>Velt`` and ``50%<Velt``.
    ``mask`` is 32 x 33 with velocity classes in rows, diameter classes in
    columns and an empty last column, exactly like the bundled file. With
    ``table_dir`` the files there are read unchanged.
    """
    if table_dir is not None:
        dv = _legacy_table_frame(table_dir)
        mask = _legacy_mask_frame(table_dir)
        classes_from_tables(dv, mask)  # validates
        return dv, mask
    selected = get_parsivel_classes(classes)
    dv = pd.DataFrame(
        {
            "Drop_bin": selected.diameter,
            "Delta-D": selected.diameter_width,
            "Theoretical_Vt": selected.terminal_velocity,
            "Measured_Vt": selected.velocity,
            "50%>Velt": 0.5 * selected.terminal_velocity,
            "50%<Velt": 1.5 * selected.terminal_velocity,
        }
    )
    matrix = np.full((N_CLASSES, N_CLASSES + 1), np.nan)
    matrix[:, :N_CLASSES] = selected.mask.T.astype(float)
    return dv, pd.DataFrame(matrix)


# ---------------------------------------------------------------------------
# Telegram parsing
# ---------------------------------------------------------------------------

_DAY_START_CACHE: dict[str, int | None] = {}


def _epoch_seconds(stamp: str) -> int | None:
    """Convert a 14-digit ``YYYYMMDDhhmmss`` stamp to seconds since 1970-01-01 UTC."""
    key = stamp[:8]
    start = _DAY_START_CACHE.get(key, -1)
    if start == -1:
        try:
            start = (
                date(int(key[0:4]), int(key[4:6]), int(key[6:8])).toordinal() - _UNIX_EPOCH_ORDINAL
            ) * SECONDS_PER_DAY
        except ValueError:
            start = None
        if len(_DAY_START_CACHE) < 200_000:
            _DAY_START_CACHE[key] = start
    if start is None:
        return None
    hour, minute, second = int(stamp[8:10]), int(stamp[10:12]), int(stamp[12:14])
    if hour > 23 or minute > 59 or second > 59:
        return None
    return start + hour * 3600 + minute * 60 + second


def _slow_spectrum(fields: Sequence[str]) -> np.ndarray | None:
    values = np.empty(N_SPECTRUM, dtype=np.int64)
    for index, raw in enumerate(fields):
        token = raw.replace(" ", "").strip()
        if token in ("", "None"):
            values[index] = 0
            continue
        try:
            values[index] = int(token)
        except ValueError:
            try:
                number = float(token)
            except ValueError:
                return None
            if not np.isfinite(number) or not float(number).is_integer():
                return None
            values[index] = int(number)
    return values


_OK, _BAD_LAYOUT, _BAD_VALUE = 0, 1, 2


def _spectrum_counts(body: str, offset: int, strict: bool = True) -> tuple[np.ndarray | None, int]:
    """Return ``(counts, status)`` for one telegram body (the text after ``;``).

    With ``strict`` the body must hold exactly ``offset`` header fields and
    1024 counts, optionally followed by one empty field (a trailing comma).
    A telegram with one header field more or less would otherwise be read
    with every count shifted into the neighbouring diameter class.
    """
    body = body.rstrip()
    # Fields, not counting one empty field after a trailing comma.
    fields_present = body.count(",") + (0 if body.endswith(",") else 1)
    expected = offset + N_SPECTRUM
    if fields_present != expected and (strict or fields_present < expected):
        return None, _BAD_LAYOUT
    rest = body.split(",", offset)[offset] if offset else body
    values = None
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        try:
            parsed = np.fromstring(rest, dtype=np.int64, sep=",")
        except (ValueError, DeprecationWarning):
            parsed = None
    if parsed is not None and (parsed.size == N_SPECTRUM or (not strict and parsed.size > N_SPECTRUM)):
        values = parsed[:N_SPECTRUM]
    else:
        fields = rest.split(",", N_SPECTRUM)
        if len(fields) < N_SPECTRUM:
            return None, _BAD_LAYOUT
        values = _slow_spectrum(fields[:N_SPECTRUM])
        if values is None:
            return None, _BAD_VALUE
    if values.min() < 0 or values.max() > np.iinfo(np.uint16).max:
        return None, _BAD_VALUE
    return values.astype(np.uint16), _OK


def _segments(text: str):
    """Split a line into ``(stamp, body)`` telegram segments."""
    stamp, separator, body = text.partition(";")
    if separator and len(stamp) == 14 and stamp.isascii() and stamp.isdigit() and ";" not in body:
        return [(stamp, body)]
    starts = [match.start() for match in _TELEGRAM_START.finditer(text)]
    bounds = [*starts, len(text)]
    return [
        (text[begin:begin + 14], text[begin + 15:end].rstrip())
        for begin, end in zip(bounds[:-1], bounds[1:])
    ]


def parse_telegram_line(line: str, *, spectrum_offset: int = SPECTRUM_OFFSET, strict_fields: bool = True,
                        _layout: list | None = None):
    """Return ``(telegrams, rejected)`` for one text line.

    ``telegrams`` is a list of ``(epoch_seconds, counts)`` with ``counts`` a
    ``uint16`` array of the 1024 raw spectrum values in instrument order.
    Two telegrams run together on one line are split at their time stamps
    and text before a time stamp is ignored.
    """
    text = line.strip("\x00 \t\r\n﻿")
    if not text:
        return [], 0
    segments = _segments(text)
    if not segments:
        return [], 1
    telegrams = []
    rejected = 0
    for stamp, body in segments:
        epoch = _epoch_seconds(stamp) if len(stamp) == 14 and stamp.isascii() and stamp.isdigit() else None
        if epoch is None:
            rejected += 1
            continue
        counts, status = _spectrum_counts(body, spectrum_offset, strict_fields)
        if counts is None:
            rejected += 1
            if status == _BAD_LAYOUT and _layout is not None:
                trimmed = body.rstrip()
                _layout.append(trimmed.count(",") + (0 if trimmed.endswith(",") else 1))
            continue
        telegrams.append((epoch, counts))
    return telegrams, rejected


@dataclass
class _Source:
    """One readable text stream: a plain file or a member of an archive."""

    label: str
    path: Path
    member: str | None = None
    priority: int = 1  # 0 for *_daily files: on equal start they are read first
    first: int | None = None  # earliest telegram stamp (epoch s), from _scan
    last: int | None = None
    ordered: bool = False  # stamps never decrease through the source
    days: frozenset = frozenset()  # UTC day numbers of the usable stamps, from _scan

    @contextmanager
    def binary(self):
        if self.member is None:
            with self.path.open("rb") as stream:
                yield stream
        else:
            with ZipFile(self.path) as archive, archive.open(self.member) as stream:
                yield stream

    def lines(self) -> Iterator[str]:
        with self.binary() as raw:
            yield from io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline=None)


_SEMICOLON = re.compile(rb";")
_READ_ERRORS = (OSError, EOFError, BadZipFile, zlib.error)


def _stamps_before_semicolons(data: bytes, start: int = 0) -> list[bytes]:
    """14-digit stamps that directly precede a ``;`` (and are not part of a longer number).

    Only semicolons at or after ``start`` are examined; ``data[0]`` must be
    the start of the stream whenever fewer than 15 bytes precede ``start``.
    """
    found = []
    for match in _SEMICOLON.finditer(data, start):
        end = match.start()
        if end < 14:
            continue
        stamp = data[end - 14:end]
        if stamp.isdigit() and (end == 14 or not data[end - 15:end - 14].isdigit()):
            found.append(stamp)
    return found


def _usable_epoch(epoch: int | None, latest: int | None) -> bool:
    """True for a stamp that can belong to a Parsivel telegram (2005 to ``latest``)."""
    return epoch is not None and epoch >= _EARLIEST_STAMP and (latest is None or epoch <= latest)


def _latest_stamp() -> int:
    """Latest possible telegram stamp: the computer clock plus 30 days (a little clock error is allowed)."""
    return int(time.time()) + _FUTURE_MARGIN


def _scan(source: _Source, latest: int | None = None) -> tuple[int, int] | None:
    """Return the earliest and latest usable telegram stamp in a source (epoch seconds).

    Only the 14 bytes before each ``;`` are looked at, in 8 MB chunks, so this
    is far cheaper than decoding. Stamps that are not a calendar time, or lie
    before 2005 or after ``latest``, are ignored here as the decoder ignores
    them. Processing order and the release of finished days rely on these
    spans, not on file names. The scan also records the UTC days of the
    stamps (``source.days``) and whether the stamps never decrease
    (``source.ordered``), which lets days be released while a long source is
    still being read.
    """
    low = high = previous = None
    ordered = True
    day_keys: set[bytes] = set()
    tail = b""
    try:
        with source.binary() as stream:
            while True:
                chunk = stream.read(1 << 23)
                if not chunk:
                    break
                data = tail + chunk
                found = _stamps_before_semicolons(data, len(tail))
                # the 15 bytes a stamp and its preceding byte need; semicolons
                # inside them were examined with this chunk
                tail = data[-15:]
                if not found:
                    continue
                if ordered:
                    sequence = found if previous is None else [previous, *found]
                    if not all(a <= b for a, b in zip(sequence, sequence[1:])):
                        # judge the order on the stamps the decoder will use
                        sequence = [
                            stamp for stamp in sequence if _usable_epoch(_epoch_seconds(stamp.decode()), latest)
                        ]
                        ordered = all(a <= b for a, b in zip(sequence, sequence[1:]))
                for stamp in reversed(found):
                    if _usable_epoch(_epoch_seconds(stamp.decode()), latest):
                        previous = stamp
                        break
                day_keys.update(stamp[:8] for stamp in found)
                # 14-digit stamps sort like the times they encode, so the
                # extremes only need checking; an impossible extreme costs one
                # pass over this chunk's stamps
                first = _epoch_seconds(min(found).decode())
                last = _epoch_seconds(max(found).decode())
                if not (_usable_epoch(first, latest) and _usable_epoch(last, latest)):
                    usable = [
                        epoch for epoch in (_epoch_seconds(stamp.decode()) for stamp in found)
                        if _usable_epoch(epoch, latest)
                    ]
                    if not usable:
                        continue
                    first, last = min(usable), max(usable)
                low = first if low is None else min(low, first)
                high = last if high is None else max(high, last)
    except _READ_ERRORS as exc:
        # Keep what was readable (e.g. an archive member with a bad CRC is
        # only detected at its end); each telegram is still validated. The
        # decoder may read further than the scan did, so the order of the
        # rest is unknown.
        LOGGER.warning("Input %s is damaged (%s); using the telegrams before the damage", source.label, exc)
        ordered = False
    if low is None:
        return None
    days = set()
    for key in day_keys:
        start = _epoch_seconds(key.decode() + "000000")
        if start is not None and start + SECONDS_PER_DAY > _EARLIEST_STAMP and (latest is None or start <= latest):
            days.add(start // SECONDS_PER_DAY)
    source.ordered = ordered
    source.days = frozenset(days)
    return low, high


def _iter_paths(input_path) -> list[tuple[Path, bool]]:
    """Return ``(path, found_in_directory)`` for every supported input."""
    items = [input_path] if isinstance(input_path, (str, os.PathLike)) else list(input_path)
    found: list[tuple[Path, bool]] = []
    for item in items:
        path = Path(item).expanduser()
        if path.is_file():
            if path.suffix.lower() not in SUPPORTED_INPUT_SUFFIXES:
                raise ValueError(f"Unsupported input type {path.suffix!r}; use ZIP, CSV, or DAT")
            found.append((path, False))
        elif path.is_dir():
            found.extend(
                (candidate, True) for candidate in sorted(path.rglob("*"))
                if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_INPUT_SUFFIXES
            )
        else:
            raise FileNotFoundError(f"Input does not exist: {path}")
    return list(dict.fromkeys(found))


def _sources(path: Path) -> list[_Source]:
    priority = 0 if "_daily" in path.name.casefold() else 1
    if path.suffix.lower() != ".zip":
        return [_Source(path.name, path, priority=priority)]
    try:
        with ZipFile(path) as archive:
            members = [
                member.filename for member in archive.infolist()
                if not member.is_dir()
                and "__MACOSX" not in Path(member.filename).parts
                and Path(member.filename).suffix.lower() in _MEMBER_SUFFIXES
            ]
    except _READ_ERRORS as exc:
        LOGGER.warning("Skipping unreadable archive %s: %s", path.name, exc)
        return []
    return [
        _Source(
            path.name if Path(member).stem == path.stem else f"{path.name}:{member}",
            path, member, priority=priority,
        )
        for member in members
    ]


def _stamp_info(name: str) -> tuple[pd.Timestamp, bool] | None:
    for match in FILENAME_STAMP.finditer(Path(name).name):
        digits = "".join(match.groups())
        pattern = {8: "%Y%m%d", 10: "%Y%m%d%H", 12: "%Y%m%d%H%M", 14: "%Y%m%d%H%M%S"}[len(digits)]
        try:
            return pd.Timestamp(datetime.strptime(digits, pattern)), len(digits) > 8
        except ValueError:
            continue
    return None


def filename_stamp(name: str) -> pd.Timestamp | None:
    """Return the date/time stamp encoded in a Parsivel file name, if any.

    Accepts stand-alone 8-, 10-, 12- or 14-digit stamps: ``*_20260810_daily``,
    ``apu04_2026081000.zip`` and ``PIERS0042_Parsivel_20260810001005.zip``.
    """
    info = _stamp_info(name)
    return None if info is None else info[0]


def _name_outside_window(path: Path, first_day, last_day) -> bool:
    """True for a directory file whose name shows it is a packet/daily file far outside the window.

    Only names that describe at most one day (a 10/12/14-digit packet stamp or
    a ``*_daily`` file) are skipped, with one day of margin; files named by
    the user are never skipped by name.
    """
    if first_day is None and last_day is None:
        return False
    info = _stamp_info(path.name)
    if info is None:
        return False
    stamp, has_time = info
    if not has_time and "_daily" not in path.name.casefold():
        return False
    day = _day_number(stamp)
    return (first_day is not None and day < first_day - 1) or (last_day is not None and day > last_day + 1)


# ---------------------------------------------------------------------------
# Telegram interval (sample duration)
# ---------------------------------------------------------------------------

_CADENCE_HALF_WINDOW = 15  # gaps on each side of a telegram
_CADENCE_MIN_SUPPORT = 3
_NEIGHBOUR_REACH = 2 * _CADENCE_HALF_WINDOW  # telegrams an inconclusive telegram may borrow across
_MIN_INTERVAL_S = 10  # shortest Parsivel measuring interval (OTT: 10 s to 1 h)
_MAX_INTERVAL_S = 3600  # longest Parsivel measuring interval
_HALF_SPAN = _MAX_INTERVAL_S // 2  # a telegram's sampling centre is at most this far before its stamp


def _snap_gaps(gaps: np.ndarray) -> np.ndarray:
    """Remove +/-1 s logger jitter from gaps near a multiple of 5 s."""
    gaps = np.asarray(gaps, dtype=np.float64)
    nearest = np.round(gaps / 5.0) * 5.0
    return np.where((nearest > 0) & (np.abs(gaps - nearest) <= 1.0), nearest, gaps)


def _cadence_candidates(gaps: np.ndarray) -> np.ndarray:
    """The 8 most frequent gap values that can be a measuring interval (>= 10 s)."""
    values, counts = np.unique(gaps, return_counts=True)
    possible = values >= _MIN_INTERVAL_S - 0.5
    values, counts = values[possible], counts[possible]
    return np.sort(values[np.argsort(-counts, kind="stable")[:8]])


def _consistency(gaps: np.ndarray, candidates: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(is a whole multiple of the candidate, equals the candidate) for each candidate x gap."""
    multiple = np.round(gaps[None, :] / candidates[:, None])
    is_multiple = (multiple >= 1) & (np.abs(gaps[None, :] - candidates[:, None] * multiple) <= 1.0)
    is_equal = np.abs(gaps[None, :] - candidates[:, None]) <= 1.0
    return is_multiple, is_equal


def _pick(multiple_share: np.ndarray, equal_count: np.ndarray, candidates: np.ndarray):
    """Largest candidate that >= 80 % of the gaps are multiples of and that occurs >= 3 times.

    Returns the pick and the number of gaps equal to it (NaN / 0 when none).
    """
    ok = (multiple_share >= 0.8) & (equal_count >= _CADENCE_MIN_SUPPORT)
    chosen = np.where(ok, candidates[:, None], -np.inf)
    best = chosen.argmax(axis=0)
    columns = np.arange(chosen.shape[1])
    pick = chosen[best, columns]
    support = np.where(np.isfinite(pick), equal_count[best, columns], 0)
    return np.where(np.isfinite(pick), pick, np.nan), support


def _mode(gaps: np.ndarray, min_support: int = _CADENCE_MIN_SUPPORT) -> float | None:
    """Measuring interval of a whole gap sequence (see :func:`_rolling_mode`), if clear."""
    gaps = np.asarray(gaps, dtype=np.float64)
    gaps = gaps[np.isfinite(gaps)]
    if gaps.size == 0:
        return None
    candidates = _cadence_candidates(gaps)
    is_multiple, is_equal = _consistency(gaps, candidates)
    ok = (is_multiple.mean(axis=1) >= 0.8) & (is_equal.sum(axis=1) >= min_support)
    return float(candidates[ok].max()) if ok.any() else None


def _most_common(values: np.ndarray) -> float | None:
    """Most frequent value (the smallest on a tie), or None for no values."""
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return None
    unique, counts = np.unique(values, return_counts=True)
    return float(unique[np.argmax(counts)])


def _rolling_mode(gaps: np.ndarray) -> np.ndarray:
    """Measuring interval of the telegram that closes each gap (NaN when it cannot be told).

    A lost telegram makes a gap a whole multiple of the measuring interval,
    so over a window of gaps the interval is the largest gap value that (a)
    at least 80 % of the window's gaps are whole multiples of and (b) itself
    occurs at least three times. This holds for any loss rate, whereas a
    median doubles once half the telegrams are missing. The rule is applied
    to the 15 gaps before, the 15 gaps after and the 31 gaps around each
    gap; the largest answer that does not exceed the gap itself is kept
    (measuring intervals cannot overlap), which keeps a change of the
    logger's interval sharp.
    """
    size = gaps.size
    candidates = _cadence_candidates(gaps)
    if candidates.size == 0:
        return np.full(size, np.nan)
    is_multiple, is_equal = _consistency(gaps, candidates)
    cumulative_multiple = np.concatenate(
        [np.zeros((candidates.size, 1), np.int64), np.cumsum(is_multiple, axis=1, dtype=np.int64)], axis=1
    )
    cumulative_equal = np.concatenate(
        [np.zeros((candidates.size, 1), np.int64), np.cumsum(is_equal, axis=1, dtype=np.int64)], axis=1
    )
    position = np.arange(size)
    half = _CADENCE_HALF_WINDOW
    picks, strength = [], []
    for before, after in ((half, half), (half, 0), (0, half)):
        low = np.clip(position - before, 0, size)
        high = np.clip(position + after + 1, 0, size)
        share = (cumulative_multiple[:, high] - cumulative_multiple[:, low]) / (high - low)[None, :]
        pick, support = _pick(share, cumulative_equal[:, high] - cumulative_equal[:, low], candidates)
        picks.append(pick)
        strength.append(support / (high - low))
    picks, strength = np.vstack(picks), np.vstack(strength)
    allowed = np.isfinite(picks) & (picks <= gaps[None, :] + 1.0)
    # The window whose answer explains most of its gaps exactly wins; on a
    # tie the centred window (listed first) is kept.
    strength = np.where(allowed, strength, -1.0)
    best = strength.argmax(axis=0)
    result = picks[best, position]
    result[~allowed[best, position]] = np.nan
    return result


def telegram_intervals(times, *, fallback: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Return the measuring interval (s) of each telegram and how it was found.

    ``times`` are sorted, unique telegram stamps (s). Each telegram gets the
    most frequent spacing in its neighbourhood (rolling mode, see
    :func:`_rolling_mode`). A telegram whose own windows are inconclusive (a
    stamp delayed by a few seconds, a short burst of irregular spacings) takes
    the interval of the nearest telegram, within 30 telegrams, that has one;
    the rest get the sequence's most frequent spacing (or, when the spacings
    are too irregular for one, its most common local answer), then
    ``fallback``. The
    second array holds ``"local"``, ``"neighbour"``, ``"sequence"``,
    ``"fallback"`` or ``"none"``.
    """
    times = np.asarray(times, dtype=np.float64)
    size = times.size
    intervals = np.full(size, np.nan)
    source = np.full(size, "none", dtype=object)
    if size >= 2:
        gaps = _snap_gaps(np.diff(times))
        gaps = np.where(gaps > _MAX_INTERVAL_S, np.nan, gaps)
        usable = np.isfinite(gaps)
        local = np.full(gaps.size, np.nan)
        if usable.any():
            local[usable] = _rolling_mode(gaps[usable])
        # telegram i closes the gap before it; the first telegram uses gap 0
        per_telegram = np.r_[local[:1], local]
        found = np.isfinite(per_telegram)
        intervals[found], source[found] = per_telegram[found], "local"
        if found.any() and not found.all():
            known, unknown = np.flatnonzero(found), np.flatnonzero(~found)
            after = np.searchsorted(known, unknown)
            before = known[np.clip(after - 1, 0, known.size - 1)]
            after = known[np.clip(after, 0, known.size - 1)]
            nearest = np.where(np.abs(unknown - before) <= np.abs(after - unknown), before, after)
            close = np.abs(nearest - unknown) <= _NEIGHBOUR_REACH
            intervals[unknown[close]] = per_telegram[nearest[close]]
            source[unknown[close]] = "neighbour"
        sequence = _mode(gaps[usable]) if usable.any() else None
        if sequence is None and found.any():
            # spacings too irregular for one answer: the most common local one
            sequence = _most_common(per_telegram[found])
        missing = ~np.isfinite(intervals)
        if sequence is not None and missing.any():
            intervals[missing], source[missing] = sequence, "sequence"
    missing = ~np.isfinite(intervals)
    if fallback is not None and missing.any():
        intervals[missing], source[missing] = float(fallback), "fallback"
    return intervals, source


# ---------------------------------------------------------------------------
# Day assembly
# ---------------------------------------------------------------------------


def _day_number(value) -> int | None:
    if value is None:
        return None
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("UTC").tz_localize(None)
    return int(stamp.normalize().value // 1_000_000_000 // SECONDS_PER_DAY)


def _day_label(day: int) -> str:
    return pd.Timestamp(day * SECONDS_PER_DAY, unit="s").strftime("%Y-%m-%d")


class _Assembler:
    """Pool telegrams by time stamp and turn finished UTC days into products."""

    def __init__(self, classes, *, fall_speed, telegram_interval_s, full_day, include_spectrum,
                 spectrum_offset, strict_fields, time_binning, first_day, last_day, latest=None):
        self.classes = classes
        self.fall_speed = fall_speed
        self.user_interval = None if telegram_interval_s is None else float(telegram_interval_s)
        self.full_day = full_day
        self.include_spectrum = include_spectrum
        self.spectrum_offset = int(spectrum_offset)
        self.strict_fields = strict_fields
        self.time_binning = time_binning
        self.first_day, self.last_day = first_day, last_day
        self.keep_from = None if first_day is None else first_day * SECONDS_PER_DAY - _HALF_SPAN
        self.keep_until = None if last_day is None else (last_day + 1) * SECONDS_PER_DAY + _HALF_SPAN
        self.latest = latest
        self.spectra: dict[int, np.ndarray] = {}
        self.origin: dict[int, int] = {}
        self.labels: list[str] = []
        self.source_days: list[frozenset] = []
        self.rejected: list[int] = []
        self.duplicates: dict[int, int] = {}
        self.conflicts: dict[int, int] = {}
        self.layout_fields: list[int] = []
        self.late = 0
        self.impossible = 0
        self.released_until: int | None = None  # end of the last day produced (s)
        self.released_through: int | None = None  # last day produced (day number)
        self.frozen: dict[int, tuple[float, str]] = {}  # intervals of telegrams left for the next day
        self.context = np.empty(0, dtype=np.int64)
        self.previous_interval: float | None = None
        self.assumed_warned = False

    # -- reading ---------------------------------------------------------
    def read(self, source: _Source, cap: int | None = None):
        """Decode one source; yield days that become complete while reading it.

        Days can only complete inside a source whose stamps never decrease
        (``source.ordered``): once its stamps pass ``day end + _HALF_SPAN`` no
        later line can belong to the day, so the pool holds at most the day
        being read and the 30 minutes after it. ``cap`` is the release limit
        set by the sources not yet read. With a date window, single-telegram
        lines stamped outside it are skipped without decoding their spectrum,
        and an ordered source is closed at the first stamp after it.
        """
        label_id = len(self.labels)
        self.labels.append(source.label)
        self.source_days.append(source.days)
        self.rejected.append(0)
        rejected = 0
        release_at = None  # stamp from which the earliest pooled day can be released
        windowed = self.keep_from is not None or self.keep_until is not None
        keep_from = -math.inf if self.keep_from is None else self.keep_from
        keep_until = math.inf if self.keep_until is None else self.keep_until
        try:
            for line in source.lines():
                if windowed and line[14:15] == ";" and line.find(";", 15) == -1:
                    stamp = line[:14]
                    epoch = _epoch_seconds(stamp) if stamp.isascii() and stamp.isdigit() else None
                    if epoch is not None and not keep_from <= epoch < keep_until:
                        if source.ordered and epoch >= keep_until and _usable_epoch(epoch, self.latest):
                            break  # every later telegram of this source is after the window
                        continue
                telegrams, bad = parse_telegram_line(
                    line, spectrum_offset=self.spectrum_offset, strict_fields=self.strict_fields,
                    _layout=self.layout_fields,
                )
                rejected += bad
                for epoch, counts in telegrams:
                    if not self._add(epoch, counts, label_id):
                        rejected += 1  # impossible time stamp
                        continue
                    if source.ordered and (release_at is None or epoch >= release_at):
                        limit = epoch - _HALF_SPAN if cap is None else min(epoch - _HALF_SPAN, cap)
                        self.rejected[label_id] = rejected
                        yield from self.release(limit)
                        release_at = self._release_at(cap)
        except _READ_ERRORS as exc:
            LOGGER.warning("Stopped reading %s: %s", source.label, exc)
        self.rejected[label_id] = rejected
        if rejected:
            LOGGER.info("%s: %d line(s) were not complete telegrams", source.label, rejected)

    def _add(self, epoch: int, counts: np.ndarray, label_id: int) -> bool:
        """Pool one telegram; False when its stamp is impossible (before 2005 or far in the future)."""
        if not _usable_epoch(epoch, self.latest):
            self.impossible += 1
            return False
        if (self.keep_from is not None and epoch < self.keep_from) or (
            self.keep_until is not None and epoch >= self.keep_until
        ):
            return True
        if self.released_until is not None and epoch < self.released_until:
            self.late += 1  # belongs to a day already produced
            return True
        known = self.spectra.get(epoch)
        day = epoch // SECONDS_PER_DAY
        if known is None:
            self.spectra[epoch] = counts
            self.origin[epoch] = label_id
        elif np.array_equal(known, counts):
            self.duplicates[day] = self.duplicates.get(day, 0) + 1
        else:
            self.conflicts[day] = self.conflicts.get(day, 0) + 1
        return True

    # -- releasing -------------------------------------------------------
    def _next_day(self) -> int:
        """The day the earliest pooled telegram can belong to that is not produced yet."""
        day = (min(self.spectra) - _HALF_SPAN) // SECONDS_PER_DAY
        return day if self.released_through is None else max(day, self.released_through + 1)

    def _release_at(self, cap: int | None) -> float | None:
        """First stamp of an ordered source at which ``release`` can produce a day."""
        if not self.spectra:
            return None  # decide after the next telegram
        day_end = (self._next_day() + 1) * SECONDS_PER_DAY
        if cap is not None and day_end > cap:
            return math.inf  # held back by an unread source
        return day_end + _HALF_SPAN

    def release(self, upto: int | None):
        """Yield ``(YYYY-MM-DD, frames)`` for every day ending at or before ``upto``.

        Each pass produces the day of the earliest pooled telegram (or the day
        after the last one produced, if later). That telegram is consumed by
        this day or the next, and the day number only grows, so the loop
        always ends. A day that cannot be produced yet is not remembered:
        telegrams for earlier days may still be added.
        """
        while self.spectra:
            day = self._next_day()
            day_end = (day + 1) * SECONDS_PER_DAY
            if upto is not None and day_end > upto:
                break
            frames = self._release_day(day)
            self.released_through = day
            self.released_until = day_end
            if frames is not None:
                yield _day_label(day), frames

    def _intervals(self, keys: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if self.user_interval is not None:
            return np.full(keys.size, self.user_interval), np.full(keys.size, "user", dtype=object)
        context = self.context[self.context < (keys[0] if keys.size else 0)]
        times = np.r_[context, keys]
        intervals, source = telegram_intervals(times)
        intervals, source = intervals[context.size:], source[context.size:]
        missing = ~np.isfinite(intervals)
        if missing.any():
            fallback, how = self.previous_interval, "previous_day"
            if fallback is None:
                pool = np.sort(np.fromiter(self.spectra, dtype=np.int64, count=len(self.spectra)))
                gaps = _snap_gaps(np.diff(pool))
                fallback, how = _mode(gaps[gaps <= _MAX_INTERVAL_S]), "later_telegrams"
            if fallback is None:
                fallback, how = 60.0, "assumed"
                if not self.assumed_warned:
                    LOGGER.warning(
                        "Too few telegrams to infer the Parsivel measuring interval near %s; "
                        "assuming 60 s (pass telegram_interval_s to set it)",
                        pd.Timestamp(int(keys[0]), unit="s"),
                    )
                    self.assumed_warned = True
            intervals[missing], source[missing] = fallback, how
        return intervals, source

    def _drop_repeats(self, keys: np.ndarray) -> np.ndarray:
        """Remove telegrams logged twice: an equal spectrum stamped 1-2 s after another.

        The Parsivel cannot send telegrams less than 10 s apart, so two equal
        spectra that close are one telegram logged twice -- unless they fill a
        gap: a telegram stamped late can land just before the next one, and
        then the spacing on one side of the pair is about two intervals.
        """
        gaps = np.diff(keys)
        if keys.size < 2 or not np.any(gaps <= _NEAR_DUPLICATE_S):
            return keys
        keep = np.ones(keys.size, dtype=bool)
        last = 0
        for position in range(1, keys.size):
            first, second = int(keys[last]), int(keys[position])
            if second - first <= _NEAR_DUPLICATE_S and np.array_equal(self.spectra[first], self.spectra[second]):
                nearby = gaps[max(0, position - 10):position + 10]
                nearby = nearby[nearby >= _MIN_INTERVAL_S - 1]
                usual = float(np.median(nearby)) if nearby.size else None
                before = first - int(keys[last - 1]) if last > 0 else 0
                after = int(keys[position + 1]) - second if position + 1 < keys.size else 0
                if usual is None or max(before, after) <= 1.5 * usual:
                    keep[position] = False
                    stamp_day = second // SECONDS_PER_DAY
                    self.duplicates[stamp_day] = self.duplicates.get(stamp_day, 0) + 1
                    del self.spectra[second]
                    del self.origin[second]
                    self.frozen.pop(second, None)
                    continue
            last = position
        return keys[keep]

    def _release_day(self, day: int):
        day_start, day_end = day * SECONDS_PER_DAY, (day + 1) * SECONDS_PER_DAY
        low, high = day_start - _HALF_SPAN, day_end + _HALF_SPAN
        keys = np.fromiter((key for key in self.spectra if low <= key < high), dtype=np.int64)
        if keys.size == 0:
            return None
        keys.sort()
        keys = self._drop_repeats(keys)
        intervals, how = self._intervals(keys)
        # A telegram holds the drops of the interval that ENDS at its stamp;
        # bin it by the centre of that interval.
        centre = keys - intervals / 2.0 if self.time_binning == "centre" else keys.astype(np.float64)
        if self.frozen:
            # A telegram left for this day by the previous one keeps the
            # interval that put it here: with more neighbours its interval can
            # come out longer and move its centre back into a finished day.
            for position in np.flatnonzero(centre < day_start).tolist():
                kept = self.frozen.get(int(keys[position]))
                if kept is not None:
                    intervals[position], how[position] = kept
                    centre[position] = keys[position] - kept[0] / 2.0
        take = (centre >= day_start) & (centre < day_end)
        consumed = centre < day_end
        self.late += int(np.count_nonzero(consumed & (centre < day_start)))
        day_keys, day_intervals, day_centre = keys[take], intervals[take], centre[take]
        spectra = [self.spectra[key] for key in day_keys.tolist()]
        origins = [self.origin[key] for key in day_keys.tolist()]
        done = keys[consumed]
        for key in done.tolist():
            del self.spectra[key]
            del self.origin[key]
            self.frozen.pop(key, None)
        for position in np.flatnonzero(~consumed).tolist():
            self.frozen[int(keys[position])] = (float(intervals[position]), how[position])
        self.context = np.r_[self.context, done][-(2 * _CADENCE_HALF_WINDOW + 1):]
        if day_keys.size and np.any(how[take] != "assumed"):
            self.previous_interval = _most_common(day_intervals[how[take] != "assumed"])
        inside = (self.first_day is None or day >= self.first_day) and (
            self.last_day is None or day <= self.last_day
        )
        if day_keys.size == 0 or not inside:
            return None
        return self._products(day, day_centre, day_intervals, how[take], np.stack(spectra), origins)

    def _products(self, day, centre, intervals, how, spectra, origins):
        day_start = day * SECONDS_PER_DAY
        minute = np.floor((centre - day_start) / 60.0).astype(np.int64)
        order = np.argsort(minute, kind="stable")
        minute, intervals, spectra = minute[order], intervals[order], spectra[order]
        bounds = np.r_[np.flatnonzero(np.r_[True, minute[1:] != minute[:-1]]), minute.size]
        counts = np.zeros((MINUTES_PER_DAY, N_SPECTRUM), dtype=np.int32)
        telegrams = np.zeros(MINUTES_PER_DAY, dtype=np.int32)
        seconds = np.zeros(MINUTES_PER_DAY, dtype=np.float64)
        # A slice sum per minute is ~15x faster than np.add.reduceat along axis 0.
        for begin, end in zip(bounds[:-1].tolist(), bounds[1:].tolist()):
            row = minute[begin]
            counts[row] = spectra[begin:end].sum(axis=0, dtype=np.int32)
            telegrams[row] = end - begin
            seconds[row] = intervals[begin:end].sum()
        del spectra
        # Field 93 lists the 32 diameter classes of velocity class 1, then of
        # velocity class 2, ...: reshape to (velocity, diameter) and transpose.
        grid = np.ascontiguousarray(counts.reshape(MINUTES_PER_DAY, N_CLASSES, N_CLASSES).transpose(0, 2, 1))
        index = pd.to_datetime(day_start + 60 * np.arange(MINUTES_PER_DAY, dtype=np.int64), unit="s")
        if not self.full_day:
            observed = np.flatnonzero(telegrams)
            window = slice(int(observed[0]), int(observed[-1]) + 1)
            grid, telegrams, seconds, index = grid[window], telegrams[window], seconds[window], index[window]
        duration = np.where(telegrams > 0, seconds, np.nan)
        parameters, nd, moments = integral_parameters(grid, duration, self.classes, fall_speed=self.fall_speed)
        parms, psd, moment_frame = _frames(index, parameters, nd, moments, self.classes, telegrams, seconds)
        used = sorted(set(origins))
        touching = sorted(set(used).union(
            item for item, days in enumerate(self.source_days) if day in days
        ))
        by_file = {self.labels[item]: self.rejected[item] for item in touching if self.rejected[item]}
        dominant = _most_common(intervals)
        sources, tally = np.unique(how.astype(str), return_counts=True)
        if self.conflicts.get(day):
            LOGGER.warning(
                "%s: %d telegram(s) share a time stamp with a different spectrum; the first read was kept",
                _day_label(day), self.conflicts[day],
            )
        parms.attrs.update(
            telegrams=int(centre.size),
            duplicate_telegrams=int(self.duplicates.get(day, 0)),
            conflicting_telegrams=int(self.conflicts.get(day, 0)),
            rejected_lines=int(sum(by_file.values())),
            rejected_lines_by_file="; ".join(f"{name}={count}" for name, count in by_file.items()),
            telegram_interval_s=(int(dominant) if dominant is not None and float(dominant).is_integer() else dominant),
            telegram_interval_source=str(sources[int(np.argmax(tally))]),
            time_binning=self.time_binning,
            source_files=", ".join(self.labels[item] for item in used),
            parsivel_classes=self.classes.name,
            fall_speed_method=self.fall_speed,
            class_description=self.classes.description,
            velocity_filter=str(self.classes.settings.get("velocity_filter", "table")),
            max_diameter_mm=str(self.classes.settings.get("max_diameter_mm", "table")),
        )
        frames = (parms, psd, moment_frame)
        if self.include_spectrum:
            frames = (*frames, spectrum_dataarray(index, grid, self.classes, telegrams))
        return frames

    def report(self) -> None:
        if self.impossible:
            LOGGER.warning(
                "%d telegram(s) had an impossible time stamp (before 2005, or over 30 days ahead of this "
                "computer's clock): the logger clock was not set, and they were rejected", self.impossible,
            )
        if self.late:
            LOGGER.warning(
                "%d telegram(s) arrived after their day had been produced and were not used", self.late
            )
        if self.layout_fields:
            fields, counts = np.unique(np.asarray(self.layout_fields), return_counts=True)
            seen = ", ".join(f"{count} with {field_count} fields" for field_count, count in zip(fields, counts))
            LOGGER.warning(
                "Rejected telegrams whose field count does not match spectrum_offset=%d + 1024 counts "
                "(%s); set spectrum_offset (or strict_fields=False) if the logger layout differs",
                self.spectrum_offset, seen,
            )


# ---------------------------------------------------------------------------
# Integral parameters
# ---------------------------------------------------------------------------

PARAMETER_COLUMNS = (
    "Total Drops", "Concentration", "LWC", "Z", "dBZ", "Rain", "Dm", "Dmax",
    "Sigma_M", "Nw", "V", "Raw Drops", "Telegrams", "Sample_Seconds",
)


def integral_parameters(counts, sample_seconds, classes: ParsivelClasses, *, fall_speed: str = "measured"):
    """Compute DSD parameters from summed (time, diameter, velocity) counts.

    ``sample_seconds`` is the sampled duration of every row. Rows whose
    duration is missing/zero or whose counts are not finite are returned as
    NaN. Returns ``(parameters, nd, moments)`` as NumPy arrays: ``parameters``
    is a dict keyed by the :data:`PARAMETER_COLUMNS` names, ``nd`` is N(D)
    (time, diameter) in m-3 mm-1 and ``moments`` holds M0..M7 in m-3 mm^n.
    Only rows that contain drops are integrated; observed rows without drops
    get zeros for the extensive quantities and NaN for Dm, sigma_m, Nw, dBZ,
    Dmax and the mean fall speed.
    """
    method = str(fall_speed).strip().lower()
    if method not in FALL_SPEED_METHODS:
        raise ValueError(f"fall_speed must be one of {FALL_SPEED_METHODS}")
    counts = np.asarray(counts)
    if counts.ndim != 3 or counts.shape[1:] != (N_CLASSES, N_CLASSES):
        raise ValueError(f"Expected (time, 32, 32) counts; got {counts.shape}")
    rows = counts.shape[0]
    seconds = np.broadcast_to(np.asarray(sample_seconds, dtype=np.float64), (rows,)).copy()
    finite_rows = (
        np.isfinite(counts).all(axis=(1, 2)) if np.issubdtype(counts.dtype, np.floating)
        else np.ones(rows, dtype=bool)
    )
    valid = np.isfinite(seconds) & (seconds > 0) & finite_rows
    raw_total = np.zeros(rows)
    raw_total[valid] = counts[valid].sum(axis=(1, 2), dtype=np.float64)
    active = np.flatnonzero(valid & (raw_total > 0))

    diameter = classes.diameter
    area = classes.sampling_area_mm2
    if np.any(area <= 0):
        raise ValueError("diameter classes produce a non-positive sampling area")
    if method == "measured":
        speed = np.broadcast_to(classes.velocity[None, :], (N_CLASSES, N_CLASSES))
    else:
        speed = np.broadcast_to(classes.terminal_velocity[:, None], (N_CLASSES, N_CLASSES))
    keep = classes.mask & (speed > 0)
    weight = np.zeros((N_CLASSES, N_CLASSES))
    weight[keep] = 1e6 / (area[:, None] * speed)[keep]  # mm2 -> m2

    zeros = np.where(valid, 0.0, np.nan)
    nd = np.repeat(zeros[:, None], N_CLASSES, axis=1)
    moments = np.repeat(zeros[:, None], 8, axis=1)
    parameters = {name: zeros.copy() for name in (
        "Total Drops", "Concentration", "LWC", "Z", "Rain", "Raw Drops",
    )}
    missing = np.full(rows, np.nan)
    for name in ("dBZ", "Dm", "Dmax", "Sigma_M", "Nw", "V"):
        parameters[name] = missing.copy()
    parameters["Raw Drops"][valid] = raw_total[valid]

    if active.size:
        filtered = counts[active].astype(np.float64) * keep[None, :, :]
        dt = seconds[active]
        per_diameter = filtered.sum(axis=2)  # filtered counts per diameter class
        total = per_diameter.sum(axis=1)
        number = np.einsum("tdv,dv->td", filtered, weight) / dt[:, None]  # N(D) dD [m-3]
        moment = number @ (diameter[:, None] ** np.arange(8)[None, :])  # [m-3 mm^n]
        m3, m4, m6 = moment[:, 3], moment[:, 4], moment[:, 6]
        with np.errstate(divide="ignore", invalid="ignore"):
            dm = np.where(m3 > 0, m4 / m3, np.nan)
            spread = (number * diameter**3 * (diameter[None, :] - dm[:, None]) ** 2).sum(axis=1)
            sigma_m = np.sqrt(np.where(m3 > 0, spread / m3, np.nan))
            nw = np.where(m4 > 0, (256.0 / 6.0) * m3**5 / m4**4, np.nan)
            dbz = np.where(m6 > 0, 10.0 * np.log10(m6), np.nan)
            mean_speed = np.where(total > 0, (filtered.sum(axis=1) @ classes.velocity) / total, np.nan)
        volume_per_area = (np.pi / 6.0) * diameter**3 / area  # mm of water per drop
        last = np.where(per_diameter > 0, np.arange(N_CLASSES)[None, :], -1).max(axis=1)
        nd[active] = number / classes.diameter_width[None, :]  # [m-3 mm-1]
        moments[active] = moment
        updates = {
            "Total Drops": total,
            "Concentration": moment[:, 0],
            "LWC": (np.pi / 6.0) * 1e-3 * m3,  # g m-3 with rho_w = 1 g cm-3
            "Z": m6,
            "dBZ": dbz,
            "Rain": (per_diameter @ volume_per_area) * 3600.0 / dt,
            "Dm": dm,
            "Dmax": np.where(last >= 0, diameter[np.maximum(last, 0)], np.nan),
            "Sigma_M": sigma_m,
            "Nw": nw,
            "V": mean_speed,
        }
        for name, values in updates.items():
            parameters[name][active] = values
    return parameters, nd, moments


def _frames(index, parameters, nd, moments, classes, telegrams=None, seconds=None):
    data = dict(parameters)
    if telegrams is not None:
        data["Telegrams"] = np.asarray(telegrams, dtype=np.int32)
    if seconds is not None:
        data["Sample_Seconds"] = np.asarray(seconds, dtype=np.float64)
    parms = pd.DataFrame(data, index=index)
    psd = pd.DataFrame(nd, index=index, columns=classes.diameter)
    psd.attrs["diameter_width"] = [float(value) for value in classes.diameter_width]
    moment_frame = pd.DataFrame(moments, index=index, columns=[f"M{i}" for i in range(8)])
    return parms, psd, moment_frame


def get_integral_parameters(instrument, ds_1min, df_mask, dv_parms, *, fall_speed="measured", sample_seconds=None):
    """0.50.0-compatible wrapper: parameters, PSD and moments from a 1-min Dataset.

    ``ds_1min["drops"]`` holds (time, Diam, Vel) counts. NaN rows are treated
    as missing. ``sample_seconds`` defaults to ``ds_1min["sample_duration"]``
    when present, otherwise 60 s per row.
    """
    del instrument  # retained for signature compatibility
    classes = classes_from_tables(dv_parms, df_mask)
    drops = ds_1min["drops"].transpose("time", "Diam", "Vel").to_numpy()
    if sample_seconds is None:
        sample_seconds = (
            ds_1min["sample_duration"].to_numpy() if "sample_duration" in ds_1min else 60.0
        )
    parameters, nd, moments = integral_parameters(drops, sample_seconds, classes, fall_speed=fall_speed)
    return _frames(pd.DatetimeIndex(ds_1min.time.to_numpy()), parameters, nd, moments, classes)


def spectrum_dataarray(index, grid, classes: ParsivelClasses, telegrams=None):
    """Return summed raw counts as an ``xarray.DataArray`` (time, diameter, velocity).

    Minutes without telegrams are NaN (missing), not zero.
    """
    import xarray as xr

    values = np.asarray(grid, dtype=np.float32)
    if telegrams is not None:
        values[np.asarray(telegrams) == 0] = np.nan
    return xr.DataArray(
        values,
        dims=("time", "drop_diameter", "fall_velocity"),
        coords={
            "time": index,
            "drop_diameter": classes.diameter,
            "fall_velocity": classes.velocity,
        },
        attrs={
            "units": "1",
            "long_name": "Raw Parsivel counts summed per minute, before the velocity-diameter filter",
        },
    )


def iter_days(
    input_path,
    instrument: str | None = None,
    *,
    start_date=None,
    end_date=None,
    classes: str = "ott",
    fall_speed: str = "measured",
    velocity_filter: float | None = 0.5,
    max_diameter_mm: float | None = 10.0,
    telegram_interval_s: float | None = None,
    full_day: bool = True,
    include_spectrum: bool = False,
    spectrum_offset: int = SPECTRUM_OFFSET,
    strict_fields: bool = True,
    time_binning: str = "centre",
    table_dir=None,
    temp_root=None,
):
    """Yield ``(YYYY-MM-DD, frames)`` in date order.

    ``frames`` is ``(parameters, psd, moments)`` -- plus a raw-count
    ``xarray.DataArray`` when ``include_spectrum=True``. Every source is
    first scanned for its earliest and latest telegram stamp; sources are
    then decoded in that order and a day is produced once no unread source
    can hold a telegram for it, so files may be named anything and only the
    days spanned by the files being read are held in memory (about one day
    for a long file whose stamps never go backwards). With ``start_date`` or
    ``end_date``, lines stamped outside the window are skipped before their
    spectrum is decoded.

    ``time_binning="centre"`` (default) puts each telegram in the minute that
    holds the centre of its measuring interval (stamp - interval / 2);
    ``"stamp"`` uses the stamp itself, as 0.50.0 did. ``strict_fields``
    rejects telegrams whose field count is not ``spectrum_offset + 1024``
    (plus an optional trailing comma).
    """
    del instrument
    if temp_root is not None:
        warnings.warn(
            "temp_root is ignored: Parsivel inputs are read in memory and no scratch files are written",
            DeprecationWarning, stacklevel=2,
        )
    method = str(fall_speed).strip().lower()
    if method not in FALL_SPEED_METHODS:
        raise ValueError(f"fall_speed must be one of {FALL_SPEED_METHODS}")
    binning = str(time_binning).strip().lower()
    if binning not in ("centre", "center", "stamp"):
        raise ValueError("time_binning must be 'centre' or 'stamp'")
    binning = "centre" if binning == "center" else binning
    if telegram_interval_s is not None and not 0 < float(telegram_interval_s) <= _MAX_INTERVAL_S:
        raise ValueError(f"telegram_interval_s must be between 0 and {_MAX_INTERVAL_S} s")
    selected = get_parsivel_classes(
        classes, velocity_filter=velocity_filter, max_diameter_mm=max_diameter_mm, table_dir=table_dir
    )
    first_day, last_day = _day_number(start_date), _day_number(end_date)
    latest = _latest_stamp()
    assembler = _Assembler(
        selected, fall_speed=method, telegram_interval_s=telegram_interval_s, full_day=full_day,
        include_spectrum=include_spectrum, spectrum_offset=spectrum_offset, strict_fields=strict_fields,
        time_binning=binning, first_day=first_day, last_day=last_day, latest=latest,
    )
    sources: list[_Source] = []
    for path, in_directory in _iter_paths(input_path):
        if in_directory and _name_outside_window(path, first_day, last_day):
            continue
        for source in _sources(path):
            span = _scan(source, latest)
            if span is None:
                continue
            source.first, source.last = span
            if assembler.keep_from is not None and source.last < assembler.keep_from:
                continue
            if assembler.keep_until is not None and source.first >= assembler.keep_until:
                continue
            sources.append(source)
    sources.sort(key=lambda item: (item.first, item.priority, item.label))
    for index, source in enumerate(sources):
        # Unread sources hold no telegram stamped before their earliest stamp,
        # so every day ending _HALF_SPAN before it is complete.
        cap = sources[index + 1].first - _HALF_SPAN if index + 1 < len(sources) else None
        yield from assembler.read(source, cap)
        if cap is not None:
            yield from assembler.release(cap)
    yield from assembler.release(None)
    assembler.report()


def run(input_path, instrument=None, *, start_date=None, end_date=None, table_dir=None, temp_root=None, **options):
    """Decode Parsivel inputs and return ``{YYYY-MM-DD: (parameters, psd, moments)}``.

    ``input_path`` may be a file, a directory searched recursively or a
    sequence of files/directories. Keyword options are those of
    :func:`iter_days`.
    """
    return dict(iter_days(
        input_path, instrument, start_date=start_date, end_date=end_date,
        table_dir=table_dir, temp_root=temp_root, **options,
    ))


def process_input(input_path, instrument, year, month, day, *, table_dir=None, temp_root=None, **options):
    """Return ``(parameters, psd, moments)`` for one UTC date (empty frames if absent)."""
    date_text = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    results = run(
        input_path, instrument, start_date=date_text, end_date=date_text,
        table_dir=table_dir, temp_root=temp_root, **options,
    )
    if date_text not in results:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    return results[date_text][:3]


def discover_input_dates(input_path):
    """Return the UTC dates that hold telegram stamps in Parsivel inputs.

    Every file is scanned (a fast byte-level look at the stamps, no decoding)
    and the distinct UTC days of its usable stamps are listed; a gap between
    two days in one file adds no dates. Products are built by the centre of
    each telegram's interval, so a telegram stamped just after midnight can
    also put a minute into the day before, and a listed day whose telegrams
    are all rejected yields no product.
    """
    latest = _latest_stamp()
    days: set[int] = set()
    for path, _ in _iter_paths(input_path):
        for source in _sources(path):
            if _scan(source, latest) is not None:
                days.update(source.days)
    return [pd.Timestamp(day * SECONDS_PER_DAY, unit="s") for day in sorted(days)]


# ---------------------------------------------------------------------------
# 0.50.0 compatibility helpers
# ---------------------------------------------------------------------------


def get_dataset_from_parsivel(path, year, month, day, dv_parms, order="F"):
    """Read one file's telegrams for a date into ``(Dataset, counts)`` (0.50.0 API).

    ``order="F"`` (OTT field 93 order, diameter varying fastest) gives the
    (time, Diam, Vel) layout. Telegrams are selected by their own time stamp
    and duplicates are counted once.
    """
    import xarray as xr

    target = _day_number(f"{int(year):04d}-{int(month):02d}-{int(day):02d}")
    stamps: dict[int, np.ndarray] = {}
    for source in _sources(Path(path)):
        try:
            for line in source.lines():
                for epoch, counts in parse_telegram_line(line)[0]:
                    if epoch // SECONDS_PER_DAY == target:
                        stamps.setdefault(epoch, counts)
        except _READ_ERRORS as exc:
            LOGGER.warning("Stopped reading %s: %s", source.label, exc)
    if not stamps:
        LOGGER.warning("No valid rows for %s%s%s in %s", year, month, day, Path(path).name)
        return None, None
    keys = sorted(stamps)
    times = pd.to_datetime(np.asarray(keys, dtype=np.int64), unit="s")
    flat = np.stack([stamps[key] for key in keys]).astype(np.float64)
    data = np.stack([row.reshape((N_CLASSES, N_CLASSES), order=order) for row in flat])
    dataset = xr.Dataset(
        {"drops": (["time", "Diam", "Vel"], data)},
        coords={
            "time": times,
            "Diam": dv_parms["Drop_bin"].to_numpy(),
            "Vel": dv_parms["Measured_Vt"].to_numpy(),
        },
        attrs={"description": "Parsivel data"},
    )
    return dataset, data


def _scratch_root(instrument, year, month, day, temp_root):
    if temp_root is None:
        return Path(tempfile.mkdtemp(prefix=f"gv_tools_parsivel_{instrument}_{year}{month}{day}_"))
    root = Path(temp_root) / "tmp" / str(instrument) / f"{year}{month}{day}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def unzip_files_parallel(zip_files, instrument, year, month, day, temp_root=None):
    """Deprecated: extract archive members to a private scratch directory.

    Members are written as ``<archive stem>__<member path>`` so equal member
    names in different archives no longer overwrite each other. Without
    ``temp_root`` a new private temporary directory is used, never the
    current working directory.
    """
    warnings.warn(
        "unzip_files_parallel is deprecated; run()/iter_days() read archives in memory",
        DeprecationWarning, stacklevel=2,
    )
    if not zip_files:
        return [], None
    root = _scratch_root(instrument, year, month, day, temp_root)
    extracted = []
    for zip_path in map(Path, zip_files):
        for source in _sources(zip_path):
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", source.member or source.label)
            destination = root / f"{zip_path.stem}__{safe}"
            with source.binary() as raw, destination.open("wb") as out:
                shutil.copyfileobj(raw, out)
            extracted.append(str(destination))
    return extracted, root


def concatenate_files(paths, instrument, year, month, day, temp_root=None):
    """Deprecated: join text files, adding a newline wherever a file lacks one."""
    warnings.warn(
        "concatenate_files is deprecated; run()/iter_days() read each file separately",
        DeprecationWarning, stacklevel=2,
    )
    if not paths:
        raise ValueError("Cannot concatenate an empty file list")
    root = _scratch_root(instrument, year, month, day, temp_root)
    destination = root / "combined_input.csv"
    with destination.open("wb") as output:
        for path in paths:
            data = Path(path).read_bytes()
            output.write(data)
            if data and not data.endswith((b"\n", b"\r")):
                output.write(b"\n")
    return destination, root


__all__ = [
    "ParsivelClasses",
    "PARAMETER_COLUMNS",
    "classes_from_tables",
    "discover_input_dates",
    "filename_stamp",
    "get_integral_parameters",
    "get_parsivel_classes",
    "integral_parameters",
    "iter_days",
    "load_tables",
    "parse_telegram_line",
    "process_input",
    "run",
    "telegram_intervals",
    "terminal_velocity",
    "velocity_filter_mask",
]
