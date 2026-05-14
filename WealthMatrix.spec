# -*- mode: python ; coding: utf-8 -*-
# WealthMatrix v4.0 - PyInstaller spec (單一 EXE 版本)
# 用法: pyinstaller WealthMatrix.spec

from PyInstaller.utils.hooks import collect_data_files
import os
import certifi

block_cipher = None

_icon = 'icon.ico' if os.path.exists('icon.ico') else None

_datas = [
    (certifi.where(), 'certifi'),
]
if _icon:
    _datas.append(('icon.ico', '.'))

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=_datas,
    hiddenimports=[
        'dashboard',
        'cashflow',
        'charts',
        'dialogs',
        'styles',
        'data_manager',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.sip',
        'requests',
        'urllib3',
        'urllib3.util',
        'urllib3.util.retry',
        'urllib3.util.timeout',
        'urllib3.util.url',
        'urllib3.contrib',
        'certifi',
        'charset_normalizer',
        'idna',
        'email',
        'email.message',
        'email.parser',
        'email.feedparser',
        'email.errors',
        'email.charset',
        'email.encoders',
        'email.header',
        'email.utils',
        'http',
        'http.client',
        'http.cookiejar',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
        'tkinter',
        'unittest',
        'xmlrpc',
        'pydoc',
        'doctest',
        'difflib',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher,
)

# ==================== 單一 EXE (onefile) ====================
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,      # 重要：加入 binaries
    a.zipfiles,
    a.datas,         # 重要：加入 datas
    name='WealthMatrix',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,        # onefile 模式建議開啟 UPX 壓縮
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
    version_file=None,
    # onefile 專用選項（可選）
    onefile=True,    # 明確標示
)