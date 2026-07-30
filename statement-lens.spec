# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Statement Lens desktop app.

Build (on Windows — PyInstaller cannot cross-compile a .exe from macOS):

    pip install -r requirements-app.txt
    pyinstaller statement-lens.spec

Produces dist/StatementLens.exe (one-file, windowed).  The Inno Setup script
in installer/ then wraps that exe into StatementLens-Setup.exe.
"""

from PyInstaller.utils.hooks import collect_all

# Bundle the webview backends and the PDF stack with their data files, so the
# frozen exe has everything it needs with no site-packages present.
datas, binaries, hiddenimports = [], [], []
for pkg in ("webview", "pdfplumber", "pdfminer", "openpyxl",
            "msoffcrypto", "olefile"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# The static upload page is loaded by URL at runtime -> must ship inside the exe.
datas += [("ui/upload.html", "ui")]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="StatementLens",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # windowed app — no console window
    disable_windowed_traceback=False,
    icon="installer/app.ico" if __import__("os").path.exists("installer/app.ico") else None,
)
