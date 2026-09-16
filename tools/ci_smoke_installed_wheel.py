#!/usr/bin/env python3
"""Autoload smoke test for an installed TIVTC wheel."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ci_smoke_package import PLUGIN_NAME, filter_report, plugin_suffix


def main() -> int:
    parser = argparse.ArgumentParser(description="Autoload smoke test for an installed TIVTC wheel.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    import vapoursynth as vs

    plugin = Path(vs.__file__).resolve().parent / "plugins" / PLUGIN_NAME / f"{PLUGIN_NAME}{plugin_suffix()}"
    manifest = plugin.with_name("manifest.vs")
    if not plugin.is_file() or not manifest.is_file():
        raise FileNotFoundError(f"missing installed TIVTC payload under {plugin.parent}")
    core = vs.core
    if not hasattr(core, "tivtc"):
        raise RuntimeError("TIVTC namespace was not autoloaded from the installed wheel")
    result = {"manifest": str(manifest), "plugin": str(plugin), **filter_report(core, vs)}
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
