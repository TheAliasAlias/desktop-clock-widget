# Desktop Clock & Calendar

A small frameless desktop widget for Linux with a live clock, date, month
calendar and current weather. Drag it anywhere, resize it from any edge, fade it
into the background, and pick your own fonts, colours and time format.

Built with Python 3 and GTK 3 (PyGObject), so there is nothing extra to install
on Linux Mint / Cinnamon.

![Desktop Clock & Calendar](screenshot.png)

## Features

- Frameless, rounded, always-on-top widget.
- Drag to move; drag any edge or corner to resize.
- Live clock with custom `strftime` format (12/24-hour, seconds, etc.).
- Date line and month calendar with today marked.
- Current temperature and conditions from Open-Meteo, with automatic or manually
  chosen location and Celsius/Fahrenheit units.
- Settings for fonts, text colour, background colour and background alpha,
  window opacity, and corner radius.
- Remembers position, size and every setting between sessions.
- Optional start at login.

## Run it

```bash
git clone https://github.com/TheAliasAlias/desktop-clock-widget.git
cd desktop-clock-widget
python3 desktop_clock.py
```

The first time it runs, the widget appears near the top-right of the screen.
Starting it again while it is already running simply brings it forward.

## Controls

| Action | How |
|---|---|
| Move | Drag the clock, date, or any empty part of the widget |
| Resize | Drag an edge or corner |
| Settings | Click the small **⚙** button, or right-click → Settings |
| Quick options | Right-click the widget |
| Settings shortcut | `Ctrl+,` |
| Quit | `Ctrl+Q`, or right-click → Quit |

If you turn off **Always on top**, the widget can sit behind other windows. Use
the application-menu entry to bring it back.

The calendar arrows browse other months; the widget returns to the current
month at midnight. If **Lock position and size** is enabled, dragging and
resizing are disabled, but the settings button and right-click menu still work.

## Settings

- **Clock** — presets or a custom format, plus the clock font.
- **Date** — show/hide, presets or a custom format, plus the date font.
- **Weather** — show/hide, location (search by city or use your current
  location), °C/°F, refresh interval and weather font.
- **Calendar** — show/hide, week numbers, plus the calendar font.
- **Appearance** — text colour, background colour, **background alpha**,
  window opacity, corner radius.
- **Behaviour** — always on top, lock position/size, start at login, and
  restore defaults.

Changes apply immediately, while the settings window is open.

### Background alpha vs. window opacity

- **Background alpha** changes only the panel behind the text: 0% is completely
  transparent, 100% is solid. This is the usual control for a translucent
  desktop widget.
- **Window opacity** fades the entire widget, including the clock and calendar.

## Weather

Weather is shown under the date as, for example, `17°C · Partly cloudy`. It uses
the free [Open-Meteo](https://open-meteo.com/) API, which needs no account or
API key.

- On first run the widget estimates your town from your IP address (using
  ipwho.is, with ipapi.co as a fallback) and stores only the resulting
  coordinates locally.
- To choose a different place, open **Settings → Weather**, type a city name
  and click **Find**.
- **Use my location** repeats the IP-based lookup.
- Temperature refreshes every 30 minutes by default; change this in the Weather
  tab, or use **Refresh weather now** / right-click → Refresh weather.
- If there is no connection, the last reading stays visible and updates resume
  automatically. With no location at all, the weather line stays hidden.

Only the coordinates are sent to Open-Meteo with each request; the last reading
is cached in the settings file so it can be shown immediately at startup.

Format strings use the standard Python `strftime` codes, for example:

| Code | Meaning |
|---|---|
| `%H` / `%I` | hour (24-hour / 12-hour) |
| `%M` / `%S` | minute / second |
| `%p` | AM or PM |
| `%A` / `%a` | weekday name / short weekday |
| `%d` / `%B` / `%Y` | day / month name / year |

So `%H:%M` gives `14:05`, and `%I:%M %p` gives `2:05 PM`.

## Install the menu and login entries

```bash
cd desktop-clock-widget
./install.sh
```

This adds:

- an application-menu entry (`~/.local/share/applications/`), and
- a start-at-login entry (`~/.config/autostart/`).

You can also toggle **Start automatically when I log in** in the widget's
Behaviour settings.

To remove both entries:

```bash
./uninstall.sh
```

The autostart entry points at the script's current path. If you move this
folder, re-run `install.sh` (or toggle the login option off and on again).

## Settings file

Settings live in:

```
~/.config/desktop-clock-widget/config.json
```

It is written automatically whenever something changes. It also caches the
chosen weather location and the last reading. Delete the file (with the widget
closed) to return to defaults, or use **Restore default settings** in the
Behaviour tab.

## Requirements

- Python 3.8 or newer
- PyGObject (`python3-gi`) and GTK 3 (`gir1.2-gtk-3.0`)

Both are normally preinstalled on Linux Mint. To check:

```bash
python3 -c "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk; print('GTK ready')"
```

On Debian/Ubuntu/Mint, if needed:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0
```

Transparency and rounded corners need a compositing window manager, which
Cinnamon, MATE, Xfce (with compositing) and GNOME all provide.

## License

MIT — see [LICENSE](LICENSE).
