"""NASA GPM Ground Validation instrument tools.

The public API is organized by task, following the style of ARM Py-ART::

    import gv_tools
    dataset = gv_tools.io.read_parsivel(
        ["/data/PIERS0042/PIERS0042_Parsivel_20260810_daily.zip"]
    )

``gv_tools.io`` reads instrument files without writing outputs. Plotting
functions always require a user-selected output filename.
"""

from importlib import import_module

__version__ = "0.50.0"

__all__ = [
    "read_2dvd",
    "config",
    "graph",
    "io",
    "util",
    "InstrumentMetadata",
    "RadarIngestRoute",
    "available_adapters",
    "create_adapter",
    "ingest_radar",
    "inspect_radar_file",
    "read_mrr",
    "read_gauge",
    "plot_instrument_timeseries",
    "plot_aio_quicklook",
    "plot_aio_wind_rose",
    "plot_ws800_full_quicklook",
    "plot_parsivel_quicklook",
    "plot_radar_ppi_quicklook",
    "plot_radar_rhi_quicklook",
    "plot_mrr_time_height_quicklook",
    "register_adapter",
]

_PUBLIC_OBJECTS = {
    "read_2dvd": (".io", "read_2dvd"),
    "config": (".config", None),
    "graph": (".graph", None),
    "io": (".io", None),
    "util": (".util", None),
    "InstrumentMetadata": (".metadata", "InstrumentMetadata"),
    "RadarIngestRoute": (".ingest_radar", "RadarIngestRoute"),
    "available_adapters": (".registry", "available_adapters"),
    "create_adapter": (".registry", "create_adapter"),
    "ingest_radar": (".ingest_radar", "ingest_radar"),
    "inspect_radar_file": (".ingest_radar", "inspect_radar_file"),
    "read_mrr": (".mrr", "read_mrr"),
    "read_gauge": (".io", "read_gauge"),
    "plot_instrument_timeseries": (".plotting", "plot_instrument_timeseries"),
    "plot_aio_quicklook": (".quicklooks", "plot_aio_quicklook"),
    "plot_aio_wind_rose": (".quicklooks", "plot_aio_wind_rose"),
    "plot_ws800_full_quicklook": (".quicklooks", "plot_ws800_full_quicklook"),
    "plot_parsivel_quicklook": (".quicklooks", "plot_parsivel_quicklook"),
    "plot_radar_ppi_quicklook": (".quicklooks", "plot_radar_ppi_quicklook"),
    "plot_radar_rhi_quicklook": (".quicklooks", "plot_radar_rhi_quicklook"),
    "plot_mrr_time_height_quicklook": (".quicklooks", "plot_mrr_time_height_quicklook"),
    "register_adapter": (".registry", "register_adapter"),
}


def __getattr__(name: str):
    try:
        module_name, object_name = _PUBLIC_OBJECTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    module = import_module(module_name, __name__)
    value = module if object_name is None else getattr(module, object_name)
    globals()[name] = value
    return value
