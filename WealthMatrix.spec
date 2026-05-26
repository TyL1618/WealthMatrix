# -*- mode: python ; coding: utf-8 -*-
# WealthMatrix v4.1 - PyInstaller spec (單一 EXE 版本)
# 用法: pyinstaller WealthMatrix.spec

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
        'wealthmatrix',
        'wealthmatrix.app',
        'wealthmatrix.theme',
        'wealthmatrix.core',
        'wealthmatrix.core.data_manager',
        'wealthmatrix.ui',
        'wealthmatrix.ui.dashboard',
        'wealthmatrix.ui.cashflow',
        'wealthmatrix.ui.charts',
        'wealthmatrix.ui.dialogs',
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
        'cryptography',
        'cryptography.fernet',
        'cryptography.hazmat.primitives',
        'cryptography.hazmat.backends',
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
    a.binaries,
    a.zipfiles,
    a.datas,
    name='WealthMatrix',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
    version_file=None,
)
