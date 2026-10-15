# Output conventions

Products are written beneath a stable deployment hierarchy:

```text
ROOT/SITE_ID/INSTRUMENT_ID/YYYY/MM/DD/
```

File stems are `SITE_INSTRUMENT_YYYYMMDD`. NetCDF is the scientific exchange
format. CSV output is split into parameters, DSD, and moments so dimensional
data are never flattened ambiguously.

Each daily directory contains `manifest.json` with schema version, UTC creation
time, product date, source platform, temporal coverage, processing software
versions, output roles, and a SHA-256 checksum for every data file. Version 0.2
files are staged before atomic replacement. A writer never modifies source
files.

Plots use a separate hierarchy selected by the caller:

```text
OUTPUT_ROOT/Plots/PLOT_TYPE/YYYY/MM/
```

Use `gv_tools.plot_directory()` rather than constructing this path in notebooks.

Every public GV Tools plot and quicklook includes the site, observation date,
and instrument name or identifier in its title or suptitle. If `title=` is
supplied, that text is used as the heading and the required metadata context is
added on the following line. Missing metadata is labeled explicitly rather
than silently omitted.

Legends attached to line-data axes use Matplotlib's automatic `best`
placement so the renderer selects the least obstructive in-axis location.
Keys intentionally anchored outside an axis, such as wind-rose speed bins,
remain outside the plotted data region.
