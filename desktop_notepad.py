#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A small editable desktop notepad for Linux (GTK 3 / PyGObject).

Features
--------
* Frameless, always-on-top window that can be dragged and resized.
* Plain-text note with automatic saving.
* Adjustable font, colours, background alpha, window opacity and corners.
* Remembers position, size and settings; the note lives in a separate file.
* Optional start-at-login entry.

Run with:  python3 desktop_notepad.py
"""

from __future__ import annotations

import json
import os
import sys
import warnings

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

APP_ID = "org.local.DesktopNotepadWidget"

CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), "desktop-notepad-widget")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
AUTOSTART_PATH = os.path.join(
    GLib.get_user_config_dir(), "autostart", "desktop-notepad-widget.desktop"
)
NOTE_DIR = os.path.join(GLib.get_user_data_dir(), "desktop-notepad-widget")
NOTE_PATH = os.path.join(NOTE_DIR, "note.txt")

DEFAULTS = {
    # Geometry. None means "place near the bottom-right of the screen".
    "x": None,
    "y": None,
    "width": 360,
    "height": 300,
    # Appearance.
    "opacity": 0.96,
    "background": "#101118",
    "background_alpha": 0.78,
    "text_color": "rgba(255,255,255,0.94)",
    "corner_radius": 18,
    "font": "Sans 11",
    # Behaviour.
    "always_on_top": True,
    "locked": False,
}


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return cfg
    if isinstance(data, dict):
        for key in DEFAULTS:
            if key in data:
                cfg[key] = data[key]
        # Older configs stored the panel alpha inside the colour itself.
        if "background_alpha" not in data and isinstance(cfg.get("background"), str):
            colour = Gdk.RGBA()
            if colour.parse(cfg["background"]):
                cfg["background_alpha"] = colour.alpha
                cfg["background"] = rgba_to_css(colour, 1.0)
    return cfg


def parse_rgba(value: str, fallback: str = "rgba(255,255,255,1)") -> Gdk.RGBA:
    colour = Gdk.RGBA()
    if not colour.parse(value or ""):
        colour.parse(fallback)
    return colour


def rgba_to_css(colour: Gdk.RGBA, alpha: float | None = None) -> str:
    a = colour.alpha if alpha is None else alpha
    a = max(0.0, min(1.0, float(a)))
    r = int(round(colour.red * 255))
    g = int(round(colour.green * 255))
    b = int(round(colour.blue * 255))
    return f"rgba({r},{g},{b},{a:.3f})"


def css_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def font_css(description: str, fallback: str = "Sans 11") -> str:
    """Turn a Pango font description ("DejaVu Sans Bold 34") into CSS."""
    try:
        desc = Pango.FontDescription.from_string(description or fallback)
    except Exception:
        desc = Pango.FontDescription.from_string(fallback)
    family = desc.get_family() or "Sans"
    size = desc.get_size()
    if size <= 0:
        size = 11 * Pango.SCALE
    parts = [
        f"font-family: {css_quote(family)};",
        f"font-size: {size / Pango.SCALE:.2f}pt;",
    ]
    if desc.get_style() == Pango.Style.ITALIC:
        parts.append("font-style: italic;")
    elif desc.get_style() == Pango.Style.OBLIQUE:
        parts.append("font-style: oblique;")
    if desc.get_variant() == Pango.Variant.SMALL_CAPS:
        parts.append("font-variant: small-caps;")
    try:
        weight = int(desc.get_weight())
    except (TypeError, ValueError):
        weight = 400
    if weight != 400:
        parts.append(f"font-weight: {max(100, min(900, weight))};")
    return " ".join(parts)


def build_css(cfg: dict) -> str:
    text = parse_rgba(cfg.get("text_color", ""), "rgba(255,255,255,0.94)")
    text_css = rgba_to_css(text)
    muted_css = rgba_to_css(text, max(0.0, min(1.0, text.alpha * 0.62)))
    faint_css = rgba_to_css(text, max(0.0, min(1.0, text.alpha * 0.35)))
    background = parse_rgba(cfg.get("background", ""), "#101118")
    try:
        background_alpha = float(cfg.get("background_alpha", 0.78))
    except (TypeError, ValueError):
        background_alpha = 0.78
    background_css = rgba_to_css(background, background_alpha)
    border_css = rgba_to_css(
        text, 0.10 * max(0.0, min(1.0, background_alpha))
    )
    radius = max(0, min(48, int(cfg.get("corner_radius", 18))))

    return f"""
    window#notepad-window {{
        background-color: transparent;
    }}

    #notepad-root {{
        background-color: {background_css};
        border: 1px solid {border_css};
        border-radius: {radius}px;
    }}

    label.note-title {{
        font-family: "Sans";
        font-size: 9pt;
        color: {muted_css};
    }}

    label.note-status {{
        font-family: "Sans";
        font-size: 8pt;
        color: {faint_css};
    }}

    textview#notepad-view,
    textview#notepad-view text {{
        {font_css(cfg.get("font", "Sans 11"))}
        background-color: transparent;
        color: {text_css};
        border-width: 0;
    }}

    textview#notepad-view {{
        padding: 2px;
    }}

    scrolledwindow#notepad-scroll,
    scrolledwindow#notepad-scroll viewport {{
        background-color: transparent;
        border-width: 0;
    }}

    scrolledwindow#notepad-scroll scrollbar {{
        background-color: transparent;
        border-width: 0;
    }}

    scrolledwindow#notepad-scroll scrollbar slider {{
        background-color: {faint_css};
        border-radius: 4px;
        min-width: 6px;
        min-height: 20px;
    }}

    button#settings-gear {{
        background-color: rgba(127,127,127,0.12);
        color: {muted_css};
        border: none;
        border-radius: 11px;
        padding: 1px 5px;
        min-width: 18px;
        min-height: 18px;
        font-size: 12px;
    }}

    button#settings-gear:hover {{
        background-color: rgba(127,127,127,0.26);
        color: {text_css};
    }}
    """


def desktop_quote(value: str) -> str:
    """Quote a value for a .desktop Exec= line."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    escaped = escaped.replace("`", "\\`").replace("$", "\\$")
    return f'"{escaped}"'


# --------------------------------------------------------------------------- #
# Notepad window
# --------------------------------------------------------------------------- #


class NotepadWidget(Gtk.Window):
    def __init__(self, application: Gtk.Application | None = None):
        super().__init__(application=application, title="Desktop Notepad")

        self.cfg = load_config()
        self._save_source: int | None = None
        self._note_save_source: int | None = None
        self._settings_dialog: Gtk.Dialog | None = None
        self._menu: Gtk.Menu | None = None
        self._loading_note = False

        self.set_name("notepad-window")
        self.set_decorated(False)
        self.set_resizable(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_focus_on_map(False)
        self.set_icon_name("accessories-text-editor")
        self.set_app_paintable(True)

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None and screen.is_composited():
            self.set_visual(visual)

        self._style_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            screen,
            self._style_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        self._build_ui()
        self._restore_geometry()
        self._load_note()
        self._apply_all()

        self.connect("configure-event", self._on_configure)
        self.connect("destroy", self._on_destroy)
        self.connect("key-press-event", self._on_key_press)
        self.show_all()

    # ------------------------------------------------------------------ UI --

    def _build_ui(self) -> None:
        grid = Gtk.Grid()
        self.add(grid)

        # Invisible border cells used for resizing (the window has no frame).
        edges = [
            (0, 0, Gdk.WindowEdge.NORTH_WEST, "nw-resize"),
            (1, 0, Gdk.WindowEdge.NORTH, "n-resize"),
            (2, 0, Gdk.WindowEdge.NORTH_EAST, "ne-resize"),
            (0, 1, Gdk.WindowEdge.WEST, "w-resize"),
            (2, 1, Gdk.WindowEdge.EAST, "e-resize"),
            (0, 2, Gdk.WindowEdge.SOUTH_WEST, "sw-resize"),
            (1, 2, Gdk.WindowEdge.SOUTH, "s-resize"),
            (2, 2, Gdk.WindowEdge.SOUTH_EAST, "se-resize"),
        ]
        for column, row, edge, cursor in edges:
            cell = self._make_resize_cell(edge, cursor)
            grid.attach(cell, column, row, 1, 1)

        self._root = Gtk.EventBox()
        self._root.set_name("notepad-root")
        self._root.set_visible_window(True)
        self._root.set_hexpand(True)
        self._root.set_vexpand(True)
        self._root.connect("button-press-event", self._on_root_press)
        grid.attach(self._root, 1, 1, 1, 1)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.set_margin_top(7)
        outer.set_margin_bottom(10)
        outer.set_margin_start(13)
        outer.set_margin_end(13)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header.set_spacing(4)
        title = Gtk.Label(label="Note")
        title.get_style_context().add_class("note-title")
        title.set_xalign(0)
        header.pack_start(title, True, True, 0)

        self._gear = Gtk.Button(label="\u2699")
        self._gear.set_name("settings-gear")
        self._gear.set_relief(Gtk.ReliefStyle.NONE)
        self._gear.set_tooltip_text("Settings  (right-click the header for more)")
        self._gear.set_focus_on_click(False)
        self._gear.set_can_focus(False)
        self._gear.connect("clicked", lambda *_: self._open_settings())
        header.pack_end(self._gear, False, False, 0)
        outer.pack_start(header, False, False, 0)

        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_name("notepad-scroll")
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_shadow_type(Gtk.ShadowType.NONE)
        self._scroll.set_overlay_scrolling(False)
        self._scroll.set_vexpand(True)
        self._scroll.set_margin_top(4)

        self._view = Gtk.TextView()
        self._view.set_name("notepad-view")
        self._view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._view.set_left_margin(8)
        self._view.set_right_margin(8)
        self._view.set_top_margin(4)
        self._view.set_bottom_margin(4)
        self._view.set_pixels_above_lines(2)
        self._view.set_pixels_below_lines(2)
        self._view.set_accepts_tab(True)
        self._view.set_tooltip_text("Click to edit · changes save automatically")
        self._scroll.add(self._view)
        outer.pack_start(self._scroll, True, True, 0)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self._status_label = Gtk.Label(label="Saved")
        self._status_label.get_style_context().add_class("note-status")
        self._status_label.set_xalign(0)
        self._status_label.set_ellipsize(Pango.EllipsizeMode.END)
        footer.pack_start(self._status_label, True, True, 0)
        outer.pack_start(footer, False, False, 0)

        self._root.add(outer)

    def _make_resize_cell(self, edge: Gdk.WindowEdge, cursor_name: str) -> Gtk.EventBox:
        cell = Gtk.EventBox()
        cell.set_visible_window(True)
        cell.set_size_request(6, 6)
        cell.connect("button-press-event", self._on_edge_press, edge)
        cell.connect("realize", self._set_cursor, cursor_name)
        return cell

    def _set_cursor(self, widget: Gtk.Widget, cursor_name: str) -> None:
        window = widget.get_window()
        if window is None:
            return
        try:
            cursor = Gdk.Cursor.new_from_name(widget.get_display(), cursor_name)
            window.set_cursor(cursor)
        except GLib.Error:
            pass

    # ------------------------------------------------------------ behaviour --

    def _restore_geometry(self) -> None:
        width = max(200, int(self.cfg.get("width") or 360))
        height = max(120, int(self.cfg.get("height") or 300))
        self.resize(width, height)

        x, y = self.cfg.get("x"), self.cfg.get("y")
        if x is not None and y is not None:
            if not self._position_is_visible(int(x), int(y), width, height):
                x = y = None
        if x is None or y is None:
            display = Gdk.Display.get_default()
            monitor = display.get_primary_monitor() if display else None
            if monitor is None and display is not None:
                monitor = display.get_monitor(0)
            if monitor is not None:
                area = monitor.get_workarea()
                x = area.x + area.width - width - 32
                y = area.y + area.height - height - 40
            else:
                x, y = 40, 40
        self.cfg["x"], self.cfg["y"] = int(x), int(y)
        self.move(int(x), int(y))

    @staticmethod
    def _position_is_visible(x: int, y: int, width: int, height: int) -> bool:
        """True if at least a 40x40 corner of the window is on some monitor."""
        display = Gdk.Display.get_default()
        if display is None:
            return True
        for index in range(display.get_n_monitors()):
            area = display.get_monitor(index).get_workarea()
            overlap_x = min(x + width, area.x + area.width) - max(x, area.x)
            overlap_y = min(y + height, area.y + area.height) - max(y, area.y)
            if overlap_x >= 40 and overlap_y >= 40:
                return True
        return False

    def _on_root_press(self, _widget: Gtk.Widget, event: Gdk.EventButton) -> bool:
        if self._event_is_from_editing_area(event):
            return False
        if event.button == 1:
            if self.cfg.get("locked"):
                return False
            self.begin_move_drag(
                event.button, int(event.x_root), int(event.y_root), event.time
            )
            return True
        if event.button == 3:
            self._show_menu(event)
            return True
        return False

    def _event_is_from_editing_area(self, event: Gdk.EventButton) -> bool:
        """True for clicks on the text view, scrollbar or settings button."""
        target = Gtk.get_event_widget(event)
        widget = target
        while widget is not None and widget is not self._root:
            if widget in (self._scroll, self._view, self._gear):
                return True
            widget = widget.get_parent()
        return False

    def _on_edge_press(
        self, _widget: Gtk.Widget, event: Gdk.EventButton, edge: Gdk.WindowEdge
    ) -> bool:
        if event.button != 1 or self.cfg.get("locked"):
            return False
        self.begin_resize_drag(
            edge, event.button, int(event.x_root), int(event.y_root), event.time
        )
        return True

    def _on_configure(self, _widget: Gtk.Widget, event: Gdk.EventConfigure) -> bool:
        self.cfg["x"] = int(event.x)
        self.cfg["y"] = int(event.y)
        self.cfg["width"] = int(event.width)
        self.cfg["height"] = int(event.height)
        self._schedule_save()
        return False

    def _on_key_press(self, _widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        control = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        if control and event.keyval in (Gdk.KEY_q, Gdk.KEY_Q):
            self.destroy()
            return True
        if control and event.keyval == Gdk.KEY_comma:
            self._open_settings()
            return True
        if control and event.keyval in (Gdk.KEY_s, Gdk.KEY_S):
            self._save_note()
            return True
        return False

    def _on_destroy(self, _widget: Gtk.Widget) -> None:
        if self._save_source is not None:
            GLib.source_remove(self._save_source)
            self._save_source = None
        if self._note_save_source is not None:
            GLib.source_remove(self._note_save_source)
            self._note_save_source = None
        self._save_note()
        self._save()

    # -------------------------------------------------------------- notepad --

    def _load_note(self) -> None:
        text = ""
        try:
            with open(NOTE_PATH, "r", encoding="utf-8") as fh:
                text = fh.read()
        except FileNotFoundError:
            pass
        except OSError as exc:
            print(f"Notepad: could not read {NOTE_PATH}: {exc}", file=sys.stderr)

        buffer = self._view.get_buffer()
        self._loading_note = True
        buffer.set_text(text)
        buffer.set_modified(False)
        self._loading_note = False
        buffer.connect("changed", self._on_note_changed)
        self._set_status("Saved")

    def _on_note_changed(self, _buffer: Gtk.TextBuffer) -> None:
        if self._loading_note:
            return
        self._set_status("Saving\u2026")
        self._schedule_note_save()

    def _schedule_note_save(self) -> None:
        if self._note_save_source is not None:
            GLib.source_remove(self._note_save_source)
        self._note_save_source = GLib.timeout_add(600, self._note_timeout)

    def _note_timeout(self) -> bool:
        self._note_save_source = None
        self._write_note()
        return False

    def _save_note(self) -> bool:
        if self._note_save_source is not None:
            GLib.source_remove(self._note_save_source)
            self._note_save_source = None
        self._write_note()
        return False

    def _write_note(self) -> None:
        buffer = self._view.get_buffer()
        text = buffer.get_text(
            buffer.get_start_iter(), buffer.get_end_iter(), True
        )
        try:
            os.makedirs(NOTE_DIR, exist_ok=True)
            temporary = NOTE_PATH + ".tmp"
            with open(temporary, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(temporary, NOTE_PATH)
            buffer.set_modified(False)
            self._set_status("Saved")
        except OSError as exc:
            self._set_status("Could not save")
            print(f"Notepad: could not save {NOTE_PATH}: {exc}", file=sys.stderr)

    def _set_status(self, text: str) -> None:
        self._status_label.set_text(text)

    def _clear_note(self) -> None:
        confirm = Gtk.MessageDialog(
            parent=self._settings_dialog or self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Clear this note?",
        )
        confirm.format_secondary_text(
            "All text will be removed from the note file. This cannot be undone."
        )
        response = confirm.run()
        confirm.destroy()
        if response != Gtk.ResponseType.OK:
            return

        self._view.get_buffer().set_text("")
        self._save_note()
        self._view.grab_focus()

    # ------------------------------------------------------------- appearance --

    def _apply_all(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            self.set_opacity(max(0.2, min(1.0, float(self.cfg.get("opacity", 0.96)))))
        self.set_keep_above(bool(self.cfg.get("always_on_top", True)))

        css = build_css(self.cfg)
        try:
            self._style_provider.load_from_data(css.encode("utf-8"))
        except GLib.Error as exc:  # pragma: no cover - only if CSS is malformed
            print(f"Notepad: could not apply styles: {exc}", file=sys.stderr)

    def _set_cfg(self, key: str, value) -> None:
        self.cfg[key] = value
        self._apply_all()
        self._schedule_save()

    # ---------------------------------------------------------------- saving --

    def _schedule_save(self) -> None:
        if self._save_source is not None:
            GLib.source_remove(self._save_source)
        self._save_source = GLib.timeout_add(600, self._save)

    def _save(self) -> bool:
        self._save_source = None
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            temporary = CONFIG_PATH + ".tmp"
            with open(temporary, "w", encoding="utf-8") as fh:
                json.dump(self.cfg, fh, indent=2, sort_keys=True)
                fh.write("\n")
            os.replace(temporary, CONFIG_PATH)
        except OSError as exc:
            print(f"Notepad: could not save settings: {exc}", file=sys.stderr)
        return False

    # -------------------------------------------------------------- autostart --

    def _autostart_enabled(self) -> bool:
        return os.path.exists(AUTOSTART_PATH)

    def _set_autostart(self, enabled: bool) -> None:
        try:
            if enabled:
                os.makedirs(os.path.dirname(AUTOSTART_PATH), exist_ok=True)
                script = os.path.abspath(__file__)
                content = (
                    "[Desktop Entry]\n"
                    "Type=Application\n"
                    "Name=Desktop Notepad\n"
                    "Comment=Editable desktop notepad widget\n"
                    f"Exec={desktop_quote(sys.executable)} {desktop_quote(script)}\n"
                    "Icon=accessories-text-editor\n"
                    "Terminal=false\n"
                    "Categories=Utility;TextEditor;\n"
                    "X-GNOME-Autostart-enabled=true\n"
                    "StartupNotify=false\n"
                )
                temporary = AUTOSTART_PATH + ".tmp"
                with open(temporary, "w", encoding="utf-8") as fh:
                    fh.write(content)
                os.replace(temporary, AUTOSTART_PATH)
                os.chmod(AUTOSTART_PATH, 0o644)
            elif os.path.exists(AUTOSTART_PATH):
                os.remove(AUTOSTART_PATH)
        except OSError as exc:
            print(f"Notepad: could not change autostart: {exc}", file=sys.stderr)

    # ------------------------------------------------------------------ menu --

    def _show_menu(self, event: Gdk.EventButton) -> None:
        menu = Gtk.Menu()
        menu.attach_to_widget(self, None)

        settings = Gtk.MenuItem(label="Settings\u2026")
        settings.connect("activate", lambda *_: self._open_settings())
        menu.append(settings)

        clear = Gtk.MenuItem(label="Clear note\u2026")
        clear.connect("activate", lambda *_: self._clear_note())
        menu.append(clear)

        menu.append(Gtk.SeparatorMenuItem())

        item = Gtk.CheckMenuItem(label="Always on top")
        item.set_active(bool(self.cfg.get("always_on_top", True)))
        item.connect(
            "toggled", lambda widget: self._set_cfg("always_on_top", widget.get_active())
        )
        menu.append(item)

        item = Gtk.CheckMenuItem(label="Lock position and size")
        item.set_active(bool(self.cfg.get("locked", False)))
        item.connect("toggled", lambda widget: self._set_cfg("locked", widget.get_active()))
        menu.append(item)

        item = Gtk.CheckMenuItem(label="Start at login")
        item.set_active(self._autostart_enabled())
        item.connect("toggled", lambda widget: self._set_autostart(widget.get_active()))
        menu.append(item)

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda *_: self.destroy())
        menu.append(quit_item)

        menu.show_all()
        self._menu = menu
        menu.popup_at_pointer(event)

    # -------------------------------------------------------------- settings --

    def _open_settings(self) -> None:
        if self._settings_dialog is not None:
            self._settings_dialog.present()
            return

        dialog = Gtk.Dialog(title="Notepad Settings", parent=self, modal=True)
        dialog.set_default_size(470, 400)
        dialog.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        dialog.add_button("Close", Gtk.ResponseType.CLOSE)
        dialog.set_default_response(Gtk.ResponseType.CLOSE)

        notebook = Gtk.Notebook()
        notebook.set_border_width(8)
        notebook.append_page(self._page_text(dialog), Gtk.Label(label="Text"))
        notebook.append_page(self._page_appearance(), Gtk.Label(label="Appearance"))
        notebook.append_page(self._page_behaviour(dialog), Gtk.Label(label="Behaviour"))
        dialog.get_content_area().add(notebook)

        dialog.connect("response", lambda d, _r: d.destroy())
        dialog.connect("destroy", self._on_settings_destroyed)
        self._settings_dialog = dialog
        dialog.show_all()

    def _on_settings_destroyed(self, _dialog: Gtk.Widget) -> None:
        self._settings_dialog = None

    def _make_page(self) -> Gtk.Grid:
        grid = Gtk.Grid()
        grid.set_row_spacing(10)
        grid.set_column_spacing(12)
        grid.set_margin_top(16)
        grid.set_margin_bottom(16)
        grid.set_margin_start(16)
        grid.set_margin_end(16)
        return grid

    def _add_row(self, grid: Gtk.Grid, row: int, label: str, widget: Gtk.Widget) -> None:
        text = Gtk.Label(label=label, xalign=0, valign=Gtk.Align.CENTER)
        grid.attach(text, 0, row, 1, 1)
        widget.set_hexpand(True)
        grid.attach(widget, 1, row, 1, 1)

    def _page_text(self, dialog: Gtk.Dialog) -> Gtk.Grid:
        grid = self._make_page()

        self._add_row(grid, 0, "Font", self._make_font_button("Notepad font", "font"))

        note_file = Gtk.Label(
            xalign=0,
            wrap=True,
            selectable=True,
            label=NOTE_PATH,
        )
        note_file.get_style_context().add_class("dim-label")
        note_file.set_tooltip_text("The note is a plain UTF-8 text file")
        grid.attach(note_file, 0, 1, 2, 1)

        clear = Gtk.Button(label="Clear note\u2026")
        clear.set_halign(Gtk.Align.START)
        clear.connect("clicked", lambda *_: self._clear_note())
        grid.attach(clear, 0, 2, 2, 1)

        hint = Gtk.Label(
            xalign=0,
            wrap=True,
            label=(
                "Changes are saved automatically, about half a second after you "
                "stop typing. Ctrl+S saves immediately."
            ),
        )
        hint.get_style_context().add_class("dim-label")
        grid.attach(hint, 0, 3, 2, 1)
        return grid

    def _page_appearance(self) -> Gtk.Grid:
        grid = self._make_page()

        self._add_row(
            grid, 0, "Text colour", self._make_colour_button("text_color")
        )
        self._add_row(
            grid,
            1,
            "Background",
            self._make_colour_button("background", use_alpha=False),
        )

        alpha_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        alpha_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        alpha_scale.set_value(float(self.cfg.get("background_alpha", 0.78)) * 100)
        alpha_scale.set_draw_value(False)
        alpha_scale.set_hexpand(True)
        alpha_scale.set_tooltip_text(
            "0% is fully transparent, 100% is solid; this affects only the panel"
        )
        alpha_label = Gtk.Label(
            label=f"{int(float(self.cfg.get('background_alpha', 0.78)) * 100)}%"
        )

        def on_alpha(widget: Gtk.Scale) -> None:
            value = int(round(widget.get_value()))
            alpha_label.set_text(f"{value}%")
            self._set_cfg("background_alpha", value / 100.0)

        alpha_scale.connect("value-changed", on_alpha)
        alpha_box.pack_start(alpha_scale, True, True, 0)
        alpha_box.pack_end(alpha_label, False, False, 0)
        self._add_row(grid, 2, "Background alpha", alpha_box)

        opacity_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        opacity_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 20, 100, 1
        )
        opacity_scale.set_value(float(self.cfg.get("opacity", 0.96)) * 100)
        opacity_scale.set_draw_value(False)
        opacity_scale.set_hexpand(True)
        opacity_label = Gtk.Label(label=f"{int(float(self.cfg.get('opacity', 0.96)) * 100)}%")

        def on_opacity(widget: Gtk.Scale) -> None:
            value = int(round(widget.get_value()))
            opacity_label.set_text(f"{value}%")
            self._set_cfg("opacity", value / 100.0)

        opacity_scale.connect("value-changed", on_opacity)
        opacity_box.pack_start(opacity_scale, True, True, 0)
        opacity_box.pack_end(opacity_label, False, False, 0)
        self._add_row(grid, 3, "Window opacity", opacity_box)

        radius_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        radius_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 40, 1)
        radius_scale.set_value(float(self.cfg.get("corner_radius", 18)))
        radius_scale.set_draw_value(False)
        radius_scale.set_hexpand(True)
        radius_label = Gtk.Label(label=f"{int(self.cfg.get('corner_radius', 18))} px")

        def on_radius(widget: Gtk.Scale) -> None:
            value = int(round(widget.get_value()))
            radius_label.set_text(f"{value} px")
            self._set_cfg("corner_radius", value)

        radius_scale.connect("value-changed", on_radius)
        radius_box.pack_start(radius_scale, True, True, 0)
        radius_box.pack_end(radius_label, False, False, 0)
        self._add_row(grid, 4, "Corner radius", radius_box)

        hint = Gtk.Label(
            xalign=0,
            wrap=True,
            label=(
                "Background alpha controls how much of the desktop shows through "
                "the panel. Window opacity fades the whole widget, text included."
            ),
        )
        hint.get_style_context().add_class("dim-label")
        grid.attach(hint, 0, 5, 2, 1)
        return grid

    def _page_behaviour(self, dialog: Gtk.Dialog) -> Gtk.Grid:
        grid = self._make_page()

        on_top = Gtk.CheckButton(label="Always on top")
        on_top.set_active(bool(self.cfg.get("always_on_top", True)))
        on_top.connect(
            "toggled",
            lambda widget: self._set_cfg("always_on_top", widget.get_active()),
        )
        grid.attach(on_top, 0, 0, 2, 1)

        locked = Gtk.CheckButton(label="Lock position and size")
        locked.set_active(bool(self.cfg.get("locked", False)))
        locked.set_tooltip_text("Unlock to drag or resize the notepad again")
        locked.connect(
            "toggled", lambda widget: self._set_cfg("locked", widget.get_active())
        )
        grid.attach(locked, 0, 1, 2, 1)

        autostart = Gtk.CheckButton(label="Start automatically when I log in")
        autostart.set_active(self._autostart_enabled())
        autostart.connect(
            "toggled", lambda widget: self._set_autostart(widget.get_active())
        )
        grid.attach(autostart, 0, 2, 2, 1)

        grid.attach(Gtk.Separator(), 0, 3, 2, 1)

        reset = Gtk.Button(label="Restore default settings")
        reset.set_halign(Gtk.Align.START)
        reset.connect("clicked", lambda *_: self._confirm_reset(dialog))
        grid.attach(reset, 0, 4, 2, 1)

        hints = Gtk.Label(
            xalign=0,
            wrap=True,
            label=(
                "Drag the \u201cNote\u201d header or the outer padding to move the "
                "notepad. Drag an edge or corner to resize it. Right-click the "
                "header for options. Ctrl+, opens settings, Ctrl+S saves, "
                "Ctrl+Q quits."
            ),
        )
        hints.get_style_context().add_class("dim-label")
        grid.attach(hints, 0, 5, 2, 1)
        return grid

    def _make_font_button(self, title: str, key: str) -> Gtk.Button:
        button = Gtk.Button(label=str(self.cfg.get(key, "")))
        button.set_halign(Gtk.Align.START)
        button.set_tooltip_text("Choose a font")

        def choose(widget: Gtk.Button) -> None:
            chooser = Gtk.FontChooserDialog(
                title=title, parent=self._settings_dialog or self
            )
            chooser.set_font(str(self.cfg.get(key, "")))
            chooser.add_button("Cancel", Gtk.ResponseType.CANCEL)
            chooser.add_button("Select", Gtk.ResponseType.OK)
            chooser.set_default_response(Gtk.ResponseType.OK)

            def on_response(chooser_dialog: Gtk.Dialog, response: int) -> None:
                if response == Gtk.ResponseType.OK:
                    selected = chooser_dialog.get_font()
                    if selected:
                        self._set_cfg(key, selected)
                        widget.set_label(selected)
                chooser_dialog.destroy()

            chooser.connect("response", on_response)
            chooser.show_all()

        button.connect("clicked", choose)
        return button

    def _make_colour_button(self, key: str, use_alpha: bool = True) -> Gtk.ColorButton:
        button = Gtk.ColorButton()
        button.set_property("use-alpha", use_alpha)
        button.set_rgba(parse_rgba(str(self.cfg.get(key, "")), "rgba(255,255,255,1)"))
        button.set_title("Choose a colour")

        def on_colour_set(widget: Gtk.ColorButton) -> None:
            colour = widget.get_rgba()
            self._set_cfg(key, rgba_to_css(colour, colour.alpha if use_alpha else 1.0))

        button.connect("color-set", on_colour_set)
        return button

    def _confirm_reset(self, settings_dialog: Gtk.Dialog) -> None:
        confirm = Gtk.MessageDialog(
            parent=settings_dialog,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Restore default settings?",
        )
        confirm.format_secondary_text(
            "Font, colours and appearance will be reset. The note text, position, "
            "size and the start-at-login setting are kept."
        )
        response = confirm.run()
        confirm.destroy()
        if response != Gtk.ResponseType.OK:
            return

        keep = {key: self.cfg.get(key) for key in ("x", "y", "width", "height")}
        self.cfg = dict(DEFAULTS)
        self.cfg.update(keep)
        self._apply_all()
        self._save()

        settings_dialog.destroy()
        GLib.idle_add(self._open_settings)


# --------------------------------------------------------------------------- #
# Application entry point
# --------------------------------------------------------------------------- #


def main(argv: list[str]) -> int:
    application = Gtk.Application(
        application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE
    )

    def on_activate(app: Gtk.Application) -> None:
        window = app.get_active_window()
        if window is None:
            # NotepadWidget shows itself; presenting here would steal focus.
            window = NotepadWidget(application=app)
        else:
            window.present()

    application.connect("activate", on_activate)
    return application.run(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
