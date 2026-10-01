#!/bin/bash
# Xcode Behavior: Settings → Behaviors → + → Run → trỏ tới file này.
# Đọc workspace và scheme đang mở, rồi in lệnh xcodebuild.
# Nếu có thêm đối số, gửi câu đó cho skai chat.

set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
SKAI="$HERE/skai.py"

if ! command -v osascript >/dev/null 2>&1; then
  echo "Behavior này chạy trên macOS, khi Xcode đang mở workspace." >&2
  exit 2
fi

INFO="$(osascript <<'APPLESCRIPT'
tell application "Xcode"
  if not (exists active workspace document) then error "Xcode không có workspace đang mở"
  tell active workspace document
    set wsPath to path
    set schemeName to ""
    try
      set schemeName to name of active scheme
    end try
  end tell
end tell
return wsPath & linefeed & schemeName
APPLESCRIPT
)" || {
  echo "Không đọc được workspace từ Xcode. Hãy mở project rồi chạy lại." >&2
  exit 2
}

WS="$(printf '%s\n' "$INFO" | sed -n '1p')"
SCHEME="$(printf '%s\n' "$INFO" | sed -n '2p')"
ROOT="$(cd "$(dirname "$WS")" && pwd)"

if [[ "$WS" == *.xcworkspace ]]; then
  export XCODE_WORKSPACE="$WS"
elif [[ "$WS" == *.xcodeproj ]]; then
  export XCODE_PROJECT="$WS"
fi
if [[ -n "$SCHEME" ]]; then
  export XCODE_SCHEME="$SCHEME"
fi

if [[ "$#" -gt 0 ]]; then
  exec python3 "$SKAI" --root "$ROOT" chat "$*"
fi
exec python3 "$SKAI" --root "$ROOT" xcode show
