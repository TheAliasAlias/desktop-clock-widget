#!/usr/bin/env bash
# Remove the application-menu and start-at-login entries for both widgets.
# Settings and notes are left untouched.
set -euo pipefail

rm -f "$HOME/.local/share/applications/desktop-clock-widget.desktop"
rm -f "$HOME/.local/share/applications/desktop-notepad-widget.desktop"
rm -f "$HOME/.config/autostart/desktop-clock-widget.desktop"
rm -f "$HOME/.config/autostart/desktop-notepad-widget.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
fi

echo "Removed menu and autostart entries for both widgets."
echo "Clock settings:  $HOME/.config/desktop-clock-widget"
echo "Notepad config:  $HOME/.config/desktop-notepad-widget"
echo "Notepad text:    $HOME/.local/share/desktop-notepad-widget/note.txt"
echo "Delete those paths if you also want to remove your settings and note."
