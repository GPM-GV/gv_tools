"""Command-line entry point."""

from __future__ import annotations

import argparse
import platform
import sys


def build_parser():
    """Build the ``gv-tools`` command-line argument parser."""
    parser = argparse.ArgumentParser(prog="gv-tools")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="report runtime dependency availability")
    check.add_argument(
        "--include",
        choices=("radar", "plot", "notebook", "sounding", "docs"),
        action="append",
        default=[],
        help="also check an optional dependency group (repeatable)",
    )
    return parser


def main(argv=None):
    """Run the dependency-report command and return a process status code."""
    args = build_parser().parse_args(argv)
    from .environment import dependency_report

    groups = ("required", "netcdf", *args.include)
    print(f"Python: {sys.version.split()[0]}")
    print(f"Platform: {platform.platform()}")
    missing = []
    for item in dependency_report(groups):
        status = "OK" if item["compatible"] else (
            "OLD" if item["available"] else "MISSING"
        )
        print(
            f"{status:7} {item['package']:<18} installed={item['installed']} "
            f"minimum={item['minimum']} ({item['group']})"
        )
        if not item["compatible"]:
            missing.append(item["package"])
    if missing:
        extras = ",".join(("netcdf", *args.include))
        print(f"Install with: python -m pip install 'gv_tools[{extras}]'")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
