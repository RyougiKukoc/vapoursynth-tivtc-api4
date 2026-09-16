#!/usr/bin/env python3
"""Create the exact zip and wheel assets published for one TIVTC platform."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "tivtc"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create release-ready TIVTC zip and wheel assets.")
    parser.add_argument("--package-dir", default="dist/msys2-ucrt64/tivtc")
    parser.add_argument("--wheel-dir", default="dist/wheels")
    parser.add_argument("--out-dir", default="dist/release-assets")
    parser.add_argument("--zip-name", default="tivtc-msys2-ucrt64.zip")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    package_dir = (ROOT / args.package_dir).resolve()
    wheel_dir = (ROOT / args.wheel_dir).resolve()
    out_dir = (ROOT / args.out_dir).resolve()
    required = [package_dir / "manifest.vs", package_dir / f"{PLUGIN_NAME}{'.dll' if args.zip_name.endswith('ucrt64.zip') else '.so'}"]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(", ".join(missing))

    wheels = sorted(wheel_dir.glob("vapoursynth_tivtc-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected exactly one TIVTC wheel in {wheel_dir}, found {len(wheels)}")

    if args.clean:
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / args.zip_name
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package_dir.rglob("*")):
            if path.is_file():
                archive.write(path, f"{PLUGIN_NAME}/{path.relative_to(package_dir).as_posix()}")

    wheel_path = out_dir / wheels[0].name
    shutil.copy2(wheels[0], wheel_path)
    assets = [zip_path, wheel_path]
    result = {
        "assets": [
            {"name": path.name, "sha256": sha256(path), "size": path.stat().st_size}
            for path in assets
        ],
        "package_dir": str(package_dir),
    }
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
