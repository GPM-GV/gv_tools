"""Instrument readers and adapters that return pandas or xarray objects."""

from ..adapters import (
    InstrumentAdapter,
    LufftWS800Adapter,
    MetOneAIOAdapter,
    ParsivelAdapter,
    ParsivelSourcePlatform,
    RMYoungAIOAdapter,
    RawMetOneAIOProduct,
    RawLufftWS800Product,
    RawParsivelProduct,
    RawRMYoungAIOProduct,
)
from ..ingest_radar import RadarIngestRoute, ingest_radar, inspect_radar_file
from ..mrr import read_mrr
from ..registry import available_adapters, create_adapter, register_adapter
from .gauge import read_gauge
from .readers import (
    discover_aio,
    discover_metone,
    discover_parsivel,
    inspect_radar,
    read_aio,
    read_aio_raw,
    read_metone,
    read_metone_raw,
    read_parsivel,
    read_parsivel_raw,
    read_radar,
    read_ws800_full,
)

__all__ = [
    "InstrumentAdapter",
    "LufftWS800Adapter",
    "MetOneAIOAdapter",
    "ParsivelAdapter",
    "ParsivelSourcePlatform",
    "RMYoungAIOAdapter",
    "RadarIngestRoute",
    "RawMetOneAIOProduct",
    "RawLufftWS800Product",
    "RawParsivelProduct",
    "RawRMYoungAIOProduct",
    "available_adapters",
    "create_adapter",
    "discover_aio",
    "discover_metone",
    "discover_parsivel",
    "ingest_radar",
    "inspect_radar_file",
    "inspect_radar",
    "register_adapter",
    "read_aio",
    "read_aio_raw",
    "read_metone",
    "read_metone_raw",
    "read_mrr",
    "read_parsivel",
    "read_parsivel_raw",
    "read_radar",
    "read_gauge",
    "read_ws800_full",
]

from .py_2dvd import ingest_raw
read_2dvd = ingest_raw
__all__ += ["read_2dvd", "ingest_raw"]
