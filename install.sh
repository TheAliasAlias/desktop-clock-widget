#!/usr/bin/env bash
# Install the desktop widget: application-menu entry + start-at-login entry.
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP="$HERE/desktop_clock.py"
PYTHON="$(command -v python3 || true)"

if [[ -z "$PYTHON" ]]; then
    echo "python3 was not found. Install Python 3 first." >&2
    exit 1
fi

chmod +x "$APP"

APPS_DIR="$HOME/.local/share/applications"
AUTOSTART_DIR="$HOME/.config/autostart"
mkdir -p "$APPS_DIR" "$AUTOSTART_DIR"

MENU_FILE="$APPS_DIR/desktop-clock-widget.desktop"
AUTOSTART_FILE="$AUTOSTART_DIR/desktop-clock-widget.desktop"

cat > "$MENU_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Desktop Clock & Calendar
Comment=Clock and calendar widget
Exec="$PYTHON" "$APP"
Icon=preferences-system-time
Terminal=false
Categories=Utility;Clock;
StartupNotify=false
EOF

cat > "$AUTOSTART_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Desktop Clock & Calendar
Comment=Clock and calendar widget
Exec="$PYTHON" "$APP"
Icon=preferences-system-time
Terminal=false
Categories=Utility;Clock;
X-GNOME-Autostart-enabled=true
StartupNotify=false
EOF

chmod 644 "$MENU_FILE" "$AUTOSTART_FILE"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi

echo "Installed:"
echo "  menu entry   $MENU_FILE"
echo "  autostart    $AUTOSTART_FILE"
echo
echo "Launch it now with:"
echo "  python3 \"$APP\""
