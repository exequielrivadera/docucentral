# Configuración inicial de PyInstaller; requiere pruebas en Windows.
import os
from PyInstaller.utils.hooks import collect_submodules
hiddenimports = collect_submodules("PySide6")
a = Analysis(["main.py"], pathex=[], binaries=[], datas=[("img", "img")] if os.path.isdir("img") else [], hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=["pytest", "IPython", "notebook"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="DocuCentral", debug=False, bootloader_ignore_signals=False, strip=False, upx=True, console=False, disable_windowed_traceback=False)
