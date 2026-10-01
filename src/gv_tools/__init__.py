"""NASA GPM Ground Validation instrument tools.

The public API is organized by task, following the style of ARM Py-ART::

    import gv_tools
    dataset = gv_tools.io.read_parsivel(
        ["/data/PIERS0042/PIERS0042_Parsivel_20260810_daily.zip"]
    )

``gv_tools.core``, ``gv_tools.io``, ``gv_tools.config``,
``gv_tools.correct``, and ``gv_tools.graph`` are the preferred interfaces.
Legacy top-level objects remain available for the 0.x migration period.
"""

from importlib import import_module

__version__ = "0.31.0"

__all__ = [
    "py_2dvd",
    "read_2dvd",
    "config",
    "core",
    "correct",
    "graph",
    "io",
    "InstrumentMetadata",
    "RadarIngestRoute",
    "available_adapters",
    "create_adapter",
    "ingest_radar",
    "inspect_radar_file",
    "output_directory",
    "read_mrr",
    "plot_aio_quicklook",
    "plot_aio_wind_rose",
    "plot_ws800_full_quicklook",
    "plot_parsivel_quicklook",
    "plot_radar_ppi_quicklook",
    "plot_radar_rhi_quicklook",
    "plot_radar_bb_zdr_calibration",
    "plot_mrr_time_height_quicklook",
    "plot_directory",
    "register_adapter",
    "validate_product",
    "write_product",
]

_PUBLIC_OBJECTS = {
    "py_2dvd": (".py_2dvd", None),
    "read_2dvd": (".io", "read_2dvd"),
    "config": (".config", None),
    "core": (".core", None),
    "correct": (".correct", None),
    "graph": (".graph", None),
    "io": (".io", None),
    "InstrumentMetadata": (".metadata", "InstrumentMetadata"),
    "RadarIngestRoute": (".ingest_radar", "RadarIngestRoute"),
    "available_adapters": (".registry", "available_adapters"),
    "create_adapter": (".registry", "create_adapter"),
    "ingest_radar": (".ingest_radar", "ingest_radar"),
    "inspect_radar_file": (".ingest_radar", "inspect_radar_file"),
    "output_directory": (".outputs", "output_directory"),
    "read_mrr": (".mrr", "read_mrr"),
    "plot_aio_quicklook": (".quicklooks", "plot_aio_quicklook"),
    "plot_aio_wind_rose": (".quicklooks", "plot_aio_wind_rose"),
    "plot_ws800_full_quicklook": (".quicklooks", "plot_ws800_full_quicklook"),
    "plot_parsivel_quicklook": (".quicklooks", "plot_parsivel_quicklook"),
    "plot_radar_ppi_quicklook": (".quicklooks", "plot_radar_ppi_quicklook"),
    "plot_radar_rhi_quicklook": (".quicklooks", "plot_radar_rhi_quicklook"),
    "plot_radar_bb_zdr_calibration": (".quicklooks", "plot_radar_bb_zdr_calibration"),
    "plot_mrr_time_height_quicklook": (".quicklooks", "plot_mrr_time_height_quicklook"),
    "plot_directory": (".outputs", "plot_directory"),
    "register_adapter": (".registry", "register_adapter"),
    "validate_product": (".products", "validate_product"),
    "write_product": (".outputs", "write_product"),
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
