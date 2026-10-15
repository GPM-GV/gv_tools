# Metadata contract

Every product must identify its instrument, deployment, processing, and time
reference. Required global attributes are:

- `instrument_id`, `instrument_type`, and `site_id`
- `processing_level`
- `processing_software` and `processing_software_version`
- `time_reference`, which must be `UTC`

Recommended deployment fields include manufacturer, model, serial number,
latitude, longitude, altitude, campaign, and source timezone. Variables must
include `units` and `long_name`; `source_field` records the input name when a
field has been normalized.

Times are represented by a sorted, unique `datetime64` coordinate. NumPy
`datetime64` does not carry a timezone, so `time_reference=UTC` is mandatory.

