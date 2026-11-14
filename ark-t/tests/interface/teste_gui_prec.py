"""Roteiro da pré-correção na interface, contra o simulador (xvfb-run)."""
import os, sys
sys.path.insert(0, os.path.abspath("."))
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk
from arkt import simulador, precorrecao as P, backup as B
from arkt.ui.app import App

SAIDA = sys.argv[1] if len(sys.argv) > 1 else "/tmp/capturas_prec"
os.makedirs(SAIDA, exist_ok=True)
eq, tcp, web = simulador.rodar(19021, 18191, em_thread=True)
app = App(("Simulador ARK-T", "127.0.0.1", 19021, 18191))
falhas = []

def checar(cond, msg):
    print(("ok   " if cond else "FALHA ") + msg, flush=True)
    if not cond:
        falhas.append(msg)

def foto(nome):
    w = app.get_active_window()
    pt = Gtk.WidgetPaintable.new(w)
    s = Gtk.Snapshot()
    pt.snapshot(s, w.get_width(), w.get_height())
    w.get_renderer().render_texture(s.to_node(), None).save_to_png(os.path.join(SAIDA, nome + ".png"))

def ir(w, pid):
    for i in range(40):
        r = w.lista_nav.get_row_at_index(i)
        if r is None: break
        if getattr(r, "id_pagina", None) == pid:
            w.lista_nav.select_row(r)

def passos():
    w = app.get_active_window()
    pag = w.pag_prec
    ir(w, "precorrecao"); yield 1.5
    foto("p1-entrada")
    pag._login(P.cmd_login("admin", "errado"), pag._entrou); yield 1.5
    checar(not pag.ativo, "senha errada não entra")
    pag._login(P.cmd_login("admin", "admin"), pag._entrou); yield 3
    checar(pag.ativo, "login e carga da pré-correção")
    checar(eq.st[731] & 1 == 1, "porta 5000 marcada como ocupada")
    checar(pag.pre is not None and pag.pre.nome == "SIMULADOR.dpre", "arquivo .dpre lido")
    checar(pag.canal is not None and pag.pot is not None, "canal %s potência %s" % (pag.canal, pag.pot))
    w.set_default_size(1280, 860); yield 1
    foto("p2-ampm")
    # edição AM: cria um ponto no meio
    ed = pag.ed_am
    ed.curva.controles.insert(1, [256, 900]); ed._recalcular(); ed.emit("alterada", True); yield 1.2
    esperado = P.am_para_equipamento(ed.pontos())
    recebido = eq.curvas.get("p0")
    rec = [(recebido[2*i] << 8) | recebido[2*i+1] for i in range(512)] if recebido else None
    checar(rec == list(esperado), "curva AM enviada (p0) confere")
    checar(pag.sujos, "marcado como não salvo")
    ed.sel = 1; ed._mouse = (400, 140); ed.queue_draw(); yield 0.5
    foto("p3-ampm-editado")
    # troca de canal pelo seletor
    if pag.dd_canal.get_sensitive() and len(pag.j.modelo.canais.saida) > 1:
        c0 = pag.canal
        pag.dd_canal.set_selected(1 if c0 != 1 else 0); yield 1.2
        checar(eq.st[523] == int(pag.j.modelo.canais.saida[1][0]) & 0xFF, "canal trocado (oo)")
        pag.dd_canal.set_selected(c0); yield 1.2
        checar(pag.canal == c0, "voltou ao canal %d" % c0)
    # linear
    pag.vs.set_visible_child_name("linear"); yield 1.5
    foto("p4-linear")
    em = pag.ed_mod
    em.curva.controles = sorted(em.curva.controles + [[1024, 2500]]); em._recalcular(); em.emit("alterada", True); yield 1.5
    coef = P.coeficientes_lineares(em.pontos(), pag.ed_fase.pontos())
    checar(eq.coef_lineares == coef, "coeficientes lineares enviados conferem")
    checar((pag._medida_hex or "").lower().startswith(coef.hex()), "resposta lida de volta (g0c)")
    foto("p5-linear-editado")
    # salvar AM/PM e linear
    pag._gravar(False, "TESTE_GUI"); yield 3
    d = simulador.ARQUIVOS.get("TESTE_GUI.dpre")
    checar(d is not None and "SIMULADOR.dpre" not in simulador.ARQUIVOS, "TESTE_GUI.dpre gravado (substitui o anterior)")
    if d:
        a = P.ArquivoPre.ler(d, "TESTE_GUI.dpre")
        c = pag._idx_arquivo(pag.canal)
        checar(a.am[c][pag.pot].controles == pag.pre.am[c][pag.pot].controles, "pontos salvos conferem")
        checar(list(a.curva_gravada(c, pag.pot, True)) == list(esperado), "curva salva confere")
    checar(not pag.sujos, "sem pendências após salvar")
    pag._gravar(True, "LIN_GUI"); yield 3
    dl = simulador.ARQUIVOS.get("LIN_GUI.dlin")
    checar(dl is not None and dl[2:770] == coef, "LIN_GUI.dlin gravado com os coeficientes")
    # backup e restauração
    prec, ref = B.escolher(list(simulador.ARQUIVOS))
    z = B.montar({n: simulador.ARQUIVOS[n] for n in prec}, {n: simulador.ARQUIVOS[n] for n in ref}, {"equipamento": "sim"})
    man, arqs = B.ler(z)
    checar(sorted(n for n, _ in arqs) == sorted(prec), "backup contém %s" % prec)
    simulador.ARQUIVOS["TESTE_GUI.dpre"] = b"estragado"
    w._restaurar(pag.trab, False, arqs); yield 4
    checar(simulador.ARQUIVOS.get("TESTE_GUI.dpre") == d, "restauração devolveu o arquivo original")
    # importar .sav
    w._enviar_sav(pag.trab, False, "NOVA.sav", b"[ARK-T]\r\n; importada\r\n"); yield 2.5
    checar("NOVA.sav" in simulador.ARQUIVOS and "config.sav" not in simulador.ARQUIVOS, "importação do .sav")
    foto("p6-final")
    pag._soltar(descartar=False); yield 1.5
    checar(eq.st[731] & 1 == 0, "porta 5000 liberada")
    foto("p7-liberado")

it = None
def tick():
    global it
    w = app.get_active_window()
    if w is None or getattr(w, "pag_prec", None) is None or w.modelo is None:
        return True
    if it is None:
        it = passos()
    try:
        dt = next(it)
    except StopIteration:
        print("FALHAS:", len(falhas), flush=True)
        app.quit()
        return False
    except Exception:
        import traceback; traceback.print_exc(); falhas.append("exceção"); app.quit(); return False
    GLib.timeout_add(int(dt * 1000), tick)
    return False

GLib.timeout_add(3000, lambda: (GLib.timeout_add(500, tick), False)[1])
app.run([sys.argv[0]])
sys.exit(1 if falhas else 0)
