"""Aplicação GTK."""
from __future__ import annotations

import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, Gtk  # noqa: E402

from .. import APP_ID  # noqa: E402
from .janela import Janela  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))


class App(Adw.Application):
    def __init__(self, alvo=None):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.alvo = alvo

    def do_startup(self):
        Adw.Application.do_startup(self)
        css = Gtk.CssProvider()
        css.load_from_path(os.path.join(AQUI, "estilo.css"))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        tema = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        icones = os.path.join(os.path.dirname(AQUI), "data", "icons")
        if os.path.isdir(icones):
            tema.add_search_path(icones)
        Gtk.Window.set_default_icon_name(APP_ID)

    def do_activate(self):
        Janela(self, self.alvo).present()


def rodar(alvo=None):
    return App(alvo).run([sys.argv[0]])
