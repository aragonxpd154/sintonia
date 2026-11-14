import os, sys
sys.path.insert(0, os.path.abspath("."))
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk
from arkt import simulador
from arkt.ui.app import App
eq, tcp, web = simulador.rodar(19041, 18121, em_thread=True)
app = App(("Simulador", "127.0.0.1", 19041, 18121))
SAIDA = "/tmp/cap4"; os.makedirs(SAIDA, exist_ok=True)
def foto(nome):
    w = app.get_active_window(); pt = Gtk.WidgetPaintable.new(w); s = Gtk.Snapshot()
    pt.snapshot(s, w.get_width(), w.get_height())
    w.get_renderer().render_texture(s.to_node(), None).save_to_png(os.path.join(SAIDA, nome + ".png"))
def linha(w, pid, var):
    for ln in w.paginas[pid].linhas:
        if ln.campo.var == var: return ln
passo = [0]
def roteiro():
    w = app.get_active_window()
    if w is None or not hasattr(w, "lista_nav"): return True
    p = passo[0]; passo[0] += 1
    if p == 0:
        for i in range(12):
            r = w.lista_nav.get_row_at_index(i)
            if r and r.id_pagina == "saida": w.lista_nav.select_row(r)
        w.btn_edicao.set_active(True)
    elif p == 1:
        ln = linha(w, "saida", "choInput6"); ln.widget.set_selected(2)          # Relé 0 -> RF Status
        e = linha(w, "saida", "mbNumericEmpty3_27"); e.entry.set_text("66"); e._mudou(); e._aplicar()
    elif p == 3:
        print("rele0 =", eq.st[566], " aviso temp =", eq.st[553], flush=True)
        foto("edicao")
        e = linha(w, "saida", "numPowerADbm"); e.entry.set_text("35,5"); e._mudou(); e._aplicar()
    elif p == 4:
        foto("confirmacao")
    elif p == 5:
        app.quit(); return False
    return True
GLib.timeout_add(3000, lambda: (GLib.timeout_add(2500, roteiro), False)[1])
app.run([sys.argv[0]])
