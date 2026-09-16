#!/usr/bin/env python3
"""Explicitly load a TIVTC release directory or zip with autoload disabled."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "tivtc"


def plugin_suffix() -> str:
    if sys.platform == "win32":
        return ".dll"
    if sys.platform == "darwin":
        return ".dylib"
    return ".so"


def frame_hash(frame: Any) -> str:
    digest = hashlib.sha256()
    for plane in range(frame.format.num_planes):
        digest.update(bytes(frame[plane]))
    return digest.hexdigest()


class IsolatedEnvironmentPolicy:
    def __init__(self, flags: int) -> None:
        self.api: Any = None
        self.environment: Any = None
        self.flags = flags

    def on_policy_registered(self, api: Any) -> None:
        self.api = api
        self.environment = api.create_environment(self.flags)

    def on_policy_cleared(self) -> None:
        self.api = None
        self.environment = None

    def get_current_environment(self) -> Any:
        return self.environment

    def set_environment(self, environment: Any) -> Any:
        previous = self.environment
        if environment is not None:
            self.environment = environment
        return previous

    def is_alive(self, environment: Any) -> bool:
        return environment is self.environment

    def close(self) -> None:
        if self.api is not None and self.environment is not None:
            self.api.destroy_environment(self.environment)
            self.environment = None


def disable_autoload(vs_module: Any) -> IsolatedEnvironmentPolicy | None:
    if not hasattr(vs_module, "register_policy") or vs_module.has_policy():
        return None
    policy = IsolatedEnvironmentPolicy(int(vs_module.DISABLE_AUTO_LOADING))
    vs_module.register_policy(policy)
    return policy


def release_dir(path: str | None, archive: str | None) -> tuple[Path, Path | None]:
    if path:
        return (ROOT / path).resolve(), None
    if not archive:
        raise ValueError("one of --artifact-dir or --artifact-zip is required")
    archive_path = (ROOT / archive).resolve()
    temporary = Path(tempfile.mkdtemp(prefix="tivtc-release-"))
    with zipfile.ZipFile(archive_path) as zf:
        zf.extractall(temporary)
    directories = [candidate for candidate in temporary.iterdir() if candidate.is_dir()]
    if len(directories) != 1:
        raise RuntimeError(f"expected one top-level plugin directory in {archive_path}, found {len(directories)}")
    return directories[0], temporary


def filter_report(core: Any, vs_module: Any) -> dict[str, Any]:
    clip = core.std.BlankClip(width=64, height=48, format=vs_module.YUV420P8, length=20, color=[96, 128, 128])
    tfm = core.tivtc.TFM(clip, order=1, field=1, mode=1, PP=0)
    decimate = core.tivtc.TDecimate(clip, mode=0, cycle=5, cycleR=1)
    frames = {number: tfm.get_frame(number) for number in (0, 3, 11)}
    decimated = decimate.get_frame(3)
    stats = dict(core.std.PlaneStats(tfm).get_frame(3).props)
    hashes = {number: frame_hash(frame) for number, frame in frames.items()}
    if len(set(hashes.values())) != 1:
        raise RuntimeError(f"static TFM input produced inconsistent frame hashes: {hashes}")

    invalid_rejected = False
    try:
        core.tivtc.TFM(core.std.BlankClip(width=64, height=48, format=vs_module.RGB24, length=1), order=1)
    except vs_module.Error:
        invalid_rejected = True
    if not invalid_rejected:
        raise RuntimeError("TFM accepted unsupported RGB input")
    frame = frames[3]
    return {
        "decimate_frames": decimate.num_frames,
        "decimate_frame_hash": frame_hash(decimated),
        "frame_hashes": hashes,
        "frames": tfm.num_frames,
        "format": frame.format.name,
        "height": frame.height,
        "invalid_rgb_rejected": invalid_rejected,
        "plane_stats_average": float(stats["PlaneStatsAverage"]),
        "plane_stats_max": float(stats["PlaneStatsMax"]),
        "plane_stats_min": float(stats["PlaneStatsMin"]),
        "width": frame.width,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Explicit TIVTC release-payload smoke test.")
    parser.add_argument("--artifact-dir")
    parser.add_argument("--artifact-zip")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    artifact_dir, temporary = release_dir(args.artifact_dir, args.artifact_zip)
    plugin = artifact_dir / f"{PLUGIN_NAME}{plugin_suffix()}"
    manifest = artifact_dir / "manifest.vs"
    if not plugin.is_file() or not manifest.is_file():
        raise FileNotFoundError(f"missing required TIVTC payload files under {artifact_dir}")

    import vapoursynth as vs

    policy = disable_autoload(vs)
    try:
        core = vs.core
        core.std.LoadPlugin(str(plugin))
        result = {
            "manifest": str(manifest),
            "plugin": str(plugin),
            **filter_report(core, vs),
        }
        print(json.dumps(result, indent=2, sort_keys=True) if args.json else result)
    finally:
        if policy is not None:
            policy.close()
        if temporary is not None:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
