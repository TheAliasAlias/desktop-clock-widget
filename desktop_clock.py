#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A small desktop clock and calendar widget for Linux (GTK 3 / PyGObject).

Features
--------
* Frameless, always-on-top window that can be dragged and resized.
* Live clock, date, current weather and month calendar.
* Adjustable fonts, colours, background alpha, window opacity and corner radius.
* Optional location-based weather (automatic or by city) with °C/°F units.
* Remembers position, size and settings in a JSON config.
* Optional start-at-login entry.

Run with:  python3 desktop_clock.py
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
import warnings
from datetime import datetime

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")

from gi.repository import Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

APP_ID = "org.local.DesktopClockWidget"

CONFIG_DIR = os.path.join(GLib.get_user_config_dir(), "desktop-clock-widget")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
AUTOSTART_PATH = os.path.join(
    GLib.get_user_config_dir(), "autostart", "desktop-clock-widget.desktop"
)

DEFAULTS = {
    # Geometry (None means "place near the top-right of the screen").
    "x": None,
    "y": None,
    "width": 320,
    "height": 400,
    # Appearance.
    "opacity": 0.96,
    "background": "#101118",
    "background_alpha": 0.78,
    "text_color": "rgba(255,255,255,0.94)",
    "corner_radius": 18,
    # Content.
    "clock_format": "%H:%M",
    "date_format": "%A, %d %B %Y",
    "clock_font": "Sans Bold 34",
    "date_font": "Sans 11",
    "calendar_font": "Sans 10",
    "show_date": True,
    "show_calendar": True,
    "week_numbers": False,
    # Weather.
    "show_weather": True,
    "weather_place": "",
    "weather_lat": None,
    "weather_lon": None,
    "weather_units": "celsius",
    "weather_refresh_minutes": 30,
    "weather_font": "Sans 10",
    "weather_temp": None,
    "weather_desc": "",
    "weather_cached_units": "celsius",
    "weather_fetched": None,
    # Behaviour.
    "always_on_top": True,
    "locked": False,
}

CLOCK_PRESETS = [
    ("24-hour  ·  14:05", "%H:%M"),
    ("24-hour with seconds  ·  14:05:09", "%H:%M:%S"),
    ("12-hour  ·  2:05 PM", "%I:%M %p"),
    ("12-hour with seconds  ·  2:05:09 PM", "%I:%M:%S %p"),
    ("Custom", None),
]

DATE_PRESETS = [
    ("Saturday, 21 November 2026", "%A, %d %B %Y"),
    ("Sat 21 Nov 2026", "%a %d %b %Y"),
    ("21/11/2026", "%d/%m/%Y"),
    ("November 21, 2026", "%B %d, %Y"),
    ("Custom", None),
]


def weather_description(code: int) -> str:
    """Short description for a WMO weather interpretation code."""
    if code == 0:
        return "Clear"
    if code == 1:
        return "Mostly clear"
    if code == 2:
        return "Partly cloudy"
    if code == 3:
        return "Overcast"
    if code in (45, 48):
        return "Fog"
    if code in (51, 53, 55, 56, 57):
        return "Drizzle"
    if code in (61, 63, 65, 66, 67):
        return "Rain"
    if code in (71, 73, 75, 77):
        return "Snow"
    if code in (80, 81, 82):
        return "Showers"
    if code in (85, 86):
        return "Snow showers"
    if code in (95, 96, 99):
        return "Thunderstorm"
    return "Unknown"


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
    muted_css = rgba_to_css(text, max(0.0, min(1.0, text.alpha * 0.68)))
    weather_css = rgba_to_css(text, max(0.0, min(1.0, text.alpha * 0.80)))
    selection_css = rgba_to_css(text, 0.22)
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
    window#clock-widget-window {{
        background-color: transparent;
    }}

    #clock-widget-root {{
        background-color: {background_css};
        border: 1px solid {border_css};
        border-radius: {radius}px;
    }}

    label.clock {{
        {font_css(cfg.get("clock_font", "Sans Bold 34"))}
        color: {text_css};
    }}

    label.date {{
        {font_css(cfg.get("date_font", "Sans 11"))}
        color: {muted_css};
    }}

    label.weather {{
        {font_css(cfg.get("weather_font", "Sans 10"))}
        color: {weather_css};
    }}

    calendar {{
        {font_css(cfg.get("calendar_font", "Sans 10"))}
        color: {text_css};
        background-color: transparent;
        border-width: 0;
    }}

    calendar.header,
    calendar.button,
    calendar.highlight {{
        color: {text_css};
        background-color: transparent;
        border: none;
    }}

    calendar:selected {{
        color: {text_css};
        background-color: {selection_css};
    }}

    calendar:indeterminate {{
        color: {muted_css};
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
# Widget window
# --------------------------------------------------------------------------- #


class ClockWidget(Gtk.Window):
    def __init__(self, application: Gtk.Application | None = None):
        super().__init__(application=application, title="Desktop Clock")

        self.cfg = load_config()
        self._save_source: int | None = None
        self._settings_dialog: Gtk.Dialog | None = None
        self._menu: Gtk.Menu | None = None
        self._last_date = None
        self._marked_day: int | None = None
        self._weather_source: int | None = None
        self._weather_initial_source: int | None = None
        self._weather_busy = False
        self._location_busy = False
        self._location_generation = 0
        self._weather_generation = 0
        self._weather_status_text = ""
        self._weather_status_label: Gtk.Label | None = None
        self._weather_place_label: Gtk.Label | None = None
        self._weather_city_entry: Gtk.Entry | None = None

        self.set_name("clock-widget-window")
        self.set_decorated(False)
        self.set_resizable(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_focus_on_map(False)
        self.set_icon_name("preferences-system-time")
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
        self._apply_all()

        self.connect("configure-event", self._on_configure)
        self.connect("destroy", self._on_destroy)
        self.connect("key-press-event", self._on_key_press)

        self._tick()
        self._tick_source = GLib.timeout_add(250, self._tick)
        self._schedule_weather_refresh()
        self._weather_initial_source = GLib.timeout_add(1500, self._weather_initial)
        self.show_all()

    # ------------------------------------------------------------------ UI --

    def _build_ui(self) -> None:
        grid = Gtk.Grid()
        grid.set_row_spacing(0)
        grid.set_column_spacing(0)
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

        # Content area: catches clicks that are not handled by a child widget.
        self._root = Gtk.EventBox()
        self._root.set_name("clock-widget-root")
        self._root.set_visible_window(True)
        self._root.set_hexpand(True)
        self._root.set_vexpand(True)
        self._root.connect("button-press-event", self._on_root_press)
        grid.attach(self._root, 1, 1, 1, 1)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.set_margin_top(8)
        outer.set_margin_bottom(14)
        outer.set_margin_start(18)
        outer.set_margin_end(18)

        topbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        topbar.set_spacing(4)
        self._gear = Gtk.Button(label="\u2699")
        self._gear.set_name("settings-gear")
        self._gear.set_relief(Gtk.ReliefStyle.NONE)
        self._gear.set_tooltip_text("Settings  (right-click the widget for more)")
        self._gear.set_focus_on_click(False)
        self._gear.set_can_focus(False)
        self._gear.connect("clicked", lambda *_: self._open_settings())
        topbar.pack_end(self._gear, False, False, 0)
        outer.pack_start(topbar, False, False, 0)

        centre = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        centre.set_spacing(2)
        centre.set_valign(Gtk.Align.CENTER)
        centre.set_vexpand(True)

        self._clock_label = Gtk.Label()
        self._clock_label.get_style_context().add_class("clock")
        self._clock_label.set_halign(Gtk.Align.CENTER)
        self._clock_label.set_justify(Gtk.Justification.CENTER)
        centre.pack_start(self._clock_label, False, False, 0)

        self._date_label = Gtk.Label()
        self._date_label.get_style_context().add_class("date")
        self._date_label.set_halign(Gtk.Align.CENTER)
        self._date_label.set_justify(Gtk.Justification.CENTER)
        self._date_label.set_no_show_all(True)
        centre.pack_start(self._date_label, False, False, 0)

        self._weather_label = Gtk.Label()
        self._weather_label.get_style_context().add_class("weather")
        self._weather_label.set_halign(Gtk.Align.CENTER)
        self._weather_label.set_margin_top(2)
        self._weather_label.set_no_show_all(True)
        centre.pack_start(self._weather_label, False, False, 0)

        self._calendar = Gtk.Calendar()
        self._calendar.set_halign(Gtk.Align.FILL)
        self._calendar.set_hexpand(True)
        self._calendar.set_margin_top(8)
        self._calendar.set_no_show_all(True)
        centre.pack_start(self._calendar, False, False, 0)

        outer.pack_start(centre, True, True, 0)
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
        width = max(180, int(self.cfg.get("width") or 320))
        height = max(120, int(self.cfg.get("height") or 380))
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
                y = area.y + 48
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
        return False

    def _on_destroy(self, _widget: Gtk.Widget) -> None:
        if self._save_source is not None:
            GLib.source_remove(self._save_source)
            self._save_source = None
        if getattr(self, "_tick_source", None) is not None:
            GLib.source_remove(self._tick_source)
            self._tick_source = None
        if self._weather_source is not None:
            GLib.source_remove(self._weather_source)
            self._weather_source = None
        if getattr(self, "_weather_initial_source", None) is not None:
            GLib.source_remove(self._weather_initial_source)
            self._weather_initial_source = None
        self._invalidate_weather()
        self._location_generation += 1
        self._save()

    # --------------------------------------------------------------- ticking --

    def _tick(self) -> bool:
        now = datetime.now()
        try:
            self._clock_label.set_text(now.strftime(self.cfg.get("clock_format") or "%H:%M"))
        except ValueError:
            self._clock_label.set_text("--:--")
        try:
            self._date_label.set_text(now.strftime(self.cfg.get("date_format") or ""))
        except ValueError:
            self._date_label.set_text("")

        if now.date() != self._last_date:
            self._last_date = now.date()
            self._refresh_calendar(now)
        return True

    def _refresh_calendar(self, now: datetime | None = None) -> None:
        now = now or datetime.now()
        if self._marked_day is not None:
            self._calendar.clear_marks()
        self._marked_day = now.day
        self._calendar.select_month(now.month - 1, now.year)
        self._calendar.mark_day(now.day)
        self._calendar.select_day(now.day)

    # ------------------------------------------------------------- appearance --

    def _apply_all(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            self.set_opacity(max(0.2, min(1.0, float(self.cfg.get("opacity", 0.96)))))
        self.set_keep_above(bool(self.cfg.get("always_on_top", True)))

        self._date_label.set_visible(
            bool(self.cfg.get("show_date", True))
            and bool(str(self.cfg.get("date_format", "")).strip())
        )
        self._calendar.set_visible(bool(self.cfg.get("show_calendar", True)))
        self._calendar.set_property(
            "show-week-numbers", bool(self.cfg.get("week_numbers", False))
        )
        self._update_weather_label()

        css = build_css(self.cfg)
        try:
            self._style_provider.load_from_data(css.encode("utf-8"))
        except GLib.Error as exc:  # pragma: no cover - only if CSS is malformed
            print(f"Clock widget: could not apply styles: {exc}", file=sys.stderr)

        self._tick()

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
            print(f"Clock widget: could not save settings: {exc}", file=sys.stderr)
        return False

    # ---------------------------------------------------------------- weather --

    def _update_weather_label(self) -> None:
        temperature = self.cfg.get("weather_temp")
        description = str(self.cfg.get("weather_desc") or "").strip()
        visible = bool(self.cfg.get("show_weather")) and temperature is not None
        if visible:
            units = self.cfg.get("weather_cached_units") or self.cfg.get(
                "weather_units", "celsius"
            )
            symbol = "\u00b0F" if units == "fahrenheit" else "\u00b0C"
            try:
                shown = round(float(temperature))
            except (TypeError, ValueError):
                shown = "--"
            text = f"{shown}{symbol}"
            if description:
                text += f"  \u00b7  {description}"
            self._weather_label.set_text(text)
        self._weather_label.set_visible(visible)

    def _weather_initial(self) -> bool:
        self._weather_initial_source = None
        if self.cfg.get("show_weather"):
            if self.cfg.get("weather_lat") is None or self.cfg.get("weather_lon") is None:
                self._detect_location()
            else:
                self._refresh_weather()
        return False

    def _schedule_weather_refresh(self) -> None:
        if self._weather_source is not None:
            GLib.source_remove(self._weather_source)
            self._weather_source = None
        try:
            minutes = max(5, int(self.cfg.get("weather_refresh_minutes", 30)))
        except (TypeError, ValueError):
            minutes = 30
        self._weather_source = GLib.timeout_add_seconds(
            minutes * 60, self._weather_tick
        )

    def _weather_tick(self) -> bool:
        self._weather_source = None
        if self.cfg.get("show_weather") and self.cfg.get("weather_lat") is not None:
            self._refresh_weather()
        self._schedule_weather_refresh()
        return False

    def _invalidate_weather(self) -> None:
        """Ignore any weather result that is already in flight."""
        self._weather_generation += 1
        self._weather_busy = False

    def _refresh_weather(self, force: bool = False) -> None:
        if not self.cfg.get("show_weather"):
            return
        latitude = self.cfg.get("weather_lat")
        longitude = self.cfg.get("weather_lon")
        if latitude is None or longitude is None:
            self._detect_location()
            return
        if self._weather_busy:
            return

        self._weather_busy = True
        self._weather_generation += 1
        generation = self._weather_generation
        units = self.cfg.get("weather_units", "celsius")
        if units not in ("celsius", "fahrenheit"):
            units = "celsius"
        self._set_weather_status("Updating weather\u2026")

        def work() -> None:
            try:
                query = urllib.parse.urlencode(
                    {
                        "latitude": latitude,
                        "longitude": longitude,
                        "current": "temperature_2m,weather_code",
                        "temperature_unit": units,
                        "timezone": "auto",
                    }
                )
                data = self._http_json(
                    "https://api.open-meteo.com/v1/forecast?" + query
                )
                current = data.get("current") or {}
                temperature = float(current["temperature_2m"])
                code = int(current.get("weather_code", -1))
                GLib.idle_add(
                    self._weather_result,
                    generation,
                    temperature,
                    weather_description(code),
                    units,
                    None,
                )
            except Exception as exc:
                GLib.idle_add(
                    self._weather_result,
                    generation,
                    None,
                    "",
                    units,
                    str(exc),
                )

        threading.Thread(target=work, daemon=True).start()

    def _weather_result(
        self,
        generation: int,
        temperature: float | None,
        description: str,
        units: str,
        error: str | None,
    ) -> bool:
        if generation != self._weather_generation:
            return False
        self._weather_busy = False

        if error is not None or temperature is None:
            self._set_weather_status("Update failed \u2014 will try again later")
            return False

        self.cfg["weather_temp"] = round(temperature, 1)
        self.cfg["weather_desc"] = description
        self.cfg["weather_cached_units"] = units
        self.cfg["weather_fetched"] = int(time.time())
        self._update_weather_label()
        self._set_weather_status(self._weather_status_message())
        self._schedule_save()
        return False

    def _detect_location(self) -> None:
        if self._location_busy:
            return
        self._location_busy = True
        self._location_generation += 1
        generation = self._location_generation
        self._set_weather_status("Detecting location\u2026")

        def work() -> None:
            result = None
            try:
                data = self._http_json("https://ipwho.is/")
                if data.get("success", True) is not False:
                    result = self._location_from_ip_data(
                        data, "city", "region", "country"
                    )
            except Exception:
                pass
            if result is None:
                try:
                    data = self._http_json("https://ipapi.co/json/")
                    result = self._location_from_ip_data(
                        data, "city", "region", "country_name"
                    )
                except Exception:
                    pass
            GLib.idle_add(self._location_result, generation, result, None)

        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _location_from_ip_data(
        data: dict, city_key: str, region_key: str, country_key: str
    ) -> tuple[float, float, str] | None:
        latitude = data.get("latitude")
        longitude = data.get("longitude")
        if latitude is None or longitude is None:
            return None
        parts: list[str] = []
        for key in (city_key, region_key, country_key):
            value = data.get(key)
            if value and str(value) not in parts:
                parts.append(str(value))
        return float(latitude), float(longitude), ", ".join(parts)

    def _geocode_city(self, query: str) -> None:
        query = query.strip()
        if not query:
            return
        self._location_busy = True
        self._location_generation += 1
        generation = self._location_generation
        self._set_weather_status("Searching for a location\u2026")

        def work() -> None:
            try:
                params = urllib.parse.urlencode(
                    {"name": query, "count": 1, "language": "en", "format": "json"}
                )
                data = self._http_json(
                    "https://geocoding-api.open-meteo.com/v1/search?" + params
                )
                results = data.get("results") or []
                if not results:
                    GLib.idle_add(
                        self._location_result,
                        generation,
                        None,
                        "Location not found \u2014 try a different name",
                    )
                    return
                place = results[0]
                parts = [
                    str(part)
                    for part in (
                        place.get("name"),
                        place.get("admin1"),
                        place.get("country"),
                    )
                    if part
                ]
                result = (
                    float(place["latitude"]),
                    float(place["longitude"]),
                    ", ".join(dict.fromkeys(parts)),
                )
                GLib.idle_add(self._location_result, generation, result, None)
            except Exception:
                GLib.idle_add(
                    self._location_result,
                    generation,
                    None,
                    "Could not search \u2014 check your connection",
                )

        threading.Thread(target=work, daemon=True).start()

    def _location_result(
        self,
        generation: int,
        result: tuple[float, float, str] | None,
        error: str | None = None,
    ) -> bool:
        if generation != self._location_generation:
            return False
        self._location_busy = False
        if result is None:
            self._set_weather_status(
                error or "Could not determine a location \u2014 set a city instead"
            )
            return False

        latitude, longitude, place = result
        self.cfg["weather_lat"] = latitude
        self.cfg["weather_lon"] = longitude
        self.cfg["weather_place"] = place
        self.cfg["weather_temp"] = None
        self.cfg["weather_desc"] = ""
        self.cfg["weather_fetched"] = None
        self._invalidate_weather()
        self._update_weather_label()
        self._update_location_widgets()
        self._set_weather_status(f"Location set to {place}")
        self._schedule_save()
        self._refresh_weather(force=True)
        return False

    def _update_location_widgets(self) -> None:
        place = str(self.cfg.get("weather_place") or "")
        if self._weather_place_label is not None:
            self._weather_place_label.set_text(place or "No location set")
        if self._weather_city_entry is not None and place:
            self._weather_city_entry.set_text(place)

    def _weather_status_message(self) -> str:
        if not self.cfg.get("show_weather"):
            return "Weather is turned off."
        if self.cfg.get("weather_lat") is None:
            return "No location set \u2014 search for a city or use your current location."
        if self._weather_busy:
            return "Updating weather\u2026"
        fetched = self.cfg.get("weather_fetched")
        place = str(self.cfg.get("weather_place") or "Current location")
        if fetched:
            try:
                when = datetime.fromtimestamp(int(fetched)).strftime("%H:%M")
            except (TypeError, ValueError, OSError):
                when = ""
            suffix = f" \u00b7 updated {when}" if when else ""
            return f"{place}{suffix}"
        return "Waiting for the first update\u2026"

    def _set_weather_status(self, text: str) -> None:
        self._weather_status_text = text
        if self._weather_status_label is not None:
            self._weather_status_label.set_text(text)

    @staticmethod
    def _http_json(url: str) -> dict:
        request = urllib.request.Request(
            url, headers={"User-Agent": "DesktopClockWidget/1.0"}
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)

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
                    "Name=Desktop Clock & Calendar\n"
                    "Comment=Clock and calendar widget\n"
                    f"Exec={desktop_quote(sys.executable)} {desktop_quote(script)}\n"
                    "Icon=preferences-system-time\n"
                    "Terminal=false\n"
                    "Categories=Utility;Clock;\n"
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
            print(f"Clock widget: could not change autostart: {exc}", file=sys.stderr)

    # ------------------------------------------------------------------ menu --

    def _show_menu(self, event: Gdk.EventButton) -> None:
        menu = Gtk.Menu()
        menu.attach_to_widget(self, None)

        settings = Gtk.MenuItem(label="Settings\u2026")
        settings.connect("activate", lambda *_: self._open_settings())
        menu.append(settings)

        for label, key in (("Show date", "show_date"), ("Show calendar", "show_calendar")):
            item = Gtk.CheckMenuItem(label=label)
            item.set_active(bool(self.cfg.get(key)))
            item.connect(
                "toggled", lambda widget, k=key: self._set_cfg(k, widget.get_active())
            )
            menu.append(item)

        refresh_weather = Gtk.MenuItem(label="Refresh weather")
        refresh_weather.set_sensitive(bool(self.cfg.get("show_weather")))
        refresh_weather.connect("activate", lambda *_: self._refresh_weather(force=True))
        menu.append(refresh_weather)

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

        dialog = Gtk.Dialog(title="Clock Widget Settings", parent=self, modal=True)
        dialog.set_default_size(500, 480)
        dialog.set_position(Gtk.WindowPosition.CENTER_ON_PARENT)
        dialog.add_button("Close", Gtk.ResponseType.CLOSE)
        dialog.set_default_response(Gtk.ResponseType.CLOSE)

        notebook = Gtk.Notebook()
        notebook.set_border_width(8)
        notebook.append_page(self._page_clock(dialog), Gtk.Label(label="Clock"))
        notebook.append_page(self._page_date(dialog), Gtk.Label(label="Date"))
        notebook.append_page(self._page_weather(dialog), Gtk.Label(label="Weather"))
        notebook.append_page(self._page_calendar(dialog), Gtk.Label(label="Calendar"))
        notebook.append_page(self._page_appearance(), Gtk.Label(label="Appearance"))
        notebook.append_page(self._page_behaviour(dialog), Gtk.Label(label="Behaviour"))
        dialog.get_content_area().add(notebook)

        dialog.connect("response", lambda d, _r: d.destroy())
        dialog.connect("destroy", self._on_settings_destroyed)
        self._settings_dialog = dialog
        dialog.show_all()

    def _on_settings_destroyed(self, _dialog: Gtk.Widget) -> None:
        self._settings_dialog = None
        self._weather_status_label = None
        self._weather_place_label = None
        self._weather_city_entry = None

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

    def _page_clock(self, dialog: Gtk.Dialog) -> Gtk.Grid:
        grid = self._make_page()
        entry = Gtk.Entry()
        entry.set_text(str(self.cfg.get("clock_format", "%H:%M")))
        preview = Gtk.Label(xalign=0)
        preview.get_style_context().add_class("dim-label")

        combo = Gtk.ComboBoxText()
        syncing = {"on": False}

        def update_preview() -> None:
            try:
                preview.set_text(
                    "Preview:   " + datetime.now().strftime(entry.get_text() or "")
                )
            except ValueError:
                preview.set_text("Preview:   (invalid format)")

        def sync_combo() -> None:
            current = entry.get_text()
            active = len(CLOCK_PRESETS) - 1
            for index, (_label, fmt) in enumerate(CLOCK_PRESETS):
                if fmt is not None and fmt == current:
                    active = index
                    break
            if combo.get_active() != active:
                syncing["on"] = True
                combo.set_active(active)
                syncing["on"] = False

        def on_entry_changed(widget: Gtk.Entry) -> None:
            if syncing["on"]:
                return
            self._set_cfg("clock_format", widget.get_text())
            update_preview()
            sync_combo()

        def on_combo_changed(widget: Gtk.ComboBoxText) -> None:
            if syncing["on"]:
                return
            index = widget.get_active()
            if index < 0:
                return
            fmt = CLOCK_PRESETS[index][1]
            if fmt is not None and fmt != entry.get_text():
                syncing["on"] = True
                entry.set_text(fmt)
                syncing["on"] = False
                self._set_cfg("clock_format", fmt)
            update_preview()
            sync_combo()

        for label, _fmt in CLOCK_PRESETS:
            combo.append_text(label)
        combo.connect("changed", on_combo_changed)
        entry.connect("changed", on_entry_changed)
        sync_combo()
        update_preview()

        self._add_row(grid, 0, "Preset", combo)
        self._add_row(grid, 1, "Format", entry)
        grid.attach(preview, 1, 2, 1, 1)
        self._add_row(
            grid, 3, "Font", self._make_font_button("Clock font", "clock_font")
        )

        hint = Gtk.Label(
            xalign=0,
            wrap=True,
            label=(
                "The format uses standard strftime codes, e.g. %H = hour, %M = minute, "
                "%S = seconds, %p = AM/PM."
            ),
        )
        hint.get_style_context().add_class("dim-label")
        grid.attach(hint, 0, 4, 2, 1)
        grid.set_row_spacing(10)
        return grid

    def _page_date(self, dialog: Gtk.Dialog) -> Gtk.Grid:
        grid = self._make_page()

        show = Gtk.CheckButton(label="Show the date")
        show.set_active(bool(self.cfg.get("show_date", True)))
        grid.attach(show, 0, 0, 2, 1)

        entry = Gtk.Entry()
        entry.set_text(str(self.cfg.get("date_format", "%A, %d %B %Y")))
        entry.set_sensitive(bool(self.cfg.get("show_date", True)))
        preview = Gtk.Label(xalign=0)
        preview.get_style_context().add_class("dim-label")

        combo = Gtk.ComboBoxText()
        syncing = {"on": False}

        def update_preview() -> None:
            try:
                preview.set_text(
                    "Preview:   " + datetime.now().strftime(entry.get_text() or "")
                )
            except ValueError:
                preview.set_text("Preview:   (invalid format)")

        def sync_combo() -> None:
            current = entry.get_text()
            active = len(DATE_PRESETS) - 1
            for index, (_label, fmt) in enumerate(DATE_PRESETS):
                if fmt is not None and fmt == current:
                    active = index
                    break
            if combo.get_active() != active:
                syncing["on"] = True
                combo.set_active(active)
                syncing["on"] = False

        def on_entry_changed(widget: Gtk.Entry) -> None:
            if syncing["on"]:
                return
            self._set_cfg("date_format", widget.get_text())
            update_preview()
            sync_combo()

        def on_combo_changed(widget: Gtk.ComboBoxText) -> None:
            if syncing["on"]:
                return
            index = widget.get_active()
            if index < 0:
                return
            fmt = DATE_PRESETS[index][1]
            if fmt is not None and fmt != entry.get_text():
                syncing["on"] = True
                entry.set_text(fmt)
                syncing["on"] = False
                self._set_cfg("date_format", fmt)
            update_preview()
            sync_combo()

        for label, _fmt in DATE_PRESETS:
            combo.append_text(label)
        combo.connect("changed", on_combo_changed)
        entry.connect("changed", on_entry_changed)
        sync_combo()
        update_preview()

        def on_show_toggled(widget: Gtk.CheckButton) -> None:
            enabled = widget.get_active()
            entry.set_sensitive(enabled)
            combo.set_sensitive(enabled)
            self._set_cfg("show_date", enabled)

        show.connect("toggled", on_show_toggled)

        self._add_row(grid, 1, "Preset", combo)
        self._add_row(grid, 2, "Format", entry)
        grid.attach(preview, 1, 3, 1, 1)
        self._add_row(
            grid, 4, "Font", self._make_font_button("Date font", "date_font")
        )

        hint = Gtk.Label(
            xalign=0,
            wrap=True,
            label="Examples: %A = weekday, %d = day, %B = month name, %Y = year.",
        )
        hint.get_style_context().add_class("dim-label")
        grid.attach(hint, 0, 5, 2, 1)
        return grid

    def _page_weather(self, dialog: Gtk.Dialog) -> Gtk.Grid:
        grid = self._make_page()

        show = Gtk.CheckButton(label="Show weather next to the clock")
        show.set_active(bool(self.cfg.get("show_weather", True)))
        grid.attach(show, 0, 0, 2, 1)

        location_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._weather_city_entry = Gtk.Entry()
        self._weather_city_entry.set_placeholder_text("City, e.g. Bristol or New York")
        self._weather_city_entry.set_text(str(self.cfg.get("weather_place") or ""))
        self._weather_city_entry.set_hexpand(True)
        find = Gtk.Button(label="Find")
        find.connect(
            "clicked",
            lambda *_: self._geocode_city(self._weather_city_entry.get_text()),
        )
        self._weather_city_entry.connect(
            "activate", lambda widget: self._geocode_city(widget.get_text())
        )
        here = Gtk.Button(label="Use my location")
        here.connect("clicked", lambda *_: self._detect_location())
        location_box.pack_start(self._weather_city_entry, True, True, 0)
        location_box.pack_start(find, False, False, 0)
        location_box.pack_start(here, False, False, 0)
        self._add_row(grid, 1, "Location", location_box)

        self._weather_place_label = Gtk.Label(xalign=0)
        self._weather_place_label.get_style_context().add_class("dim-label")
        self._weather_place_label.set_text(
            str(self.cfg.get("weather_place") or "No location set")
        )
        grid.attach(self._weather_place_label, 1, 2, 1, 1)

        units = Gtk.ComboBoxText()
        units.append_text("Celsius (\u00b0C)")
        units.append_text("Fahrenheit (\u00b0F)")
        units.set_active(1 if self.cfg.get("weather_units") == "fahrenheit" else 0)

        def on_units(widget: Gtk.ComboBoxText) -> None:
            new_units = "fahrenheit" if widget.get_active() == 1 else "celsius"
            if new_units == self.cfg.get("weather_units"):
                return
            self.cfg["weather_units"] = new_units
            self.cfg["weather_temp"] = None
            self.cfg["weather_desc"] = ""
            self.cfg["weather_fetched"] = None
            self._invalidate_weather()
            self._update_weather_label()
            self._schedule_save()
            self._refresh_weather(force=True)

        units.connect("changed", on_units)
        self._add_row(grid, 3, "Units", units)

        interval = Gtk.SpinButton.new_with_range(5, 240, 5)
        interval.set_value(float(self.cfg.get("weather_refresh_minutes", 30)))
        interval.set_tooltip_text("How often the temperature is refreshed")

        def on_interval(widget: Gtk.SpinButton) -> None:
            self._set_cfg("weather_refresh_minutes", int(widget.get_value()))
            self._schedule_weather_refresh()

        interval.connect("value-changed", on_interval)
        self._add_row(grid, 4, "Refresh every (min)", interval)

        self._add_row(
            grid, 5, "Font", self._make_font_button("Weather font", "weather_font")
        )

        status = Gtk.Label(xalign=0, wrap=True)
        status.get_style_context().add_class("dim-label")
        status.set_text(self._weather_status_text or self._weather_status_message())
        self._weather_status_label = status
        grid.attach(status, 0, 6, 2, 1)

        refresh = Gtk.Button(label="Refresh weather now")
        refresh.set_halign(Gtk.Align.START)
        refresh.connect("clicked", lambda *_: self._refresh_weather(force=True))
        grid.attach(refresh, 0, 7, 2, 1)

        note = Gtk.Label(
            xalign=0,
            wrap=True,
            label=(
                "Weather data comes from Open-Meteo.com. Choosing \u201cUse my "
                "location\u201d sends your IP address to ipwho.is to estimate the "
                "town; the coordinates are then stored locally."
            ),
        )
        note.get_style_context().add_class("dim-label")
        grid.attach(note, 0, 8, 2, 1)

        def on_show(widget: Gtk.CheckButton) -> None:
            enabled = widget.get_active()
            self._set_cfg("show_weather", enabled)
            if enabled:
                if self.cfg.get("weather_lat") is None:
                    self._detect_location()
                else:
                    self._refresh_weather(force=True)

        show.connect("toggled", on_show)
        return grid

    def _page_calendar(self, dialog: Gtk.Dialog) -> Gtk.Grid:
        grid = self._make_page()

        show = Gtk.CheckButton(label="Show the calendar")
        show.set_active(bool(self.cfg.get("show_calendar", True)))
        grid.attach(show, 0, 0, 2, 1)

        weeks = Gtk.CheckButton(label="Show week numbers")
        weeks.set_active(bool(self.cfg.get("week_numbers", False)))
        weeks.connect(
            "toggled",
            lambda widget: self._set_cfg("week_numbers", widget.get_active()),
        )
        grid.attach(weeks, 0, 1, 2, 1)

        font_button = self._make_font_button("Calendar font", "calendar_font")
        self._add_row(grid, 2, "Font", font_button)

        def on_show_toggled(widget: Gtk.CheckButton) -> None:
            enabled = widget.get_active()
            weeks.set_sensitive(enabled)
            font_button.set_sensitive(enabled)
            self._set_cfg("show_calendar", enabled)

        show.connect("toggled", on_show_toggled)
        weeks.set_sensitive(show.get_active())
        font_button.set_sensitive(show.get_active())

        hint = Gtk.Label(
            xalign=0,
            wrap=True,
            label=(
                "Today is marked in the calendar. Use the arrows to browse months; "
                "the widget returns to the current month at midnight."
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
        locked.set_tooltip_text("Unlock to drag or resize the widget again")
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
                "Drag the clock or empty space to move the widget. Drag an edge or "
                "corner to resize it. Right-click the widget for quick options; "
                "Ctrl+, opens these settings and Ctrl+Q quits."
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
            "Fonts, colours, formats, weather and appearance will be reset. "
            "Position, size and the start-at-login setting are kept."
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
        self._schedule_weather_refresh()
        if self.cfg.get("show_weather") and self.cfg.get("weather_lat") is None:
            self._detect_location()

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
            # ClockWidget shows itself; presenting here would steal keyboard
            # focus from whatever the user is doing on login.
            window = ClockWidget(application=app)
        else:
            window.present()

    application.connect("activate", on_activate)
    return application.run(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
