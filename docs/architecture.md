# Architecture

GV Tools separates instrument-specific decoding from scientific products:

```text
raw files -> adapter -> normalized xarray.Dataset -> QC/analysis -> output/plots
```

Instrument adapters implement the low-level decoding contract and may partition
their results by ISO date internally. The public `gv_tools.io` layer gives every
instrument the same interface: an explicit file-path list, optional date bounds,
and a single merged return product. All downstream code consumes that normalized
product and must not rely on manufacturer field names or raw file layouts.

The Parsivel adapter deliberately calls the existing `process_parsivel` public
API rather than copying its formulas. `read_raw()` returns a typed
`RawParsivelProduct`; `read()` normalizes its parameter, DSD, and moment tables
into one dataset. Instrument-aware discovery prevents files for another APU or
PIERS platform from contributing dates.

The RM Young AIO adapter natively decodes PIERS `WX` packet files. Its
`read_raw()` method exposes a typed pandas product and source accounting, while
`read()` produces normalized daily partitions that `gv_tools.io.read_aio()`
merges chronologically for the user.

The Met One AIO adapter independently decodes monthly `AIO_SITE_YYYYMM.dat`
files. It validates the filename month against each year/Julian-day/HHMM row
and exposes the same raw-versus-normalized workflow and ingest accounting.

MRR2 and MRRPro use a separate `gv_tools.io.read_mrr()` regime. MRR files
are already scientific NetCDF products, so they do not pass through a surface
instrument adapter or the scanning-radar Py-ART route. The reader identifies
MRR2 versus MRRPro from the dataset schema, normalizes MRR2 Unix timestamps,
records the detected model, and returns the native multidimensional
`xarray.Dataset`.

Outputs are staged in the destination filesystem before atomic replacement.
The typed version 0.2 manifest records checksums, platform, and temporal
coverage. Public imports are lazy so the dependency checker remains usable in
a minimal environment.

## Adding an instrument

1. Add a module under `gv_tools.adapters`.
2. Subclass `InstrumentAdapter`.
3. Convert source timestamps to the normalized UTC `time` coordinate.
4. Apply `InstrumentMetadata` and processing provenance.
5. Call `validate_product()` before returning.
6. Register the adapter and add unit tests using a small representative fixture.

Radars, profiles, spectra, and surface time series may have different dimensions.
Only their identity, time, provenance, variable metadata, and QC conventions are
shared.

Radar volumes use the public `gv_tools.io.read_radar()` entry point because Py-ART's
``Radar`` object preserves sweep, ray, gate, and instrument metadata that do not
fit the daily ``xarray.Dataset`` adapter contract. The ingest inspects the file
signature, routes raw np1 SIGMET/IRIS volumes to ``read_sigmet()``, WSR-88D
NEXRAD Level-II archives to ``read_nexrad_archive()``, and NPOL1 CF/Radial
NetCDF volumes to `read_cfradial()`. Each call reads one radar volume. Gzip,
bzip2, and single-member ZIP compression are transparent.

MRR is intentionally distinct from this scanning-radar path: its vertically
profiling time/range representation is preserved as xarray rather than mapped
to Py-ART sweeps, rays, and gates.
