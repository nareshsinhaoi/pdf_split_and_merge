# pdf_merger.spec
# Build with: pyinstaller pdf_merger.spec --noconfirm

import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# --- Hidden imports ---------------------------------------------------------
hiddenimports = [
    "waitress",
    "pymongo",
    "gridfs",
    "bson",
    "dotenv",
    "fitz",          # PyMuPDF
    "pymupdf",
    "flask",
    "jinja2",
    "werkzeug",
]

# PyMuPDF ships compiled DLLs; collect them all
datas, binaries, hiddenimports_pymupdf = collect_all("pymupdf")
hiddenimports += hiddenimports_pymupdf
datas_pymupdf, binaries_pymupdf, _ = collect_all("fitz")
datas += datas_pymupdf
binaries += binaries_pymupdf

# --- Static/template assets -------------------------------------------------
datas += [
    ("app/templates", "app/templates"),
    ("app/static", "app/static"),
]

# --- Analysis ---------------------------------------------------------------
a = Analysis(
    ["main.py"],
    pathex=[os.path.abspath(".")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "IPython",
        "pytest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# --- One-file executable ----------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="PDFMerger",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # UPX can corrupt PyMuPDF DLLs — keep off
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,            # keep console so users see logs; set False for silent
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="app/static/icon.ico",   # optional; remove if you have no icon
)