from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface
from packaging import tags


ROOT = Path(__file__).resolve().parent
PLUGIN_NAME = "tivtc"
DEFAULT_REPOSITORY = "RyougiKukoc/vapoursynth-tivtc-api4"
DEFAULT_PREBUILT_ASSET = "tivtc-msys2-ucrt64.zip"


def _truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() not in {"", "0", "false", "no", "off"})


def _project_version() -> str:
    override = os.environ.get("TIVTC_PREBUILT_VERSION")
    if override:
        return override
    with (ROOT / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not version.strip():
        raise RuntimeError("project.version is missing from pyproject.toml")
    return version


def _default_prebuilt_url(version: str) -> str:
    repository = os.environ.get("TIVTC_PREBUILT_REPOSITORY") or os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPOSITORY
    tag = os.environ.get("TIVTC_PREBUILT_TAG") or f"v{version}"
    asset = os.environ.get("TIVTC_PREBUILT_ASSET_NAME") or DEFAULT_PREBUILT_ASSET
    return f"https://github.com/{repository}/releases/download/{tag}/{asset}"


def _prebuilt_source(version: str) -> tuple[str, bool]:
    explicit = os.environ.get("TIVTC_PREBUILT_URL")
    if explicit:
        return explicit, True
    return _default_prebuilt_url(version), False


def _supports_prebuilt() -> bool:
    return sys.platform == "win32" and platform.machine().lower() in {"amd64", "x86_64"}


def _fetch_prebuilt_archive(source: str, destination: Path) -> None:
    candidate = Path(source)
    if candidate.exists():
        shutil.copy2(candidate, destination)
        return

    request = urllib.request.Request(source, headers={"User-Agent": "vapoursynth-tivtc-build-hook"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def _stage_package_from_zip(archive_path: Path, target_dir: Path) -> None:
    with zipfile.ZipFile(archive_path) as zf:
        package_members = [
            name
            for name in zf.namelist()
            if name.replace("\\", "/").startswith(f"{PLUGIN_NAME}/") and not name.endswith("/")
        ]
        if not package_members:
            raise FileNotFoundError(f"prebuilt archive does not contain a {PLUGIN_NAME}/ package directory")

        for member in package_members:
            normalized = member.replace("\\", "/")
            relative = normalized.split("/", 1)[1]
            out_path = target_dir / relative
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, out_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)

    plugin_dll = target_dir / f"{PLUGIN_NAME}.dll"
    if not plugin_dll.exists():
        raise FileNotFoundError(f"prebuilt archive did not provide {PLUGIN_NAME}.dll")
    manifest = target_dir / "manifest.vs"
    if not manifest.exists():
        manifest.write_text("[VapourSynth Manifest V1]\ntivtc\n", encoding="ascii", newline="\n")


def _stage_prebuilt_plugin(version: str, target_dir: Path) -> bool:
    if _truthy(os.environ.get("TIVTC_FORCE_BUILD")):
        print("TIVTC wheel build: skipping prebuilt asset because TIVTC_FORCE_BUILD is set")
        return False
    if not _supports_prebuilt():
        print("TIVTC wheel build: prebuilt release asset path only applies to Windows x86_64; falling back to local build")
        return False

    source, explicit = _prebuilt_source(version)
    asset_name = Path(source).name or DEFAULT_PREBUILT_ASSET
    try:
        with tempfile.TemporaryDirectory(prefix="tivtc-prebuilt-") as temp_dir_text:
            archive_path = Path(temp_dir_text) / asset_name
            _fetch_prebuilt_archive(source, archive_path)
            _stage_package_from_zip(archive_path, target_dir)
    except Exception as exc:
        if explicit:
            raise RuntimeError(f"failed to use explicit TIVTC prebuilt asset {source!r}") from exc
        print(f"TIVTC wheel build: prebuilt asset unavailable at {source}; falling back to local build ({exc})")
        return False

    print(f"TIVTC wheel build: using prebuilt release asset {source}")
    return True


def _run(cmd: list[str], *, env: dict[str, str]) -> None:
    print("+ " + subprocess.list2cmdline(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True, env=env)


def _prepend_path_entries(env: dict[str, str], entries: list[Path]) -> None:
    parts = [str(entry) for entry in entries if entry.exists()]
    if not parts:
        return
    existing = env.get("PATH")
    env["PATH"] = os.pathsep.join(parts + ([existing] if existing else []))


def _candidate_msys2_prefixes(env: dict[str, str]) -> list[Path]:
    prefixes: list[Path] = []
    msystem_prefix = env.get("MSYSTEM_PREFIX")
    if msystem_prefix:
        prefixes.append(Path(msystem_prefix))
    for var_name in ("MSYS2_ROOT", "MSYS2_DIR"):
        msys2_root = env.get(var_name)
        if not msys2_root:
            continue
        root = Path(msys2_root)
        prefixes.extend([root / "ucrt64", root / "mingw64"])
    for parent in (ROOT, *ROOT.parents):
        msys2_root = parent / "msys2"
        if not msys2_root.exists():
            continue
        prefixes.extend([msys2_root / "ucrt64", msys2_root / "mingw64"])
        break
    prefixes.extend([Path(r"C:\msys64\ucrt64"), Path(r"C:\msys64\mingw64")])

    seen: set[str] = set()
    unique: list[Path] = []
    for prefix in prefixes:
        key = str(prefix).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(prefix)
    return unique


def _configure_windows_build_env(env: dict[str, str]) -> dict[str, str]:
    if sys.platform != "win32":
        return env

    path_entries: list[Path] = []
    python_scripts = Path(sys.executable).resolve().parent / "Scripts"
    if python_scripts.exists():
        path_entries.append(python_scripts)

    for prefix in _candidate_msys2_prefixes(env):
        path_entries.extend([prefix / "bin", prefix.parent / "usr" / "bin"])
    _prepend_path_entries(env, path_entries)

    env.setdefault("CC", "gcc")
    env.setdefault("CXX", "g++")
    return env


def _stage_local_build(target_dir: Path) -> None:
    env = _configure_windows_build_env(os.environ.copy())
    build_dir = ROOT / "build-wheel-msys2"
    plugins_root = target_dir.parent
    _run([sys.executable, "tools/ci_prepare_msys2.py"], env=env)
    _run(
        [
            sys.executable,
            "tools/ci_build_msys2.py",
            "--clean",
            "--build-dir",
            str(build_dir),
            "--dist-dir",
            str(plugins_root),
        ],
        env=env,
    )
    if not (target_dir / f"{PLUGIN_NAME}.dll").exists():
        raise FileNotFoundError(target_dir / f"{PLUGIN_NAME}.dll")


class CustomHook(BuildHookInterface[Any]):
    build_dir = ROOT / "build-wheel-msys2"
    dist_dir = ROOT / "vapoursynth" / "plugins" / PLUGIN_NAME

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        del version
        build_data["pure_python"] = False
        build_data["tag"] = f"py3-none-{next(tags.platform_tags())}"
        project_version = _project_version()

        shutil.rmtree(self.build_dir, ignore_errors=True)
        shutil.rmtree(self.dist_dir.parent.parent, ignore_errors=True)
        self.dist_dir.mkdir(parents=True, exist_ok=True)

        if not _stage_prebuilt_plugin(project_version, self.dist_dir):
            _stage_local_build(self.dist_dir)

    def finalize(self, version: str, build_data: dict[str, Any], artifact_path: str) -> None:
        del version, build_data, artifact_path
        shutil.rmtree(self.build_dir, ignore_errors=True)
        shutil.rmtree(self.dist_dir.parent.parent, ignore_errors=True)
