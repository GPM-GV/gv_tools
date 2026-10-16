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
