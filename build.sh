#!/bin/bash
# ============================================
# ProximityLock 一键构建脚本
# 将 Python 项目打包为 macOS .app 应用
# ============================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="ProximityLock"
DIST_DIR="$SCRIPT_DIR/dist"

echo "🔧 ProximityLock 构建工具"
echo "========================"
echo ""

# 1. 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 未找到 python3，请先安装 Python"
    exit 1
fi

# 2. 安装依赖
echo "📦 安装依赖..."
python3 -m pip install -r "$SCRIPT_DIR/requirements.txt" -q
python3 -m pip install pyinstaller -q

# 3. 构建 .app
echo "🔨 构建 $APP_NAME.app ..."
cd "$SCRIPT_DIR"

rm -rf "$DIST_DIR" "$SCRIPT_DIR/build"
python3 -m PyInstaller ProximityLock.spec --noconfirm --clean

# 4. 检查结果
APP_PATH="$DIST_DIR/$APP_NAME.app"
if [ -d "$APP_PATH" ]; then
    echo ""
    echo "✅ 构建成功！"
    echo "📍 应用位置: $APP_PATH"
    echo ""

    # 5. 询问是否复制到应用程序目录
    read -p "是否复制到 /Applications？(y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        cp -R "$APP_PATH" "/Applications/"
        echo "✅ 已复制到 /Applications/$APP_NAME.app"
        echo "   现在可以从启动台找到它了！"
    fi

    echo ""
    echo "🎉 完成! 双击 $APP_NAME.app 即可启动"
    echo ""
    echo "⚠️ 首次启动注意："
    echo "   1. 如果提示"无法打开"，请右键 → 打开"
    echo "   2. 需要授权蓝牙和辅助功能权限"
    echo "   3. 若仍无反应，请查看 ~/Library/Logs/ProximityLock/ProximityLock.log"
else
    echo "❌ 构建失败"
    exit 1
fi
