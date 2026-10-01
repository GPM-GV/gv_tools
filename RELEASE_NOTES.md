# 0.31.0

- Adds content-based detection for WSR-88D NEXRAD Level-II archives beginning
  with either ``AR2V`` or legacy ``ARCHIVE2.`` signatures.
- Routes NEXRAD Level-II data transparently through
  ``pyart.io.read_nexrad_archive()``. ``XRADAR=True`` warns and safely falls
  back to Py-ART for NEXRAD volumes whose unequal gate counts cannot be
  converted reliably by the current xradar-to-Py-ART bridge.
- Adds dispatch regression tests and verifies decoding against a KCRP V06
  archive containing 14 sweeps, 7,920 rays, and seven radar fields.
- Updates the quickstart example with optional content-aware radar ingest.

# 0.30.0

Built on 0.29.6, preserving its existing readers, corrections, plotting, and
output interfaces. Integrates py_2dvd_lite 0.1.2 as gv_tools.py_2dvd:

- Raw text/ZIP/TGZ ingestion and CSV/NetCDF export in gv_tools.io.
- Drop quality control, integral parameters, and DSD in gv_tools.core.
- Optional eight-panel integral and logarithmic DSD plots in gv_tools.graph.
- Bundled lookup tables and retained source scientific conventions/provenance.
- Processing and plotting CLI commands, master notebook example, and HTML manual.

The mistakenly built 0.21.0 artifact from the stale Documents copy is superseded
by this release and must not be used to replace 0.29.6.

# GV Tools 0.29.6

- Warns and ignores the Py-ART-only ``file_field_names`` option when radar
  ingest is requested with ``XRADAR=True``.
- Adds regression coverage and updates the master notebook, source and HTML
  documentation, and release artifacts.

# GV Tools 0.29.5

- Stores the radar ``XRADAR`` provenance flag as the NetCDF-safe integer
  ``0`` or ``1`` instead of a Boolean.
- Fixes direct CF/Radial output with ``pyart.io.write_cfradial`` after
  ``gv_tools.io.read_radar`` and adds a round-trip regression test.
- Updates the master notebook, source documentation, HTML documentation, and
  release artifacts.

# GV Tools 0.29.4

- Uses Matplotlib ``loc="best"`` for all legends attached to line-data axes,
  reducing overlap with observed curves.
- Retains intentionally external legends, such as wind-rose speed-bin keys,
  outside the data region.
- Updates tests, notebooks, complete HTML documentation, and release artifacts.

# GV Tools 0.29.3

- Standardizes every public plot and quicklook title to include site,
  observation date, and instrument name or identifier.
- Preserves custom title text while appending the required metadata context,
  with explicit fallbacks when source metadata is incomplete.
- Updates tests, notebooks, complete HTML documentation, and release artifacts.

# GV Tools 0.29.2

- Replaces the WS800-full dashboard with a six-row, single-column quicklook
  for air temperature, dew point, relative humidity, absolute humidity,
  mixing ratio, and lightning field families.
- Supports both pandas and xarray input, plots every matching family field,
  and adds per-field colors, line width, figure size, and DPI controls.
- Updates the master notebook, HTML documentation, tests, and release artifacts.

# GV Tools 0.29.1

- Fixes hourly APU Parsivel archive ingest by deriving the internal processing
  interval from the first and last filenames in the ordered user input list.
- Processes the exact Parsivel file list as one staged batch, avoiding repeated
  decoding and keeping date controls out of the public API.
- Updates the master notebook, HTML documentation, tests, and release artifacts.

# GV Tools 0.29.0

- Removes all start/end date parameters from public readers, adapter methods,
  the Parsivel backend call, and the command-line interface.
- Makes the caller solely responsible for date selection: every supplied file
  is processed and list-based readers require fully qualified filenames.
- Updates all current examples, notebooks, source documentation, HTML pages,
  tests, and installation artifacts for the file-only ingest contract.

# GV Tools 0.28.0

- Adds ``plot_mrr_time_height_quicklook`` for explicit MRR2 or MRRPro field
  lists in a shared-time, single-column time-height figure.
- Adds global or per-field colormaps, color bounds and labels, height/time
  ranges, colorbar placement, grid, title, figure size, DPI, and save behavior.
- Updates the master notebook and complete HTML documentation with immediate
  post-ingest MRR2 and MRRPro plotting examples.

# GV Tools 0.27.1

- Adds ``plot_radar_bb_zdr_calibration`` for birdbath ZDR sample-density,
  vertical-profile, distribution, bias, and additive-correction diagnostics,
  with configurable filtering and an attached numeric result.
- Clarifies that one-dimensional time-series plotting accepts pandas
  DataFrames or xarray Datasets.
- Removes the duplicate MRR API navigation entry; ``read_mrr`` remains under
  ``gv_tools.io`` while the dedicated MRR scientific user guide remains.

# GV Tools 0.27.0

- Adds ``plot_radar_rhi_quicklook`` using Py-ART for native and XRADAR-loaded
  RHI volumes, with configurable field, sweep, colors, range/height bounds,
  axis direction, colorbar, grid, title, figure size, DPI, and output.
- Adds RHI graph symbols using ``Location``, ``Color``, ``Symbol``, and ``Size``
  dictionaries, accepting one symbol or a sequence of symbols.
- Draws PPI coastlines and administrative borders once at the requested map
  resolution, avoiding a low-resolution basemap under higher-resolution maps.

# GV Tools 0.26.1

- Fixes ``plot_radar_ppi_quicklook`` for PPI volumes loaded with
  ``XRADAR=True``, including later sweeps when XRADAR supplies ray-indexed
  elevation data and a single fixed-angle value.
- Adds an end-to-end XRADAR ingest and mapped-PPI plotting regression test.

# GV Tools 0.26.0

- Adds ``plot_radar_ppi_quicklook`` using Py-ART and Cartopy mapped PPI tools
  with selectable field and sweep, native color defaults, geographic grids,
  map features, borders, radar marker, and verbose UTC/elevation titles.
- Adds configurable range rings in kilometers and radial spokes in degrees,
  including independent colors and line widths, map range/resolution,
  projection, color limits, figure size, DPI, and show-or-save behavior.

# GV Tools 0.25.1

- Adds ``plot_ws800_full_quicklook`` as a 4×2 dashboard spanning thermal,
  moisture, pressure, radiation, wind, precipitation, wind rose, and a dynamic
  field inventory.
- Allows AIO and WS800 full quicklooks and wind roses to accept pandas
  DataFrames as well as xarray Datasets; Parsivel remains xarray-only.

# GV Tools 0.25.0

- Redesigns ``plot_aio_quicklook`` as a 3×2 dashboard with temperature,
  pressure, humidity, dual-axis wind speed/direction, a wind rose, and a boxed
  data summary.
- Adds the established ``savefig`` show-or-save behavior to the AIO quicklook.

# GV Tools 0.24.3

- Displays the Parsivel quicklook normally when ``savefig`` is omitted.
- When ``savefig`` is supplied, saves and closes the figure without displaying
  it and prints ``Plot saved to PATH``.

# GV Tools 0.24.2

- Creates Parsivel quicklooks as unmanaged Matplotlib figures, preventing
  Jupyter backends from automatically rendering a second identical copy.
- Adds the keyword-only ``savefig=`` API for a complete output path and image
  filename while retaining the legacy positional output argument.

# GV Tools 0.24.1

- Closes the Matplotlib-managed Parsivel figure before explicitly displaying
  it, preventing a second automatic rendering across Jupyter backends.

# GV Tools 0.24.0

- Removes the DSD moments row from the Parsivel quicklook, leaving six aligned
  daily panels.
- Explicitly displays and then closes the notebook figure so the inline backend
  produces exactly one copy.

# GV Tools 0.23.0

- Adds configurable Parsivel DSD colormaps, color bounds, colorbar placement,
  and diameter range.
- Renders zero-valued DSD bins white, enlarges quicklook fonts, and keeps all
  seven time axes aligned to the same width.
- Prevents duplicate inline rendering of the Parsivel figure in the example
  notebook.

# GV Tools 0.22.0

- Renames ``plot_aio_overview()`` to ``plot_aio_quicklook()`` and
  ``plot_parsivel_overview()`` to ``plot_parsivel_quicklook()``.
- Calls the Parsivel quicklook immediately after the demonstration dataset is
  loaded, keeping plotting as a direct post-ingest workflow.

# GV Tools 0.21.0

- Adds ``gv_tools.graph.plot_parsivel_overview()`` for a seven-row daily DSD,
  parameter, drop-count, and 1st/3rd/6th-moment quicklook with hourly UTC ticks.
- Updates the master notebook, API reference, user guide, and release artifacts
  for the new plotting workflow.

# GV Tools 0.20.0

- Audits the complete ingest API and retains the readers required for Pandas,
  Xarray, MRR2, and radar results.
- Synchronizes package, notebook, provenance, installation, and documentation
  version references.
- Rebuilds and ships the complete HTML reference documentation for 0.20.0.
- Documents Micro Rain Radar as a dedicated ingest regime, including separate
  MRR2/MRRPro detection, xarray returns, ZIP handling, and time decoding.

- Extends ``gv_tools.io.read_mrr(file)`` to automatically detect and ingest
  MRRPro CF/Radial NetCDF4/HDF5 files, including single-file ZIP archives.
- Records the detected ``MRR2`` or ``MRRPro`` model in ``dataset.attrs``.

# GV Tools 0.18.0

- Normalizes scalar xradar instrument and calibration metadata so native ``radar.info()`` works at every reporting level.
- Adds ``gv_tools.io.read_mrr(file)`` for MRR2 processed NetCDF files and
  single-file ZIP archives, returning an xarray Dataset with decoded UTC time.
- Detects the MRR2 data schema and reports MRRPro as unsupported rather than
  silently interpreting its different format.

# GV Tools 0.17.0

- Makes pandas DataFrame the default ``read_aio`` result for RM Young, Met One, and WS800.
- Adds the common ``XARRAY=True`` choice for xarray Dataset output across all AIO families.

# GV Tools 0.16.1

- Makes ``read_ws800_full(files)`` accept and merge the standard explicit file list.

# GV Tools 0.16.0

- Makes WS800 ``read_aio`` results compact pandas DataFrames using common AIO names.
- Adds ``read_ws800_full(file, XARRAY=False)`` for every WS800 field in pandas or xarray.

# GV Tools 0.15.0

- Adds automatic Lufft WS800 routing through ``gv_tools.io.read_aio()`` and ``read_aio_raw()``.
- Merges multiple WS800 files and retains all source measurements with normalized metadata.

# GV Tools 0.14.3

- Preserves Py-ART's native ``radar.info()`` method on xradar-loaded, converted radar objects.

# GV Tools 0.14.2

- Records the selected radar backend as the Boolean ``radar.metadata['XRADAR']``.

# GV Tools 0.14.1

- Converts the xradar DataTree with ``tree.pyart.to_radar()`` before returning.
- Makes ``read_radar`` return a Py-ART Radar for both backend choices.

# GV Tools 0.14.0

- Adds the opt-in ``read_radar(radar_file, XRADAR=True)`` backend.
- Returns an xradar ``xarray.DataTree`` while retaining Py-ART as the default.
- Preserves compressed-input handling and PPI/RHI/BB reporting for both backends.

# GV Tools 0.13.2

- Detects and prints PPI, RHI, or birdbath (BB) scan type during radar ingest.
- Stores the classification in ``radar.metadata['gv_tools_scan_type']``.

# GV Tools 0.13.1

- Constrains NumPy to ``>=2.4,<2.5`` so GV Tools shares the compatible range required by the Parsivel and radar processing packages.

# GV Tools 0.13.0

- Simplifies radar ingest to ``gv_tools.io.read_radar(radar_file)`` for one volume per call.
- Detects the radar format from decompressed content and dispatches through ARM Py-ART.
- Supports uncompressed, gzip, bzip2, and single-file ZIP radar inputs.

# GV Tools 0.12.1

- Trusts an explicitly supplied AIO file list instead of rejecting files from dates inferred from their names.
- Applies `START_DATE` and `END_DATE` to observation timestamps read from AIO data, fixing false "no overlap" errors when a filename date differs from its contents.

# GV Tools 0.12.0

- Unifies RM Young and Met One ingestion behind ``read_aio`` and
  ``read_aio_raw`` with automatic filename-based routing.
- Gives AIO the same explicit file-list and uppercase ``START_DATE`` /
  ``END_DATE`` interface as Parsivel.
- Keeps ``read_metone`` and ``read_metone_raw`` as compatibility wrappers.

# GV Tools 0.11.3

- Filters the explicit Parsivel file list by archive date before decoding.
- Processes each selected archive only for its own filename date, preventing
  repeated false ``No valid rows`` warnings across multi-file date ranges.

# GV Tools 0.11.2

- Adds optional uppercase ``START_DATE`` and ``END_DATE`` keywords to
  ``read_parsivel`` and ``read_parsivel_raw``.
- Accepts strict ``YYYY-MM-DD`` strings and valid date/datetime-like values,
  normalizes datetime values to calendar dates, and validates range order.

# GV Tools 0.11.1

- Simplifies Parsivel ingest to ``gv_tools.io.read_parsivel(FILES)`` using
  explicit file paths and one merged dataset return value.
- Distinguishes standalone APU archives from PIERS platform Parsivel archives
  by filename, without user-created adapters or metadata.
- Requires PIERS Parsivel archives to match
  ``PIERS####_Parsivel_*.zip`` so other PIERS instruments cannot be ingested
  accidentally as disdrometers.

# GV Tools 0.11.0

- Requires a non-empty filename list for every public instrument reader.
- Resolves relative filenames with the shared ``input_dir=`` keyword.
- Merges multiple files chronologically into one raw product or normalized
  dataset and removes duplicate timestamps.
- Joins multiple radar volumes into one Py-ART ``Radar`` object.
- Updates notebooks, examples, and the reference manual for the common ingest
  contract.

# GV Tools 0.10.0

- Adds direct, metadata-inferring readers under `gv_tools.io` for RM Young
  AIO, Met One AIO, Parsivel, and radar data.
- Provides consistent `read_*`, `read_*_raw`, and `discover_*` naming across
  instrument families.
- Keeps adapter construction as an advanced extension API rather than a
  routine user requirement.
- Updates all notebooks and examples to use the streamlined interface.

# GV Tools 0.9.3

- Rewrites the master notebook against the supported task-oriented v0.9 API.
- Removes imports and cells that depended on unavailable legacy v0.8 gauge
  workflow objects.
- Makes external Met One, Parsivel, and radar demonstrations optional and
  environment-configurable.

# GV Tools 0.9.2

- Makes every notebook independent of the Jupyter launch directory.
- Adds `GV_TOOLS_HOME` and notebook-specific environment-variable overrides.
- Defaults project, sample, and output paths to `~/Desktop/Work/GV Tools`.

# GV Tools 0.9.1

- Places every release notebook in the project-level `notebooks` folder.
- Places current Python scripts in the project-level `examples` folder.
- Synchronizes and updates the canonical ingestion demonstration notebook.

# GV Tools 0.9.0

This release follows GV Tools 0.8.1. The task-oriented interface work was
developed under an incorrect provisional 0.4.0 version and is released as
0.9.0 to preserve the established project history.

- Reorganizes the preferred public API by task into `gv_tools.core`,
  `gv_tools.io`, `gv_tools.config`, `gv_tools.correct`, and `gv_tools.graph`.
- Preserves the 0.3 top-level imports as compatibility aliases during the 0.x
  migration period.
- Adds a Py-ART-inspired HTML reference manual built with Sphinx and the
  PyData Sphinx theme, including searchable API pages and source links.
- Installs all release notebooks below `gv_tools/notebooks`.
- Installs runnable Python scripts below `gv_tools/examples`.
- Adds a task-oriented quickstart and public-interface tests.

# GV Tools 0.3.0

- Adds a native PIERS RM Young All-in-One reader with UTC conversion,
  malformed-row accounting, timestamp deduplication, and normalized weather
  variables.
- Ingests both APU and PIERS Parsivel archive families with explicit platform
  validation and provenance.
- Separates raw decoding (`read_raw`) from normalized product construction.
- Filters discovery by instrument identifier.
- Strengthens product and variable metadata validation.
- Writes data files atomically and emits a typed manifest with SHA-256 hashes
  and time coverage.
- Adds `gv-tools check` for non-installing dependency diagnostics.
- Provides a pure-Python wheel and source ZIP suitable for macOS and Rocky
  Linux with Python 3.10 or newer.

Third-party libraries are declared as dependencies and are not bundled in the
release artifacts.
