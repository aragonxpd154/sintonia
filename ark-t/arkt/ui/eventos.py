"""Histórico de eventos com filtro, busca e exportação."""
from __future__ import annotations

import csv
import io

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import eventos as E  # noqa: E402

FILTROS = [("todos", "Todos"), (E.TIPO_ALARME, "Alarmes"), (E.TIPO_EVENTO, "Eventos"),
           (E.TIPO_COMANDO, "Comandos"), (E.TIPO_INICIO, "Inicializações")]
ICONES = {E.TIPO_ALARME: ("dialog-warning-symbolic", "evento-alarme"),
          E.TIPO_COMANDO: ("utilities-terminal-symbolic", "evento-comando"),
          E.TIPO_INICIO: ("system-reboot-symbolic", "evento-inicio"),
          E.TIPO_EVENTO: ("emblem-ok-symbolic", None),
          E.TIPO_DESCONHECIDO: ("dialog-question-symbolic", None)}


class PaginaEventos:
    def __init__(self, ctx):
        self.ctx = ctx
        self.eventos: list[E.Evento] = []
        self.filtro = "todos"
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        topo = Gtk.Box(spacing=8, margin_top=18, margin_start=18, margin_end=18, margin_bottom=8)
        t = Gtk.Label(label="Histórico de eventos", xalign=0, hexpand=True)
        t.add_css_class("titulo-tela")
        topo.append(t)
        self.total = Gtk.Label()
        self.total.add_css_class("dim-label")
        topo.append(self.total)
        self.widget.append(topo)

        barra = Gtk.Box(spacing=8, margin_start=18, margin_end=18, margin_bottom=8)
        caixa_f = Gtk.Box()
        caixa_f.add_css_class("linked")
        primeiro = None
        for chave, nome in FILTROS:
            b = Gtk.ToggleButton(label=nome)
            if primeiro is None:
                primeiro = b
                b.set_active(True)
            else:
                b.set_group(primeiro)
            b.connect("toggled", self._filtro, chave)
            caixa_f.append(b)
        barra.append(caixa_f)
        self.busca = Gtk.SearchEntry(placeholder_text="Buscar no histórico", hexpand=True)
        self.busca.connect("search-changed", lambda *a: self._refiltrar())
        barra.append(self.busca)
        self.btn_atualizar = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Baixar o histórico de novo")
        self.btn_atualizar.connect("clicked", lambda *a: self.ctx.recarregar_eventos())
        barra.append(self.btn_atualizar)
        self.btn_exportar = Gtk.Button(label="Exportar…")
        self.btn_exportar.connect("clicked", self._exportar)
        barra.append(self.btn_exportar)
        self.btn_limpar = Gtk.Button(label="Limpar")
        self.btn_limpar.add_css_class("destructive-action")
        self.btn_limpar.connect("clicked", self._limpar)
        barra.append(self.btn_limpar)
        self.widget.append(barra)

        sc = Gtk.ScrolledWindow(vexpand=True)
        self.lista = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, margin_start=18, margin_end=18,
                                 margin_bottom=18, valign=Gtk.Align.START)
        self.lista.add_css_class("boxed-list")
        self.lista.set_filter_func(self._passa)
        sc.set_child(self.lista)
        self.widget.append(sc)
        self.vazio = Adw.StatusPage(icon_name="document-open-recent-symbolic", title="Baixando histórico…", vexpand=True)
        self.widget.append(self.vazio)
        self.set_editavel(False)

    def set_editavel(self, ed):
        self.btn_limpar.set_sensitive(ed)

    def carregando(self):
        self.vazio.set_title("Baixando histórico…")
        self.vazio.set_visible(not self.eventos)

    def definir(self, eventos):
        self.eventos = eventos
        while (r := self.lista.get_row_at_index(0)) is not None:
            self.lista.remove(r)
        for ev in eventos:
            self.lista.append(self._linha(ev))
        self.total.set_text("%d eventos" % len(eventos))
        self.vazio.set_title("Nenhum evento registrado")
        self.vazio.set_visible(not eventos)
        self.lista.get_parent().get_parent().set_visible(bool(eventos))

    def _linha(self, ev):
        row = Adw.ActionRow(title=GLib.markup_escape_text(ev.texto), subtitle="%s  %s" % (ev.data, ev.hora))
        row.set_title_lines(3)
        icone, cls = ICONES.get(ev.tipo, ICONES[E.TIPO_DESCONHECIDO])
        img = Gtk.Image(icon_name=icone)
        if cls:
            img.add_css_class(cls)
        row.add_prefix(img)
        row.evento = ev
        return row

    def _filtro(self, b, chave):
        if b.get_active():
            self.filtro = chave
            self._refiltrar()

    def _refiltrar(self):
        self.lista.invalidate_filter()

    def _passa(self, row):
        ev = getattr(row.get_child(), "evento", None) or getattr(row, "evento", None)
        if ev is None:
            return True
        if self.filtro != "todos" and ev.tipo != self.filtro:
            return False
        q = self.busca.get_text().strip().lower()
        return not q or q in ev.texto.lower() or q in ev.data

    def _exportar(self, *a):
        if not self.eventos:
            self.ctx.aviso("O histórico está vazio")
            return
        dlg = Gtk.FileDialog(title="Exportar histórico", initial_name="eventos-%s.csv" % self.ctx.endereco.replace(":", "_"))
        filtro_csv = Gtk.FileFilter(name="Planilha CSV")
        filtro_csv.add_pattern("*.csv")
        filtro_log = Gtk.FileFilter(name="Texto (.log, igual ao programa antigo)")
        filtro_log.add_pattern("*.log")
        lst = Gio.ListStore.new(Gtk.FileFilter)
        lst.append(filtro_csv)
        lst.append(filtro_log)
        dlg.set_filters(lst)

        def fim(d, res):
            try:
                f = d.save_finish(res)
            except GLib.Error:
                return
            caminho = f.get_path()
            if caminho.endswith(".log"):
                texto = "".join("Last Event: %s\n" % e.linha() for e in self.eventos)
            else:
                if not caminho.endswith(".csv"):
                    caminho += ".csv"
                buf = io.StringIO()
                w = csv.writer(buf, delimiter=";")
                w.writerow(["data", "hora", "tipo", "descricao"])
                for e in self.eventos:
                    w.writerow([e.data, e.hora, e.tipo, e.texto])
                texto = buf.getvalue()
            with open(caminho, "w", encoding="utf-8") as fh:
                fh.write(texto)
            self.ctx.aviso("Histórico exportado para %s" % caminho)
        dlg.save(self.ctx.janela, None, fim)

    def _limpar(self, *a):
        self.ctx.enviar_bruto("xq\r\n", 3, "Apagar o histórico de eventos do equipamento", confirmar=True,
                              corpo="Todos os eventos gravados no ARK-T serão apagados. Exporte antes se precisar.",
                              destrutivo=True, ao_fim=lambda: self.ctx.recarregar_eventos())
