#!/usr/bin/env bash
# Remove the application-menu and start-at-login entries.
# The widget's settings in ~/.config/desktop-clock-widget are left untouched.
set -euo pipefail

rm -f "$HOME/.local/share/applications/desktop-clock-widget.desktop"
rm -f "$HOME/.config/autostart/desktop-clock-widget.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
fi

echo "Removed menu and autostart entries."
echo "Settings were kept in $HOME/.config/desktop-clock-widget (delete it to reset)."
