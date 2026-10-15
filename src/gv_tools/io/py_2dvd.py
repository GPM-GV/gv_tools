"""Read individual 2DVD drop records into a pandas DataFrame.

This module performs I/O only: it never filters drops, integrates a spectrum,
plots data, or silently writes extracted archive members.

Format authority is the user-supplied ``load_drop_file.pro`` (record indices)
and ``dropbydrop.f`` (split numeric clock). These are file-format references,
not journal specifications. Kruger & Krajewski (2002), DOI
10.1175/1520-0426(2002)019<0602:TDVDAD>2.0.CO;2, describes the instrument.

"""

import re
import stat
import tarfile
import zipfile
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd

# Order is the normalized numeric layout: three clock fields, five physical
# measurements, then eight camera measurements. Units live in the names so an
# area in mm² cannot easily be confused with the m² used by the physics code.
DROP_COLUMNS = (
    "hour",
    "minute",
    "second",
    "reported_diameter_mm",
    "drop_volume_mm3",
    "measured_velocity_m_s",
    "axis_ratio",
    "sampling_area_mm2",
    "camera_a_height_mm",
    "camera_b_height_mm",
    "camera_a_width_mm",
    "camera_b_width_mm",
    "camera_a_min_index",
    "camera_a_max_index",
    "camera_b_min_index",
    "camera_b_max_index",
)
DROP_FILENAME = re.compile(r"V(\d{2})(\d{3})\.drops\.txt")
CLOCK_TOKEN = re.compile(r"(\d{1,2}):(\d{2}):(\d{2}(?:\.\d+)?)")


def date_from_filename(filename, *, date=None):
    """Decode VYYDDD.drops.txt; optional date disambiguates the century.

    YY=23 and DDD=022 mean 2023-01-22. Without an explicit date, YY is interpreted
    in 2000–2099. Invalid day-of-year values, including 366 in a non-leap year,
    raise ValueError. An explicit date must agree with both YY and DDD.
    """
    match = DROP_FILENAME.fullmatch(Path(filename).name)
    if match is None:
        raise ValueError("Expected a drop filename of the form VYYDDD.drops.txt")
    short_year, day_of_year = map(int, match.groups())
    requested_date = pd.Timestamp(date) if date is not None else None
    year = requested_date.year if requested_date is not None else 2000 + short_year
    day = pd.Timestamp(year=year, month=1, day=1) + pd.Timedelta(days=day_of_year - 1)
    if day_of_year < 1 or day.year != year or year % 100 != short_year:
        raise ValueError("Invalid year or day-of-year in input filename")
    if requested_date is not None and requested_date != day:
        raise ValueError(
            "Explicit date must match the filename at midnight, without a timezone"
        )
    return day


def _single_member(member_names):
    """Ignore unrelated files and macOS resource forks; require one drop file."""
    candidates = [
        name
        for name in member_names
        if "__MACOSX" not in Path(name).parts
        and DROP_FILENAME.fullmatch(Path(name).name)
    ]
    if len(candidates) != 1:
        raise ValueError(
            f"Archive must contain exactly one drop file; found {len(candidates)}"
        )
    return candidates[0]


@contextmanager
def _open_input(input_path):
    """Yield a binary stream and its logical filename, closing both afterward.

    Archive member names are labels, never filesystem destinations. ZIP symbolic
    links and tar links/directories are excluded. No extract/extractall operation
    is used. Only a single matching day is accepted, avoiding an ambiguous merge.
    """
    suffix = input_path.name.lower()
    if suffix.endswith(".zip"):
        with zipfile.ZipFile(input_path) as archive:
            regular_files = [
                member
                for member in archive.infolist()
                if not member.is_dir() and not stat.S_ISLNK(member.external_attr >> 16)
            ]
            filename = _single_member([member.filename for member in regular_files])
            member = next(item for item in regular_files if item.filename == filename)
            with archive.open(member) as stream:
                yield stream, filename
    elif suffix.endswith((".tgz", ".tar.gz")):
        with tarfile.open(input_path, mode="r:gz") as archive:
            regular_files = [
                member for member in archive.getmembers() if member.isfile()
            ]
            filename = _single_member([member.name for member in regular_files])
            member = next(item for item in regular_files if item.name == filename)
            with archive.extractfile(member) as stream:
                yield stream, filename
    else:
        with input_path.open("rb") as stream:
            yield stream, input_path.name


def _parse_record(tokens, line_number):
    """Normalize one record without shifting the camera fields.

    Split-time records have 16 numeric tokens. Clock-string records have a
    HH:MM:SS.sss token, five physical values, optionally 0–2 uninterpreted source
    metadata tokens, and eight camera values. In the supplied IDL reader the
    two metadata tokens are a[6] and a[7]; camera A height is a[8]. Those metadata
    tokens are retained as strings rather than guessed or converted to numbers.
    """
    metadata = []
    if ":" in tokens[0]:
        clock = CLOCK_TOKEN.fullmatch(tokens[0])
        if clock is None or len(tokens) not in (14, 15, 16):
            raise ValueError(f"Line {line_number}: invalid clock-string record")
        metadata_count = len(tokens) - 14
        metadata = tokens[6 : 6 + metadata_count]
        numeric_tokens = (
            list(clock.groups()) + tokens[1:6] + tokens[6 + metadata_count :]
        )
        layout = f"clock_string_{metadata_count}_extra"
    else:
        if len(tokens) != 16:
            raise ValueError(f"Line {line_number}: expected 16 split-time columns")
        numeric_tokens = tokens
        layout = "split_time"
    try:
        values = [float(token) for token in numeric_tokens]
    except ValueError as error:
        raise ValueError(
            f"Line {line_number}: nonnumeric physical measurement"
        ) from error
    if not np.isfinite(values).all():
        raise ValueError(f"Line {line_number}: nonfinite physical measurement")
    hour, minute, second = values[:3]
    if not (
        0 <= hour < 24
        and hour.is_integer()
        and 0 <= minute < 60
        and minute.is_integer()
        and 0 <= second < 60
    ):
        raise ValueError(f"Line {line_number}: invalid clock values")
    if values[4] < 0:
        raise ValueError(f"Line {line_number}: negative drop volume")
    return values, metadata, layout


def _file_hash(path):
    """Compute a SHA-256 in bounded chunks rather than loading a whole archive."""
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ingest_raw(datafile, *, site="WFF", instrument="sn37", date=None):
    """Read one plain/ZIP/TGZ day into a DataFrame without scientific filtering.

    The first two physical lines are headers, following both supplied readers.
    Blank data lines are ignored; malformed nonblank lines fail with their
    original line number. Records remain in input order: sorting here would
    conceal backward clock jumps from quality control. Subsecond times are
    retained. The source contains no timezone, so timestamps remain naive.

    Each returned row is one detected object, not a concentration or a spectrum.
    Source filenames, the date/site/instrument, layouts, row count, and hashes
    are stored in DataFrame.attrs. The content hash includes headers and blank
    lines and is computed on uncompressed bytes during the same read pass.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]+", site):
        raise ValueError("site must contain only letters, digits, underscore or hyphen")
    input_path = Path(datafile).expanduser().resolve()
    records, metadata_records, layouts = [], [], set()
    content_digest = sha256()
    header_count = 0
    with _open_input(input_path) as (stream, logical_filename):
        observation_date = date_from_filename(logical_filename, date=date)
        for line_number, binary_line in enumerate(stream, start=1):
            content_digest.update(binary_line)
            if line_number <= 2:
                header_count += 1
                continue
            tokens = binary_line.decode("utf-8-sig").split()
            if not tokens:
                continue
            values, metadata, layout = _parse_record(tokens, line_number)
            records.append(values)
            metadata_records.append(metadata)
            layouts.add(layout)
    if header_count != 2:
        raise ValueError("Input must contain the two required header lines")
    raw_drops = pd.DataFrame(records, columns=DROP_COLUMNS, dtype=float)
    for index in range(max(map(len, metadata_records), default=0)):
        raw_drops[f"source_extra_{index + 1}"] = [
            fields[index] if index < len(fields) else None
            for fields in metadata_records
        ]
    seconds_since_midnight = (
        raw_drops.hour * 3600 + raw_drops.minute * 60 + raw_drops.second
    )
    raw_drops["time"] = observation_date + pd.to_timedelta(
        seconds_since_midnight, unit="s"
    )
    raw_drops.attrs = {
        "site": site,
        "instrument_id": instrument,
        "date": str(observation_date.date()),
        "source_file": str(input_path),
        "source_member": logical_filename,
        "source_sha256": _file_hash(input_path),
        "source_data_sha256": content_digest.hexdigest(),
        "source_layouts": ",".join(sorted(layouts)) or "empty",
        "input_rows": len(raw_drops),
        "timezone": "Unspecified in source; timestamps are naive",
    }
    return raw_drops


