from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str]) -> int:
    pkg_config = os.environ.get("PKG_CONFIG_REAL")
    if pkg_config:
        cmd = [pkg_config, *argv]
    else:
        for candidate in ["pkg-config.exe", "pkgconf.exe", "pkg-config", "pkgconf"]:
            resolved = shutil.which(candidate)  # type: ignore[name-defined]
            if resolved:
                cmd = [resolved, *argv]
                break
        else:
            raise FileNotFoundError("pkg-config")

    env = os.environ.copy()
    pc = ROOT / "_deps" / "vapoursynth-wheel-R77" / "vapoursynth" / "lib" / "pkgconfig"
    paths = [str(pc)]
    existing = env.get("PKG_CONFIG_PATH")
    if existing:
        paths.append(existing)
    env["PKG_CONFIG_PATH"] = os.pathsep.join(paths)
    completed = subprocess.run(cmd, env=env, cwd=ROOT, check=False)
    return completed.returncode


if __name__ == "__main__":
    import shutil

    raise SystemExit(main(sys.argv[1:]))
