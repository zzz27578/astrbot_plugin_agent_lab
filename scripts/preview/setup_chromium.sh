#!/bin/bash
# 在沙盒里准备无头 Chromium，供 preview.js 给 webui 截图。
# 沙盒 /tmp 在多次调用间共享但会话结束清空；每次新会话跑一遍本脚本即可。
# 用法：bash scripts/preview/setup_chromium.sh   （需多次调用累积下载时重复执行本脚本，curl 断点续传）
set -e
PW=/tmp/pw
mkdir -p "$PW"
cd "$PW"

# 1) playwright-core（仅驱动库，不自动下浏览器）
if [ ! -d "$PW/node_modules/playwright-core" ]; then
  PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm i playwright-core@1.49.1 --no-audit --no-fund --loglevel=error
fi
REV=$(node -e 'console.log(require("/tmp/pw/node_modules/playwright-core/browsers.json").browsers.find(b=>b.name==="chromium").revision)')
echo "chromium revision = $REV"

# 2) 下载 chromium（断点续传，单次调用 45s 上限，下不完就再跑一遍本脚本）
URL="https://cdn.playwright.dev/builds/chromium/$REV/chromium-linux.zip"
if [ ! -f "$PW/chromium/chrome-linux/chrome" ]; then
  echo "downloading chromium..."
  curl -sL -C - --max-time 40 -o chromium.zip "$URL" || true
  TOTAL=$(curl -sIL "$URL" | awk 'tolower($1)=="content-length:"{print $2}' | tr -d '\r' | tail -1)
  HAVE=$(stat -c%s chromium.zip 2>/dev/null || echo 0)
  echo "downloaded $HAVE / $TOTAL bytes"
  if [ -n "$TOTAL" ] && [ "$HAVE" -lt "$TOTAL" ]; then
    echo "未下完，请再次运行本脚本继续（断点续传）。"; exit 2
  fi
  unzip -q -o chromium.zip -d chromium
fi
CHROME="$PW/chromium/chrome-linux/chrome"
chmod +x "$CHROME" 2>/dev/null || true

# 3) 补缺失动态库（chromium 通常只缺 libXdamage.so.1；免 root）
mkdir -p "$PW/libs"
if LD_LIBRARY_PATH="$PW/libs" ldd "$CHROME" 2>/dev/null | grep -qi "not found"; then
  mkdir -p "$PW/debs" && cd "$PW/debs"
  for pkg in libxdamage1; do apt-get download "$pkg" 2>/dev/null || true; done
  for d in *.deb; do [ -f "$d" ] && dpkg -x "$d" ex && find ex -name "*.so*" -exec cp {} "$PW/libs/" \; ; done
fi
echo "missing libs after fix:"; LD_LIBRARY_PATH="$PW/libs" ldd "$CHROME" 2>/dev/null | grep -i "not found" || echo "  none"
echo "READY: chrome=$CHROME  libs=$PW/libs"
