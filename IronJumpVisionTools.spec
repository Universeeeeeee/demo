# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all


ROOT = Path(SPECPATH).resolve()


def files(pattern, destination):
    return [(str(path), destination) for path in ROOT.glob(pattern) if path.is_file()]


mediapipe_data, mediapipe_binaries, mediapipe_hidden = collect_all("mediapipe")
dayu_data, dayu_binaries, dayu_hidden = collect_all("dayu_widgets")

datas = [
    *mediapipe_data,
    *dayu_data,
    *files("config/*.json", "config"),
    *files("ui/assets/*", "ui/assets"),
]
binaries = [
    *mediapipe_binaries,
    *dayu_binaries,
    *files("camera/bin/*.dll", "camera/bin"),
    *files("hardware/CyUsbInterface.dll", "."),
]

model = ROOT / "models" / "pose_landmarker_full.task"
if model.is_file():
    datas.append((str(model), "models"))

build_info = ROOT / "build" / "IronJumpVisionTools_build_info.json"
if build_info.is_file():
    datas.append((str(build_info), "."))

icon = ROOT / "ui" / "assets" / "yingheng_app_icon.ico"

a = Analysis(
    [str(ROOT / "vision_app.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[*mediapipe_hidden, *dayu_hidden],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="IronJumpVisionTools",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon) if icon.is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="IronJumpVisionTools",
)
