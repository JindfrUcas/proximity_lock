# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('config.py', '.'), ('signal_filter.py', '.'), ('activity_monitor.py', '.'), ('remote_auth.py', '.'), ('state_machine.py', '.'), ('screen_control.py', '.'), ('scanner.py', '.'), ('calibration.py', '.'), ('gui_setup.py', '.')],
    hiddenimports=['rumps', 'bleak', 'numpy', 'asyncio', 'bleak.backends.corebluetooth', 'objc', 'CoreBluetooth'],
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
    name='ProximityLock',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ProximityLock',
)
app = BUNDLE(
    coll,
    name='ProximityLock.app',
    icon=None,
    bundle_identifier='com.proximitylock.app',
    info_plist={
        'CFBundleDisplayName': 'ProximityLock',
        'CFBundleName': 'ProximityLock',
        'CFBundleShortVersionString': '0.1.0',
        'CFBundleVersion': '1',
        'LSUIElement': True,
        'NSBluetoothAlwaysUsageDescription': 'ProximityLock 需要使用蓝牙检测 iPhone 是否在电脑附近，以在离开时自动锁屏。',
        'NSAppleEventsUsageDescription': 'ProximityLock 需要控制系统事件来锁定屏幕，并在授权后协助执行解锁。',
    },
)
