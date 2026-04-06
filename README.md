# ProximityLock

> iPhone 距离感应离开锁屏 macOS 菜单栏应用

当前版本默认只做“离开自动锁屏”。
当本地键盘/鼠标连续无操作 5 秒后，应用才会开始快速检测 iPhone 的 BLE RSSI；如果信号超出设定范围，就认为你已经离开并执行锁屏。回来时不会自动亮屏。

如果你愿意额外配置，还可以启用“远程授权解锁”：
朋友在电脑旁但你的手机不在时，可以在同一局域网里打开授权页，输入你发给他的 6 位动态码，程序会从 Keychain 取出已保存的 Mac 登录密码帮他解锁。

## 快速开始

### 1. 初始设置

```bash
# 第 1 步：扫描并选择你的 iPhone
python main.py --discover

# 第 2 步：校准 RSSI 阈值（推荐）
python main.py --calibrate

# 第 3 步：配置远程授权解锁（可选）
python main.py --setup-remote-unlock
```

### 2. 启动

```bash
# 安装依赖
pip install -r requirements.txt

# 菜单栏模式
python main.py

# 命令行模式（调试用）
python main.py --cli
```

## 当前检测逻辑

1. 正常使用电脑时，不持续扫描蓝牙。
2. 本地空闲达到 `idle_grace_seconds` 后，进入快速 BLE 检测。
3. 如果滤波后的 RSSI 持续低于 `lock_rssi`，或者空闲检测期间持续收不到信号，就锁屏。
4. 检测到本地重新有操作后，只做静默复位，不主动亮屏。

## 远程授权解锁

1. 先运行 `python main.py --setup-remote-unlock`。
2. 按提示把生成的 `TOTP` 密钥导入认证器应用。
3. 程序会打印授权地址，例如 `http://你的Mac.local:8765`。
4. 当电脑已经锁屏时，朋友在同一局域网里打开该地址，输入你发给他的 6 位动态码。
5. 验证通过后，电脑会临时放行一段时间，避免因为手机不在而再次立刻锁回去。

## 项目结构

```text
proximity_lock/
├── main.py              # 入口 + 菜单栏应用
├── activity_monitor.py  # macOS 本地空闲检测
├── config.py            # 配置管理
├── remote_auth.py       # 一次性动态码 + 远程授权页
├── scanner.py           # BLE 扫描（bleak）
├── signal_filter.py     # RSSI 滤波 + 异常值检测
├── state_machine.py     # 只负责“离开锁屏”的状态机
├── screen_control.py    # macOS 锁屏/解锁/通知
├── calibration.py       # 阈值校准向导
└── gui_setup.py         # GUI 设置向导
```

## 关键配置

配置文件位于 `~/.proximity_lock/config.json`。

```json
{
  "idle_grace_seconds": 5.0,
  "idle_scan_window": 0.35,
  "idle_scan_pause": 0.05,
  "lock_rssi": -72,
  "lock_confirm_seconds": 0.6,
  "signal_lost_timeout": 1.2,
  "remote_unlock_enabled": false,
  "remote_unlock_port": 8765,
  "remote_unlock_session_minutes": 15
}
```

## 注意事项

1. 首次运行需要授权蓝牙权限。
2. 如果启用远程授权解锁，还需要先把 Mac 登录密码保存到 Keychain，并授予辅助功能权限。
3. 远程授权页默认监听局域网端口 `8765`，建议只在可信局域网中使用。
4. 锁屏命令依赖 macOS，本项目主要面向 macOS 使用。
5. BLE 广播和系统扫描本身有物理延迟，因此“毫秒级”更准确地说是“接近实时的亚秒级响应”。

## 打包

需要在 macOS 上执行：

```bash
pip install -r requirements.txt
./build.sh
```

当前仓库里的 `.app` 目录仅代表历史构建产物，建议每次发布前在目标 Mac 上重新打包。
如果双击 `.app` 没有明显反应，请查看日志文件：

```bash
tail -n 100 ~/Library/Logs/ProximityLock/ProximityLock.log
```
