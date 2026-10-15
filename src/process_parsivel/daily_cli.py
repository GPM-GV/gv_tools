"""Module entry point for the daily APU archive converter."""

from .daily import daily_main


if __name__ == "__main__":
    raise SystemExit(daily_main())
