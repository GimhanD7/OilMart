# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

root = Path(SPECPATH)

a = Analysis(
    [str(root / "run_oilmart.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "oilmart" / "*.qss"), "oilmart"),
        (str(root / "assets" / "oilmart.svg"), "assets"),
    ],
    hiddenimports=["sqlalchemy.dialects.sqlite"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="OilMart POS",
    icon=str(root / "assets" / "oilmart.ico"),
    console=False,
    disable_windowed_traceback=False,
)
