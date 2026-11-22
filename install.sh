#!/usr/bin/env bash
# Install the desktop widgets: application-menu entries + start-at-login entries.
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$(command -v python3 || true)"

if [[ -z "$PYTHON" ]]; then
    echo "python3 was not found. Install Python 3 first." >&2
    exit 1
fi

APPS_DIR="$HOME/.local/share/applications"
AUTOSTART_DIR="$HOME/.config/autostart"
mkdir -p "$APPS_DIR" "$AUTOSTART_DIR"

install_widget() {
    local slug="$1" name="$2" script="$3" icon="$4" comment="$5" categories="$6"
    local app="$HERE/$script"
    local menu_file="$APPS_DIR/$slug.desktop"
    local autostart_file="$AUTOSTART_DIR/$slug.desktop"

    chmod +x "$app"

    cat > "$menu_file" <<EOF
[Desktop Entry]
Type=Application
Name=$name
Comment=$comment
Exec="$PYTHON" "$app"
Icon=$icon
Terminal=false
Categories=$categories
StartupNotify=false
EOF

    cat > "$autostart_file" <<EOF
[Desktop Entry]
Type=Application
Name=$name
Comment=$comment
Exec="$PYTHON" "$app"
Icon=$icon
Terminal=false
Categories=$categories
X-GNOME-Autostart-enabled=true
StartupNotify=false
EOF

    chmod 644 "$menu_file" "$autostart_file"
    echo "  $name -> $menu_file"
    echo "  $name -> $autostart_file"
}

echo "Installed:"
install_widget \
    "desktop-clock-widget" \
    "Desktop Clock & Calendar" \
    "desktop_clock.py" \
    "preferences-system-time" \
    "Clock, calendar and weather widget" \
    "Utility;Clock;"

install_widget \
    "desktop-notepad-widget" \
    "Desktop Notepad" \
    "desktop_notepad.py" \
    "accessories-text-editor" \
    "Editable desktop notepad widget" \
    "Utility;TextEditor;"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi

echo
echo "Launch them now with:"
echo "  python3 \"$HERE/desktop_clock.py\""
echo "  python3 \"$HERE/desktop_notepad.py\""
