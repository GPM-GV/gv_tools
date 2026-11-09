# GV Tools 0.65.0

Version 0.65.0 corrects the scientific processing of Parsivel spectra, rebuilds
how Parsivel days are assembled, and fixes the input-handling issues found in
0.50.0. Several products change value; `CHANGES_0.65.0.html` lists every change.
The release incorporates the reviewed 0.60.0 change set and promotes it as
0.65.0 after local integration with the retained 0.50.0 APIs, examples, radar
support, metadata helpers, and package documentation.

## Science corrections

- Parsivel N(D), concentration, LWC, Z, dBZ, Dm, sigma_m and moments: each
  count is divided by its own velocity class (or by Vt of its own diameter
  with `fall_speed="theoretical"`). 0.50.0 broadcast the terminal speed of
  diameter class *j* along the velocity axis.
- `mass_spectrum_width` is sigma_m in mm (0.50.0: the variance, in mm2).
- dBZ is NaN when Z = 0 (0.50.0 clamped every value below 0 dBZ to 0).
- Dm, sigma_m, Dmax are NaN when there are no drops (0.50.0: 0).
- Rates use the sampled duration, not a fixed 60 s. Each telegram's
  measuring interval is inferred from its neighbours (robust to any loss
  rate and to an interval change) and the telegram is counted in the minute
  holding the centre of its interval (`time_binning="stamp"` for 0.50.0's
  stamp binning).
- OTT manual size classes are the default; 0.50.0 tables are `classes="legacy"`.
- New: Nw, mean fall speed, raw (unfiltered) particle count, telegram count,
  sample duration, class widths, optional raw spectrum.
- WS800 `MixingRatio_*`/`RelPress_*` columns holding specific enthalpy and air
  density are renamed with kJ kg-1 and kg m-3 units (checked against the
  thermodynamics of each file).
- Model soundings: below-ground isobaric levels dropped, surface level added
  when available, RAP/HRRR/NAM (Lambert) and polar-stereographic
  grid-relative winds rotated to earth-relative, dew point from specific
  humidity when available.
- Wind roses report calms separately instead of as northerly wind.
- Parsivel quicklook colours N(D) on a log scale and shades outages.

## Input handling

- Any file name works: sources are ordered and days released by the telegram
  stamps found in the files, so raw PIERS `..._YYYYMMDDhhmmss.zip` and APU
  `apuNN_YYYYMMDDhh.zip` names, multi-day files and undated names all work.
- Days keep their last minutes from the next morning's first packet; a
  partial copy of a day can no longer replace the complete one.
- Telegrams with the wrong number of header fields are rejected instead of
  being read shifted by one diameter class.
- Minutes without telegrams are missing (NaN), with `telegram_count = 0`.
- Each telegram counted once across daily files, packets and archives; no
  scratch files; whole-telegram validation; non-UTF-8 bytes and stray quotes
  cost one telegram at most.
- `source` attributes no longer carry directories.
- Daily files and packets are read together for AIO and gauges (0.50.0
  dropped all packets when a daily file was present).
- Met One `HHMM = 2400` rows are kept as 00:00 of the next day.
- New `read_tipping_bucket` / `tipping_bucket_rain`: a counter drop is read
  as a reset, a dip (dropout, stale value) or a spike, whichever implies the
  calmest rain (a reset when they are close); long dropouts are recognised
  when the counter returns; a drop on the last record and impossible jumps
  have unknown tips; plausible-only wrap-arounds; reports binned by the
  minute they cover; unknown minutes NaN (gaps, multi-minute reports)
  without losing their tips; suspect rates flagged and blanked.
  `glitch_window=0` reads every drop as a reset, for counters cleared on a
  schedule.
- Parsivel: an equal spectrum logged twice within 2 s counts once (unless
  the pair fills a gap, as a late stamp does); stamps
  before 2005 or in the future (logger clock not set) are rejected; stamps a
  few seconds late no longer upset the interval inference; a file whose
  telegrams are all rejected is still reported in the provenance;
  `discover_input_dates` lists the days that hold stamps.
- Met One negative values (`08-005.6`) are kept; local time zones with
  daylight saving no longer abort AIO reads.
- Merged Parsivel products report telegram counts, rejected lines (once per
  file) and the interval correctly; `read_parsivel_raw` keeps the spectrum.
- `netcdf` extra requires h5netcdf>=1.8; an old h5netcdf now raises a clear
  ImportError.

## Performance

- Parsivel: about 10x faster and 4x less memory on a 145-packet day; holds
  at most about two days of telegrams at a time for long reads, and about one
  day inside a single long time-ordered file.
- 2DVD: vectorized parsing, about 2.4x faster with identical output.

# GV Tools 0.50.1

- Accepted valid hourly APU Parsivel archives when the hour was joined
  directly to the date, such as ``apu09_2024030615.zip``, as well as the
  conventional ``apu09_20240306_15.zip`` spelling.
- Continued to reject archives that decoded to no valid Parsivel observations.
- Version 0.65.0 generalizes this behavior by deriving product dates from
  valid telegram timestamps instead of filenames.

# GV Tools 0.50.0

Version 0.50.0 is a clean release focused on instrument ingestion and
user-directed plotting.

## Supported workflows

- Read R.M. Young AIO, Met One AIO, Lufft WS800, PIERS tipping-bucket,
  Parsivel/Parsivel2, MRR2/MRRPro, weather radar, and 2DVD observations.
- Return pandas DataFrames, xarray Datasets, or a Py-ART Radar object as
  appropriate for the source format.
- Plot selected time series, instrument quicklooks, radar sweeps, MRR
  time-height fields, Parsivel DSDs, and model sounding Skew-T diagrams.
- Require users to select every figure filename. The validation notebook writes
  figures to ``$WORKSPACE/Output`` and never inside the package.

## Cleanup and compatibility

- Removed the deprecated, ambiguous ``plot_timeseries`` alias; use
  ``plot_instrument_timeseries``.
- Removed the stale ``plot_directory`` and invalid top-level ``py_2dvd`` exports.
- Consolidated PIERS support around daily products while retaining explicit
  compatible file-list input.
- Bundled the required Parsivel decoding functionality; neither
  ``piers_gauge_tools`` nor ``process_piers_plus`` is required.
- Centralized runtime processing-version metadata on ``gv_tools.__version__``.
- Corrected optional dependency groups and expanded dependency checks.
- Refreshed examples, clean notebooks, API documentation, and HTML output.

Release artifacts are available from the GitHub `v0.50.0` release.
