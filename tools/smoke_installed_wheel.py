from __future__ import annotations

import argparse
import os
import site
import sys
import sysconfig
from pathlib import Path


PLUGIN_NAME = "tivtc"


def add_existing_dll_dirs(paths: list[Path]) -> None:
    for path in paths:
        if path.exists():
            os.add_dll_directory(str(path))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test an installed vapoursynth-tivtc wheel.")
    parser.add_argument("--exercise-filter", action="store_true", help="Create TFM/TDecimate nodes and request frames.")
    args = parser.parse_args(argv)

    try:
        import vapoursynth as vs
    except ImportError as exc:
        print(f"failed to import VapourSynth Python module: {exc}", file=sys.stderr)
        return 1

    vs_pkg = Path(vs.__file__).resolve().parent
    plugin_dir = vs_pkg / "plugins" / PLUGIN_NAME
    required = [
        plugin_dir / f"{PLUGIN_NAME}.dll",
        plugin_dir / "manifest.vs",
    ]
    for path in required:
        if not path.exists():
            print(f"missing installed file: {path}", file=sys.stderr)
            return 1

    add_existing_dll_dirs(
        [
            plugin_dir,
            vs_pkg,
            Path(sys.executable).resolve().parent,
            Path(sysconfig.get_paths().get("platlib", "")),
            Path(sysconfig.get_paths().get("purelib", "")),
            *(Path(p) for p in site.getsitepackages()),
        ]
    )

    try:
        env = vs.create_environment()
        core = env.get_core()
    except AttributeError:
        core = vs.core

    if not hasattr(core, "tivtc") or not hasattr(core.tivtc, "TFM") or not hasattr(core.tivtc, "TDecimate"):
        print("core.tivtc TFM/TDecimate missing after installed-wheel autoload", file=sys.stderr)
        return 1
    print(core.tivtc.TFM)
    print(core.tivtc.TDecimate)

    if args.exercise_filter:
        try:
            clip = core.std.BlankClip(format=vs.YUV420P8, width=64, height=32, length=10, color=[96, 128, 128])
            tfm = core.tivtc.TFM(clip, order=1, field=1, mode=1, PP=0)
            tdec = core.tivtc.TDecimate(clip, mode=0, cycle=5, cycleR=1)
            tfm_frame = tfm.get_frame(0)
            tdec_frame = tdec.get_frame(0)
            tfm_stats = core.std.PlaneStats(tfm).get_frame(0).props
            tdec_stats = core.std.PlaneStats(tdec).get_frame(0).props
        except Exception as exc:
            print(f"filter exercise failed: {exc}", file=sys.stderr)
            return 1

        print(f"tfm={tfm_frame.width}x{tfm_frame.height}")
        print(f"tfm PlaneStatsAverage={tfm_stats['PlaneStatsAverage']}")
        print(f"tdec={tdec_frame.width}x{tdec_frame.height}")
        print(f"tdec PlaneStatsAverage={tdec_stats['PlaneStatsAverage']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
