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
WINDOWS_PREBUILT_ASSET = "tivtc-msys2-ucrt64.zip"
LINUX_PREBUILT_ASSET = "tivtc-linux-x86_64.zip"


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


def _default_prebuilt_asset() -> str:
    if sys.platform == "linux" and platform.machine().lower() in {"amd64", "x86_64"}:
        return LINUX_PREBUILT_ASSET
    return WINDOWS_PREBUILT_ASSET


def _default_prebuilt_url(version: str) -> str:
    repository = os.environ.get("TIVTC_PREBUILT_REPOSITORY") or os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPOSITORY
    tag = os.environ.get("TIVTC_PREBUILT_TAG") or f"v{version}"
    asset = os.environ.get("TIVTC_PREBUILT_ASSET_NAME") or _default_prebuilt_asset()
    return f"https://github.com/{repository}/releases/download/{tag}/{asset}"


def _prebuilt_source(version: str) -> tuple[str, bool]:
    explicit = os.environ.get("TIVTC_PREBUILT_URL")
    if explicit:
        return explicit, True
    return _default_prebuilt_url(version), False


def _supports_prebuilt() -> bool:
    return sys.platform in {"win32", "linux"} and platform.machine().lower() in {"amd64", "x86_64"}


def _plugin_filename() -> str:
    if sys.platform == "win32":
        return f"{PLUGIN_NAME}.dll"
    if sys.platform == "darwin":
        return f"{PLUGIN_NAME}.dylib"
    return f"{PLUGIN_NAME}.so"


def _fetch_prebuilt_archive(source: str, destination: Path) -> None:
    candidate = Path(source)
    if candidate.exists():
        shutil.copy2(candidate, destination)
        return

    request = urllib.request.Request(source, headers={"User-Agent": "vapoursynth-tivtc-build-hook"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def _write_manifest(target_dir: Path) -> None:
    (target_dir / "manifest.vs").write_text(
        "[VapourSynth Manifest V1]\n"
        f"{PLUGIN_NAME}\n",
        encoding="ascii",
        newline="\n",
    )


def _stage_package_from_zip(archive_path: Path, target_dir: Path) -> None:
    root = target_dir.resolve()
    with zipfile.ZipFile(archive_path) as zf:
        members = [info.filename.replace("\\", "/") for info in zf.infolist() if not info.is_dir()]
        if not members or any(not member.startswith(f"{PLUGIN_NAME}/") for member in members):
            raise FileNotFoundError(f"prebuilt archive must contain only a top-level {PLUGIN_NAME}/ package directory")

        for member in members:
            relative = member.split("/", 1)[1]
            out_path = (target_dir / relative).resolve()
            try:
                out_path.relative_to(root)
            except ValueError as exc:
                raise RuntimeError(f"unsafe path in prebuilt archive: {member!r}") from exc
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, out_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)

    plugin = target_dir / _plugin_filename()
    if not plugin.is_file():
        raise FileNotFoundError(f"prebuilt archive did not provide {_plugin_filename()}")
    if not (target_dir / "manifest.vs").is_file():
        _write_manifest(target_dir)


def _stage_prebuilt_plugin(version: str, target_dir: Path) -> bool:
    if _truthy(os.environ.get("TIVTC_FORCE_BUILD")):
        print("TIVTC wheel build: skipping prebuilt asset because TIVTC_FORCE_BUILD is set")
        return False
    if not _supports_prebuilt():
        print("TIVTC wheel build: no matching platform release asset path; falling back to local build")
        return False

    source, explicit = _prebuilt_source(version)
    asset_name = Path(source).name or _default_prebuilt_asset()
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
    if parts:
        existing = env.get("PATH")
        env["PATH"] = os.pathsep.join(parts + ([existing] if existing else []))


def _candidate_msys2_prefixes(env: dict[str, str]) -> list[Path]:
    prefixes: list[Path] = []
    if env.get("MSYSTEM_PREFIX"):
        prefixes.append(Path(env["MSYSTEM_PREFIX"]))
    for var_name in ("MSYS2_ROOT", "MSYS2_DIR"):
        if env.get(var_name):
            root = Path(env[var_name])
            prefixes.extend([root / "ucrt64", root / "mingw64"])
    prefixes.extend([Path(r"C:\msys64\ucrt64"), Path(r"C:\msys64\mingw64")])
    return list(dict.fromkeys(prefixes))


def _configure_windows_build_env(env: dict[str, str]) -> dict[str, str]:
    path_entries = [Path(sys.executable).resolve().parent / "Scripts"]
    for prefix in _candidate_msys2_prefixes(env):
        path_entries.extend([prefix / "bin", prefix.parent / "usr" / "bin"])
    _prepend_path_entries(env, path_entries)
    env.setdefault("CC", "gcc")
    env.setdefault("CXX", "g++")
    return env


def _configure_posix_build_env(env: dict[str, str]) -> dict[str, str]:
    """Prepend the wheel SDK while retaining any caller-supplied pc search path."""
    try:
        import vapoursynth
    except ImportError:
        return env
    pkgconfig_dir = Path(vapoursynth.__file__).resolve().parent / "pkgconfig"
    if pkgconfig_dir.is_dir():
        existing = env.get("PKG_CONFIG_PATH")
        env["PKG_CONFIG_PATH"] = os.pathsep.join(
            [str(pkgconfig_dir)] + ([existing] if existing else [])
        )
    return env


def _meson_command() -> list[str]:
    meson = shutil.which("meson")
    if meson:
        return [meson]
    for module_name in ("mesonbuild", "mesonbuild.mesonmain"):
        command = [sys.executable, "-m", module_name]
        if subprocess.run(command + ["--version"], cwd=ROOT, capture_output=True).returncode == 0:
            return command
    raise FileNotFoundError("meson executable not found and python -m mesonbuild is unavailable")


def _find_built_plugin(build_dir: Path) -> Path:
    suffixes = [".dll"] if sys.platform == "win32" else [".so", ".dylib"]
    for suffix in suffixes:
        for stem in (PLUGIN_NAME, f"lib{PLUGIN_NAME}"):
            candidate = build_dir / f"{stem}{suffix}"
            if candidate.is_file():
                return candidate
    raise FileNotFoundError(f"missing built TIVTC plugin under {build_dir}")


def _stage_local_build(target_dir: Path) -> None:
    if sys.platform == "win32":
        env = _configure_windows_build_env(os.environ.copy())
        build_dir = ROOT / "build-wheel-msys2"
        _run([sys.executable, "tools/ci_prepare_msys2.py"], env=env)
        _run(
            [
                sys.executable,
                "tools/ci_build_msys2.py",
                "--clean",
                "--build-dir",
                str(build_dir),
                "--dist-dir",
                str(target_dir.parent),
            ],
            env=env,
        )
        if not (target_dir / _plugin_filename()).is_file():
            raise FileNotFoundError(target_dir / _plugin_filename())
        return

    env = _configure_posix_build_env(os.environ.copy())
    build_dir = ROOT / "build-wheel-native"
    meson = _meson_command()
    _run(meson + ["setup", str(build_dir), "--wipe"], env=env)
    _run(meson + ["compile", "-C", str(build_dir)], env=env)
    shutil.copy2(_find_built_plugin(build_dir), target_dir / _plugin_filename())
    _write_manifest(target_dir)


class CustomHook(BuildHookInterface[Any]):
    dist_dir = ROOT / "vapoursynth" / "plugins" / PLUGIN_NAME

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        del version
        build_data["pure_python"] = False
        platform_tag = os.environ.get("TIVTC_PLATFORM_TAG") or str(next(tags.platform_tags()))
        build_data["tag"] = f"py3-none-{platform_tag}"

        build_dir = ROOT / ("build-wheel-msys2" if sys.platform == "win32" else "build-wheel-native")
        shutil.rmtree(build_dir, ignore_errors=True)
        shutil.rmtree(self.dist_dir.parent.parent, ignore_errors=True)
        self.dist_dir.mkdir(parents=True, exist_ok=True)
        if not _stage_prebuilt_plugin(_project_version(), self.dist_dir):
            _stage_local_build(self.dist_dir)

    def finalize(self, version: str, build_data: dict[str, Any], artifact_path: str) -> None:
        del version, build_data, artifact_path
        for build_dir in (ROOT / "build-wheel-msys2", ROOT / "build-wheel-native"):
            shutil.rmtree(build_dir, ignore_errors=True)
        shutil.rmtree(self.dist_dir.parent.parent, ignore_errors=True)
