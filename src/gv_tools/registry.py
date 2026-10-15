"""Instrument adapter registry."""

from __future__ import annotations

from .adapters.base import InstrumentAdapter
from .adapters.lufft_ws800 import LufftWS800Adapter
from .adapters.metone_aio import MetOneAIOAdapter
from .adapters.parsivel import ParsivelAdapter
from .adapters.rm_young_aio import RMYoungAIOAdapter

_ADAPTERS: dict[str, type[InstrumentAdapter]] = {
    "metone_aio": MetOneAIOAdapter,
    "lufft_ws800": LufftWS800Adapter,
    "parsivel": ParsivelAdapter,
    "rm_young_aio": RMYoungAIOAdapter,
}


def register_adapter(name: str, adapter: type[InstrumentAdapter], *, replace=False) -> None:
    """Register an adapter class under a case-insensitive public name."""
    key = name.strip().lower()
    if not key:
        raise ValueError("adapter name must not be empty")
    if key in _ADAPTERS and not replace:
        raise ValueError(f"adapter is already registered: {key}")
    if not issubclass(adapter, InstrumentAdapter):
        raise TypeError("adapter must inherit InstrumentAdapter")
    _ADAPTERS[key] = adapter


def available_adapters() -> tuple[str, ...]:
    """Return registered adapter names in deterministic order."""
    return tuple(sorted(_ADAPTERS))


def create_adapter(name, metadata, **options) -> InstrumentAdapter:
    """Instantiate a registered adapter with instrument metadata and options."""
    key = name.strip().lower()
    try:
        adapter = _ADAPTERS[key]
    except KeyError as exc:
        raise ValueError(f"unknown adapter {name!r}; available: {available_adapters()}") from exc
    return adapter(metadata, **options)
