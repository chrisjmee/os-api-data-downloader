#!/usr/bin/env python3
"""Builds the local index of every OS NGD feature type's description-style attribute and its allowed
values - the same thing the "Find an NGD Feature Type" tab's own 'Rebuild index' button does inside QGIS,
but runnable from a terminal. Handy for generating the CSV bundled with the plugin itself (so a fresh
install has real data from the first run, not just an empty template), or for scripting/CI.

It checks every OS NGD feature type's queryables once (a couple of hundred API calls), so it takes a
minute or two and needs an OS Data Hub API key for the OS NGD API - Features product. It makes no other
changes - OS NGD is a REST API, not a database, so there's no SQL involved anywhere in this.

Usage:
    python3 build_ngd_index.py [-o OUTPUT_CSV] [--api-key KEY]

The API key can also come from the OS_API_KEY or OS_PLACES_API_KEY environment variable (the same ones the
plugin itself falls back to - see core/settings.py). No QGIS installation or extra pip packages are needed,
just a plain Python 3 interpreter.
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(HERE)
sys.path.insert(0, os.path.dirname(PLUGIN_DIR))   # so "os_api_data_downloader" is importable

from os_api_data_downloader.core.budget import Budget  # noqa: E402
from os_api_data_downloader.core.ngd_features import NgdFeaturesClient  # noqa: E402
from os_api_data_downloader.core.ngd_index import build, write_csv  # noqa: E402
from os_api_data_downloader.core.transport import UrllibTransport  # noqa: E402

DEFAULT_OUT = os.path.join(PLUGIN_DIR, "data", "ngd_feature_types.csv")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-o", "--output", default=DEFAULT_OUT,
                   help=f"CSV file to write (default: the plugin's own bundled copy, {DEFAULT_OUT})")
    p.add_argument("--api-key", help="OS Data Hub API key (else the OS_API_KEY / OS_PLACES_API_KEY "
                                     "environment variable)")
    args = p.parse_args()

    api_key = args.api_key or os.environ.get("OS_API_KEY") or os.environ.get("OS_PLACES_API_KEY")
    if not api_key:
        sys.exit("No API key given - pass --api-key YOUR_KEY, or set the OS_API_KEY environment variable.")

    client = NgdFeaturesClient(api_key, transport=UrllibTransport(), budget=Budget())

    def progress(pct, msg=None):
        print(f"\r{pct:5.1f}%  {(msg or ''):<60}", end="", flush=True)

    print("Checking every OS NGD feature type's queryables - this takes a minute or two...")
    index = build(client, progress=progress, is_cancelled=lambda: False)
    print()

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    write_csv(index, args.output)
    with_attr = sum(1 for info in index.values() if info.get("attr"))
    print(f"Wrote {len(index)} feature types to {args.output} ({with_attr} with a filterable attribute "
          f"found, {len(index) - with_attr} without).")


if __name__ == "__main__":
    main()
