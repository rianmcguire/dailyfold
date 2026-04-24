import argparse
import os
from dataclasses import dataclass

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Pango, PangoCairo


BG = (1.0, 1.0, 1.0)
FG = (0.13, 0.13, 0.13)
DIM = (0.55, 0.55, 0.57)
GUIDE = (0.87, 0.87, 0.89)


@dataclass
class Block:
    level: int
    text: str


BLOCKS = [
    Block(0, "Wednesday, 24 April 2026"),
    Block(1, "dailyfold — hello, world"),
    Block(2, "GTK3 window open"),
    Block(2, "custom Cairo rendering"),
    Block(2, "snapshot → PNG for feedback"),
    Block(1, "next: editable bullets"),
]


def resolve_body_font(widget=None):
    if widget is not None:
        return widget.get_pango_context().get_font_description().copy()
    settings = Gtk.Settings.get_default()
    name = settings.get_property("gtk-font-name") if settings else None
    return Pango.FontDescription(name or "Sans 11")


def render_blocks(cr, width, height, body_font, blocks):
    cr.set_source_rgb(*BG)
    cr.paint()

    layout = PangoCairo.create_layout(cr)
    layout.set_font_description(body_font)
    layout.set_text("Ag", -1)
    _, body_ext = layout.get_pixel_extents()
    line_h = body_ext.height + 8

    header_font = body_font.copy()
    size = header_font.get_size() or 11 * Pango.SCALE
    header_font.set_size(int(size * 1.3))
    header_font.set_weight(Pango.Weight.BOLD)

    x0 = 32
    y = 28
    indent = 22

    for block in blocks:
        x = x0 + block.level * indent

        if block.level == 0:
            layout.set_font_description(header_font)
            layout.set_text(block.text, -1)
            _, ext = layout.get_pixel_extents()
            cr.set_source_rgb(*FG)
            cr.move_to(x, y)
            PangoCairo.show_layout(cr, layout)
            y += ext.height + 12
            layout.set_font_description(body_font)
            continue

        cr.set_source_rgb(*GUIDE)
        cr.set_line_width(1)
        for g in range(1, block.level):
            gxi = x0 + g * indent - indent // 2
            cr.move_to(gxi + 0.5, y)
            cr.line_to(gxi + 0.5, y + line_h)
            cr.stroke()

        cr.set_source_rgb(*DIM)
        cr.arc(x + 5, y + line_h / 2, 2.5, 0, 2 * 3.14159)
        cr.fill()

        cr.set_source_rgb(*FG)
        layout.set_text(block.text, -1)
        cr.move_to(x + 16, y + (line_h - body_ext.height) / 2)
        PangoCairo.show_layout(cr, layout)

        y += line_h


class BlocksView(Gtk.Overlay):
    def __init__(self, blocks):
        super().__init__()
        self.blocks = blocks
        self.canvas = Gtk.DrawingArea()
        self.canvas.connect("draw", self._on_draw)
        self.add(self.canvas)

    def _on_draw(self, widget, cr):
        alloc = widget.get_allocation()
        render_blocks(cr, alloc.width, alloc.height, resolve_body_font(widget), self.blocks)
        return False


class AppWindow(Gtk.Window):
    def __init__(self, blocks):
        super().__init__(title="dailyfold")
        self.set_default_size(720, 480)
        self.connect("destroy", Gtk.main_quit)
        self.add(BlocksView(blocks))


DEFAULT_SNAPSHOT = os.path.join(os.path.dirname(__file__), "snapshots", "latest.png")


def snapshot(path, width=720, height=480):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    render_blocks(cr, width, height, resolve_body_font(), BLOCKS)
    surface.write_to_png(path)


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--snapshot",
        nargs="?",
        const=DEFAULT_SNAPSHOT,
        default=None,
        metavar="PATH",
        help=f"render to PNG and exit (default: {DEFAULT_SNAPSHOT})",
    )
    p.add_argument("--width", type=int, default=720)
    p.add_argument("--height", type=int, default=480)
    args = p.parse_args()

    if args.snapshot:
        snapshot(args.snapshot, args.width, args.height)
        return

    win = AppWindow(BLOCKS)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
