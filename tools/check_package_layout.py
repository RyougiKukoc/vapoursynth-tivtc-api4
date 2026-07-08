from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path


def normalize_name(name: str) -> str:
    name = name.replace("\\", "/").strip()
    while name.startswith("./"):
        name = name[2:]
    while name.startswith("/"):
        name = name[1:]
    return "/".join(part for part in name.split("/") if part and part != ".")


def open_names(path: Path) -> list[str]:
    if path.is_dir():
        return sorted(normalize_name(p.relative_to(path).as_posix()) for p in path.rglob("*") if p.is_file())
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            names: set[str] = set()
            for info in zf.infolist():
                if info.is_dir():
                    continue
                normalized = normalize_name(info.filename)
                if normalized:
                    names.add(normalized)
            return sorted(names)
    raise FileNotFoundError(f"not a directory or zip file: {path}")


def parent_dirs_for(names: list[str], filename: str) -> set[str]:
    filename = normalize_name(filename).strip("/")
    parents: set[str] = set()
    for name in names:
        if name == filename:
            parents.add("")
        elif name.endswith(f"/{filename}"):
            parents.add(name[: -(len(filename) + 1)])
    return parents


def infer_package_dir(names: list[str], plugin_dll: str, manifest: str) -> str:
    plugin_dirs = parent_dirs_for(names, plugin_dll)
    manifest_dirs = parent_dirs_for(names, manifest)
    common_dirs = plugin_dirs & manifest_dirs
    if len(common_dirs) == 1:
        return next(iter(common_dirs))
    if len(plugin_dirs) == 1 and not manifest_dirs:
        return next(iter(plugin_dirs))

    top_files = [name for name in names if "/" not in name]
    top_dirs = sorted({name.split("/", 1)[0] for name in names if "/" in name})
    if len(top_dirs) == 1 and not top_files:
        return top_dirs[0]
    if plugin_dll in names or manifest in names:
        return ""
    raise RuntimeError("could not infer package directory")


def read_manifest_plugins(path: Path, manifest_name: str) -> list[str]:
    if path.is_dir():
        text = (path / manifest_name).read_text(encoding="utf-8-sig", errors="replace")
    else:
        with zipfile.ZipFile(path) as zf:
            text = zf.read(manifest_name).decode("utf-8-sig", errors="replace")

    plugins: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        plugins.append(line)
    return plugins


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate a TIVTC plugin package directory or zip.")
    parser.add_argument("path")
    parser.add_argument("--plugin-dll", required=True)
    parser.add_argument("--manifest", default="manifest.vs")
    parser.add_argument("--require-manifest", action="store_true")
    parser.add_argument("--require-top-level-dir", action="store_true")
    parser.add_argument("--forbid-vapoursynth-prefix", action="store_true")
    args = parser.parse_args(argv)

    source = Path(args.path).resolve()
    names = open_names(source)
    if not names:
        print("error: package is empty", file=sys.stderr)
        return 1

    plugin_dll = normalize_name(args.plugin_dll).strip("/")
    manifest = normalize_name(args.manifest).strip("/")
    package_dir = infer_package_dir(names, plugin_dll, manifest)
    prefix = f"{package_dir}/" if package_dir else ""
    rel_files = {name[len(prefix) :] if prefix else name for name in names if name.startswith(prefix)}

    errors: list[str] = []
    if args.require_top_level_dir and not package_dir:
        errors.append("artifact does not preserve a top-level package directory")
    if args.forbid_vapoursynth_prefix and package_dir.lower().startswith("vapoursynth/"):
        errors.append(f"artifact has redundant VapourSynth install prefix: {package_dir}")
    if args.require_top_level_dir and package_dir:
        outside = [name for name in names if not name.startswith(prefix)]
        if outside:
            errors.append("files outside package directory: " + ", ".join(outside[:10]))
    if plugin_dll not in rel_files:
        errors.append(f"missing plugin DLL: {prefix}{plugin_dll}")
    if args.require_manifest and manifest not in rel_files:
        errors.append(f"missing manifest: {prefix}{manifest}")
    if manifest in rel_files:
        manifest_name = prefix + manifest
        plugins = read_manifest_plugins(source, manifest_name)
        if Path(plugin_dll).stem not in plugins:
            errors.append(f"manifest does not list plugin base name {Path(plugin_dll).stem!r}: {manifest_name}")

    print(f"source={source}")
    print(f"package_dir={package_dir or '.'}")
    print(f"files={len(rel_files)}")
    for name in sorted(rel_files):
        print(name)

    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
