"""Abre o app contra o simulador, navega pelas páginas e salva PNGs."""
import os, sys
sys.path.insert(0, os.path.abspath("."))
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk
from arkt import simulador
from arkt.ui.app import App

SAIDA = sys.argv[1] if len(sys.argv) > 1 else "/tmp/capturas"
os.makedirs(SAIDA, exist_ok=True)
eq, tcp, web = simulador.rodar(19011, 18091, em_thread=True)
app = App(("Simulador ARK-T", "127.0.0.1", 19011, 18091))
estado = {"passo": 0}

def foto(nome):
    w = app.get_active_window()
    pt = Gtk.WidgetPaintable.new(w)
    s = Gtk.Snapshot()
    W, H = w.get_width(), w.get_height()
    pt.snapshot(s, W, H)
    node = s.to_node()
    tex = w.get_renderer().render_texture(node, None)
    tex.save_to_png(os.path.join(SAIDA, nome + ".png"))
    print("foto", nome, W, H, flush=True)

PAGINAS = os.environ.get("PAGINAS", "visao,geral,entrada,modos,modulacao,saida,rede,gps,alarmes,eventos").split(",")

def roteiro():
    w = app.get_active_window()
    if w is None or not hasattr(w, "lista_nav"):
        return True
    p = estado["passo"]
    if p == 0:
        if os.environ.get("EDICAO"):
            w.btn_edicao.set_active(True)
    if p < len(PAGINAS):
        pid = PAGINAS[p]
        for i in range(30):
            r = w.lista_nav.get_row_at_index(i)
            if r is None: break
            if r.id_pagina == pid:
                w.lista_nav.select_row(r)
        estado["passo"] += 1
        GLib.timeout_add(1500, lambda: (foto("%02d-%s" % (p, pid)), False)[1])
        return True
    GLib.timeout_add(1800, lambda: (app.quit(), False)[1])
    return False

def iniciar():
    GLib.timeout_add(2600, lambda: (GLib.timeout_add(1900, roteiro), False)[1])
    return False
GLib.idle_add(iniciar)
app.run([sys.argv[0]])
