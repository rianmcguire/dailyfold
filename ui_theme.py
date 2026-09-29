"""Colors derived from the active GTK theme."""

from dataclasses import dataclass

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, Gtk


RGB = tuple[float, float, float]
COLOR_SCHEME_SCHEMA = "org.gnome.desktop.interface"
COLOR_SCHEME_KEY = "color-scheme"


@dataclass(frozen=True)
class ThemePalette:
    background: RGB
    text: RGB
    muted_text: RGB
    collapsed_indicator: RGB
    guide: RGB
    selection_bg: RGB
    code_bg: RGB
    link: RGB
    todo_accent: RGB
    todo_bg: RGB
    done_accent: RGB
    done_bg: RGB
    search_match_bg: RGB
    search_match_fg: RGB
    checkmark: RGB


def _apply_color_scheme(color_settings, gtk_settings):
    prefer_dark = color_settings.get_string(COLOR_SCHEME_KEY) == "prefer-dark"
    gtk_settings.set_property(
        "gtk-application-prefer-dark-theme", prefer_dark
    )


def _on_color_scheme_changed(color_settings, key, gtk_settings):
    _apply_color_scheme(color_settings, gtk_settings)


def follow_system_color_scheme():
    """Make GTK3 follow the desktop color-scheme preference when available."""
    source = Gio.SettingsSchemaSource.get_default()
    if source is None:
        return None
    schema = source.lookup(COLOR_SCHEME_SCHEMA, True)
    if schema is None or COLOR_SCHEME_KEY not in schema.list_keys():
        return None

    gtk_settings = Gtk.Settings.get_default()
    if gtk_settings is None:
        return None

    color_settings = Gio.Settings.new_full(schema, None, None)
    color_settings.connect(
        f"changed::{COLOR_SCHEME_KEY}",
        _on_color_scheme_changed,
        gtk_settings,
    )
    _apply_color_scheme(color_settings, gtk_settings)
    return color_settings


def blend(foreground: RGB, background: RGB, amount: float) -> RGB:
    """Return *foreground* composited over *background* at *amount*."""
    return tuple(
        background[channel]
        + (foreground[channel] - background[channel]) * amount
        for channel in range(3)
    )


def color_hex(color: RGB) -> str:
    channels = [max(0, min(255, round(value * 255))) for value in color]
    return "#{:02x}{:02x}{:02x}".format(*channels)


def _rgb(rgba) -> RGB:
    return rgba.red, rgba.green, rgba.blue


def _lookup(context, *names):
    for name in names:
        found, rgba = context.lookup_color(name)
        if found:
            return _rgb(rgba)
    return None


def _state_color(context, state, background=False):
    if background:
        rgba = context.get_background_color(state)
        if rgba.alpha <= 0:
            return None
    else:
        rgba = context.get_color(state)
    return _rgb(rgba)


def _relative_luminance(color: RGB) -> float:
    def linear(channel):
        if channel <= 0.04045:
            return channel / 12.92
        return ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in color)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(first: RGB, second: RGB) -> float:
    lighter, darker = sorted(
        (_relative_luminance(first), _relative_luminance(second)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


def _ensure_contrast(color: RGB, background: RGB, text: RGB) -> RGB:
    """Move a semantic theme color toward text until it is readable."""
    if _contrast(color, background) >= 4.5:
        return color
    for step in range(1, 11):
        candidate = blend(text, color, step / 10)
        if _contrast(candidate, background) >= 4.5:
            return candidate
    return text


def palette_for(widget) -> ThemePalette:
    """Resolve a complete palette from *widget*'s current style context."""
    context = widget.get_style_context()

    background = (
        _lookup(context, "theme_base_color", "theme_bg_color")
        or _state_color(context, Gtk.StateFlags.NORMAL, background=True)
        or (1.0, 1.0, 1.0)
    )
    text = (
        _lookup(context, "theme_text_color", "theme_fg_color")
        or _state_color(context, Gtk.StateFlags.NORMAL)
        or (0.13, 0.13, 0.13)
    )
    selected_bg = (
        _lookup(context, "theme_selected_bg_color")
        or _state_color(context, Gtk.StateFlags.SELECTED, background=True)
        or blend(text, background, 0.35)
    )
    selected_fg = (
        _lookup(context, "theme_selected_fg_color")
        or _state_color(context, Gtk.StateFlags.SELECTED)
        or text
    )
    link = _ensure_contrast(
        _lookup(context, "link_color", "theme_link_color") or selected_bg,
        background,
        text,
    )
    success = _ensure_contrast(
        _lookup(context, "success_color") or link,
        background,
        text,
    )

    # Theme colors provide the hue and contrast. Subtle surfaces are blends so
    # they remain legible on both light and dark themes without a second fixed
    # palette to maintain.
    code_bg = blend(text, background, 0.055)
    checkmark = max(
        (text, background, selected_fg),
        key=lambda candidate: _contrast(candidate, success),
    )
    return ThemePalette(
        background=background,
        text=text,
        muted_text=blend(text, background, 0.58),
        collapsed_indicator=blend(text, background, 0.72),
        guide=blend(text, background, 0.16),
        selection_bg=blend(selected_bg, background, 0.28),
        code_bg=code_bg,
        link=link,
        todo_accent=link,
        todo_bg=blend(link, background, 0.14),
        done_accent=success,
        done_bg=blend(success, background, 0.14),
        search_match_bg=blend(selected_bg, background, 0.38),
        search_match_fg=text,
        checkmark=checkmark,
    )
