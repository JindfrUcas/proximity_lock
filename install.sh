#!/bin/bash
# ============================================
# ProximityLock 一键安装脚本
# 适用于完全没有编程经验的用户
# ============================================

echo ""
echo "  ╔══════════════════════════════════╗"
echo "  ║   🔒 ProximityLock 安装程序      ║"
echo "  ║    iPhone 距离感应自动锁屏      ║"
echo "  ╚══════════════════════════════════╝"
echo ""

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 检查 Homebrew
if ! command -v brew &> /dev/null; then
    echo "📦 正在安装 Homebrew（macOS 包管理器）..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "🐍 正在安装 Python..."
    brew install python3
fi

# 安装 Python 依赖
echo "📦 正在安装依赖..."
pip3 install -r "$SCRIPT_DIR/requirements.txt" -q 2>/dev/null || \
    pip install -r "$SCRIPT_DIR/requirements.txt" -q

# 安装 PyInstaller
echo "🔧 正在安装打包工具..."
pip3 install pyinstaller -q 2>/dev/null || pip install pyinstaller -q

# 构建应用
echo ""
echo "🔨 正在构建应用程序（可能需要 1-2 分钟）..."
echo ""

cd "$SCRIPT_DIR"
pyinstaller \
    --name "ProximityLock" \
    --windowed \
    --onedir \
    --noconfirm \
    --clean \
    --add-data "config.py:." \
    --add-data "signal_filter.py:." \
    --add-data "activity_monitor.py:." \
    --add-data "remote_auth.py:." \
    --add-data "state_machine.py:." \
    --add-data "screen_control.py:." \
    --add-data "scanner.py:." \
    --add-data "calibration.py:." \
    --add-data "gui_setup.py:." \
    --hidden-import rumps \
    --hidden-import bleak \
    --hidden-import numpy \
    --hidden-import asyncio \
    --osx-bundle-identifier "com.proximitylock.app" \
    main.py 2>&1 | grep -E "(Building|Completed|ERROR)" || true

# 检查构建结果
APP_PATH="$SCRIPT_DIR/dist/ProximityLock.app"

if [ -d "$APP_PATH" ]; then
    echo ""
    echo "✅ 构建成功！"
    echo ""

    # 复制到应用程序
    echo "📂 正在安装到「应用程序」文件夹..."
    cp -R "$APP_PATH" "/Applications/" 2>/dev/null && {
        echo "✅ 安装完成！"
        echo ""
        echo "  ╔═══════════════════════════════════════╗"
        echo "  ║  🎉 安装成功!                         ║"
        echo "  ║                                       ║"
        echo "  ║  在启动台找到 ProximityLock 即可使用   ║"
        echo "  ║  首次启动会弹出设置向导                ║"
        echo "  ║                                       ║"
        echo "  ║  ⚠️ 如果提示"无法打开"               ║"
        echo "  ║     请右键点击 → 选择"打开"           ║"
        echo "  ╚═══════════════════════════════════════╝"
        echo ""
    } || {
        echo "⚠️ 无法写入 /Applications，可能需要管理员权限"
        echo "   应用在这里: $APP_PATH"
        echo "   你可以手动拖到「应用程序」文件夹"
    }

    # 询问是否立即打开
    read -p "是否现在就打开 ProximityLock？(y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        open "/Applications/ProximityLock.app" 2>/dev/null || open "$APP_PATH"
    fi
else
    echo ""
    echo "❌ 构建失败，请检查错误信息"
    echo "   也可以直接用命令行模式运行："
    echo "   cd $SCRIPT_DIR && python3 main.py"
fi
