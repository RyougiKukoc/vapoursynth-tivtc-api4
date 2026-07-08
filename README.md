# VapourSynth TIVTC

TIVTC provides field matching and decimation filters for VapourSynth:

- `core.tivtc.TFM`
- `core.tivtc.TDecimate`

This repository contains the API4 migration target and a Windows-first pip
packaging path for current VapourSynth releases.

## Install

Windows x86_64 users can install directly from the Git repository:

```powershell
pip install "vapoursynth-tivtc @ git+https://github.com/RyougiKukoc/vapoursynth-tivtc-api4.git"
```

The source-install wheel build first tries to download the matching GitHub
Release asset:

```text
https://github.com/RyougiKukoc/vapoursynth-tivtc-api4/releases/download/v3.5/tivtc-msys2-ucrt64.zip
```

If that asset is available, `pip` repackages the tested plugin payload into the
installed wheel. If not, the build hook falls back to a local Meson build.

To force a local build:

```powershell
$env:TIVTC_FORCE_BUILD = "1"
pip install "vapoursynth-tivtc @ git+https://github.com/RyougiKukoc/vapoursynth-tivtc-api4.git"
```

To point at a specific local or remote prebuilt zip:

```powershell
$env:TIVTC_PREBUILT_URL = "C:\path\to\tivtc-msys2-ucrt64.zip"
pip install --force-reinstall --no-deps --no-build-isolation .
```

The installed wheel places the plugin under:

```text
site-packages/vapoursynth/plugins/tivtc/
  tivtc.dll
  manifest.vs
```

The `manifest.vs` file ensures VapourSynth autoloads only `tivtc.dll` from
that directory.

## Runtime

The filters remain clip-input temporal filters and still require deterministic
usage for meaningful verification. The local migration work for this repository
validated:

- API3 baseline build/load/run on R73
- API4 build/load/run on R77
- paired R73/API3 versus R77/API4 report comparison with strict matches

## Local build

Meson still works directly for native builds:

```powershell
meson setup build
meson compile -C build
```

For the current Windows packaging path, the repository also includes helper
scripts under `tools/` for:

- preparing the VapourSynth R77 wheel as a build SDK
- producing a release-style package directory and zip
- smoke-testing the package directory
- smoke-testing an installed wheel

## License

The upstream source headers state GPL 2 or later.
