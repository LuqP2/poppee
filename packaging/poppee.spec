# -*- mode: python -*-
# PyInstaller spec: `pyinstaller packaging/poppee.spec` (run `python packaging/make_icons.py` first).
#
#   Windows: dist/poppee/{poppee.exe (console CLI), poppee-tray.exe (no console)}
#   macOS:   dist/Poppee.app (menu-bar only app, no Dock icon)
#   Linux:   dist/poppee/poppee
import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
VERSION = re.search(
    r'__version__ = "([^"]+)"', (ROOT / "src" / "poppee" / "__init__.py").read_text()
).group(1)
ICONS = ROOT / "build" / "icons"

if sys.platform == "win32":
    icon = ICONS / "poppee.ico"
elif sys.platform == "darwin":
    icon = ICONS / "poppee.icns"
else:
    icon = None
icon = str(icon) if icon and icon.exists() else None

a = Analysis(
    [str(ROOT / "packaging" / "poppee_entry.py")],
    pathex=[str(ROOT / "src")],
    hiddenimports=[],
    excludes=[
        "pytest",
        "IPython",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtSql",
        "PySide6.QtDesigner",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
    ],
)
pyz = PYZ(a.pure)


def make_exe(name, console):
    return EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=name,
        console=console,
        icon=icon,
        upx=False,
    )


if sys.platform == "darwin":
    exe = make_exe("Poppee", console=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="Poppee", upx=False)
    app = BUNDLE(
        coll,
        name="Poppee.app",
        icon=icon,
        bundle_identifier="io.github.poppee",
        version=VERSION,
        info_plist={
            "CFBundleShortVersionString": VERSION,
            "LSUIElement": True,
            "NSHighResolutionCapable": True,
        },
    )
elif sys.platform == "win32":
    cli = make_exe("poppee", console=True)
    gui = make_exe("poppee-tray", console=False)
    coll = COLLECT(cli, gui, a.binaries, a.datas, name="poppee", upx=False)
else:
    cli = make_exe("poppee", console=True)
    coll = COLLECT(cli, a.binaries, a.datas, name="poppee", upx=False)
