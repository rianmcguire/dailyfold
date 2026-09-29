import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from ui_theme import (
    COLOR_SCHEME_KEY,
    COLOR_SCHEME_SCHEMA,
    _apply_color_scheme,
    _contrast,
    blend,
    color_hex,
    follow_system_color_scheme,
    palette_for,
)


def rgba(color, alpha=1.0):
    return SimpleNamespace(
        red=color[0], green=color[1], blue=color[2], alpha=alpha
    )


class FakeContext:
    def __init__(self, colors):
        self.colors = colors

    def lookup_color(self, name):
        color = self.colors.get(name)
        return (color is not None, rgba(color or (0, 0, 0)))

    def get_background_color(self, state):
        return rgba((0, 0, 0), alpha=0)

    def get_color(self, state):
        return rgba(self.colors["theme_text_color"])


class TestThemePalette(unittest.TestCase):
    def palette(self, colors):
        widget = SimpleNamespace(get_style_context=lambda: FakeContext(colors))
        return palette_for(widget)

    def test_blends_colors_and_serializes_them_for_markup(self):
        self.assertEqual(blend((1, 1, 1), (0, 0, 0), 0.25), (0.25,) * 3)
        self.assertEqual(color_hex((0.0, 0.5, 1.0)), "#0080ff")

    def test_dark_theme_uses_theme_background_and_readable_accents(self):
        background = (45 / 255, 45 / 255, 45 / 255)
        palette = self.palette(
            {
                "theme_base_color": background,
                "theme_text_color": (1, 1, 1),
                "theme_selected_bg_color": (21 / 255, 83 / 255, 158 / 255),
                "theme_selected_fg_color": (1, 1, 1),
                "success_color": (38 / 255, 171 / 255, 98 / 255),
            }
        )

        self.assertEqual(palette.background, background)
        self.assertGreaterEqual(_contrast(palette.link, background), 4.5)
        self.assertGreaterEqual(_contrast(palette.done_accent, background), 4.5)
        self.assertGreater(palette.code_bg[0], background[0])

    def test_light_theme_darkens_accent_when_needed(self):
        background = (1, 1, 1)
        selected = (53 / 255, 132 / 255, 228 / 255)
        palette = self.palette(
            {
                "theme_base_color": background,
                "theme_text_color": (46 / 255, 52 / 255, 54 / 255),
                "theme_selected_bg_color": selected,
                "theme_selected_fg_color": (1, 1, 1),
            }
        )

        self.assertGreaterEqual(_contrast(palette.link, background), 4.5)
        self.assertLess(palette.link[0], selected[0])
        self.assertLess(palette.code_bg[0], background[0])


class TestSystemColorScheme(unittest.TestCase):
    def test_prefer_dark_sets_gtk_dark_preference(self):
        color_settings = Mock()
        color_settings.get_string.return_value = "prefer-dark"
        gtk_settings = Mock()

        _apply_color_scheme(color_settings, gtk_settings)

        color_settings.get_string.assert_called_once_with(COLOR_SCHEME_KEY)
        gtk_settings.set_property.assert_called_once_with(
            "gtk-application-prefer-dark-theme", True
        )

    def test_default_and_prefer_light_clear_gtk_dark_preference(self):
        for value in ("default", "prefer-light"):
            with self.subTest(value=value):
                color_settings = Mock()
                color_settings.get_string.return_value = value
                gtk_settings = Mock()

                _apply_color_scheme(color_settings, gtk_settings)

                gtk_settings.set_property.assert_called_once_with(
                    "gtk-application-prefer-dark-theme", False
                )

    @patch("ui_theme.Gtk.Settings.get_default")
    @patch("ui_theme.Gio.Settings.new_full")
    @patch("ui_theme.Gio.SettingsSchemaSource.get_default")
    def test_binding_applies_and_watches_available_setting(
        self,
        get_schema_source,
        new_settings,
        get_gtk_settings,
    ):
        schema = Mock()
        schema.list_keys.return_value = [COLOR_SCHEME_KEY]
        source = get_schema_source.return_value
        source.lookup.return_value = schema
        color_settings = new_settings.return_value
        color_settings.get_string.return_value = "prefer-dark"
        gtk_settings = get_gtk_settings.return_value

        result = follow_system_color_scheme()

        self.assertIs(result, color_settings)
        source.lookup.assert_called_once_with(COLOR_SCHEME_SCHEMA, True)
        new_settings.assert_called_once_with(schema, None, None)
        color_settings.connect.assert_called_once()
        gtk_settings.set_property.assert_called_once_with(
            "gtk-application-prefer-dark-theme", True
        )

    @patch("ui_theme.Gio.SettingsSchemaSource.get_default", return_value=None)
    def test_missing_settings_schema_is_ignored(self, get_schema_source):
        self.assertIsNone(follow_system_color_scheme())


if __name__ == "__main__":
    unittest.main()
