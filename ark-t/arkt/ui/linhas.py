"""Linhas da interface: cada Campo do motor vira uma linha libadwaita."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import campos as C  # noqa: E402
from ..fmt import fmt_num, parse_num  # noqa: E402
from ..i18n import POR_NOME, item, titulo  # noqa: E402

CORES = {
    "#00ff00": "led-verde", "#0c7430": "led-verde",
    "#ff0000": "led-vermelho",
    "#ffff00": "led-amarelo", "#ffc800": "led-amarelo",
    "#0000ff": "led-azul",
}


def classe_cor(cor):
    return CORES.get((cor or "").lower(), "led-cinza")


def texto_led(cls):
    return {"led-verde": "Sim", "led-vermelho": "Alarme", "led-amarelo": "Atenção", "led-azul": "Sim"}.get(cls, "Não")


def rotulo_campo(c: C.Campo):
    t = c.title.strip() if c.title else ""
    if not t and c.name in POR_NOME:
        return POR_NOME[c.name]
    if not t and c.name:
        return POR_NOME.get(c.name, c.name)
    if t.isdigit():
        return "Destino de trap %s" % t
    return titulo(t)


class Linha:
    """Base: guarda o campo, o widget e o contexto (janela)."""
    escreve = False

    def __init__(self, campo, ctx):
        self.campo = campo
        self.ctx = ctx
        self.widget: Gtk.Widget = None
        self._pendente = False

    def visivel(self):
        return self.campo.enabled or self.ctx.mostrar_ocultos

    def atualizar(self, st):
        pass

    def set_editavel(self, ed):
        pass

    def _aplicar_visibilidade(self):
        self.widget.set_visible(self.visivel())


def _estilo_valor(label, v: C.Valor):
    for c in ("valor-standby", "valor-erro"):
        label.remove_css_class(c)
    if v.estado in ("standby", "desligado"):
        label.add_css_class("valor-standby")
    elif v.estado == "erro":
        label.add_css_class("valor-erro")


class LinhaValor(Linha):
    def __init__(self, campo, ctx):
        super().__init__(campo, ctx)
        self.widget = Adw.ActionRow(title=rotulo_campo(campo))
        self.lbl = Gtk.Label(xalign=1, selectable=True)
        self.lbl.add_css_class("valor")
        self.widget.add_suffix(self.lbl)

    def atualizar(self, st):
        self._aplicar_visibilidade()
        v = self.campo.ler(st)
        forcado = self.campo.extras.get("forcar_texto")
        txt = forcado if forcado is not None else v.texto
        if isinstance(self.campo, C.TextoEscolha):
            txt = item(txt)
        if v.estado == "standby" and not txt:
            txt = "—"
        self.lbl.set_text(txt or "")
        _estilo_valor(self.lbl, v)


class LinhaLed(Linha):
    def __init__(self, campo, ctx):
        super().__init__(campo, ctx)
        self.widget = Adw.ActionRow(title=rotulo_campo(campo))
        box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        self.ponto = Gtk.Label(label="●")
        self.ponto.add_css_class("led")
        self.lbl = Gtk.Label(xalign=1)
        self.lbl.add_css_class("dim-label")
        box.append(self.lbl)
        box.append(self.ponto)
        self.widget.add_suffix(box)
        self._cls = None

    def atualizar(self, st):
        self._aplicar_visibilidade()
        self.widget.set_title(rotulo_campo(self.campo))
        v = self.campo.ler(st)
        cls = "led-cinza" if v.estado in ("standby", "desligado") else classe_cor(v.cor)
        if cls != self._cls:
            if self._cls:
                self.ponto.remove_css_class(self._cls)
            self.ponto.add_css_class(cls)
            self._cls = cls
        self.lbl.set_text("—" if v.estado in ("standby", "desligado") else texto_led(cls))


class LinhaNivel(Linha):
    def __init__(self, campo, ctx):
        super().__init__(campo, ctx)
        self.widget = Adw.ActionRow(title=rotulo_campo(campo))
        self.barra = Gtk.LevelBar(min_value=0, max_value=63, valign=Gtk.Align.CENTER, width_request=160)
        self.lbl = Gtk.Label(xalign=1)
        self.lbl.add_css_class("valor")
        self.widget.add_suffix(self.lbl)
        self.widget.add_suffix(self.barra)

    def atualizar(self, st):
        v = self.campo.ler(st)
        self.lbl.set_text(v.texto)
        d = self.campo.dispositivo
        base = (d.defs.rflev_dig if d and d.config_em_uso(st) in (2, 4) else (d.defs.rflev_ana if d else -90)) or -90
        self.barra.set_value(max(0, min(63, (v.bruto or 0) - base)))


class LinhaEscolha(Linha):
    escreve = True

    def __init__(self, campo, ctx):
        super().__init__(campo, ctx)
        self.widget = Adw.ComboRow(title=rotulo_campo(campo))
        self.modelo = Gtk.StringList()
        self.widget.set_model(self.modelo)
        self._itens = None
        self._bloq = False
        self._sel = -1
        self.widget.connect("notify::selected", self._mudou)

    def _sincronizar_itens(self):
        itens = list(self.campo.items)
        if itens != self._itens:
            self._bloq = True
            self.modelo.splice(0, self.modelo.get_n_items(), [item(i) for i in itens] or ["—"])
            self._itens = itens
            self._bloq = False

    def atualizar(self, st):
        self._aplicar_visibilidade()
        self._sincronizar_itens()
        v = self.campo.ler(st)
        sel = v.bruto if isinstance(v.bruto, int) else -1
        self._pendente = False
        self.widget.remove_css_class("pendente")
        if sel != self._sel or self.widget.get_selected() != sel:
            self._bloq = True
            self.widget.set_selected(sel if sel >= 0 else Gtk.INVALID_LIST_POSITION)
            self._bloq = False
            self._sel = sel
        sub = ""
        if v.estado == "erro":
            sub = v.texto
        elif v.estado == "standby":
            sub = "Sem leitura no momento"
        self.widget.set_subtitle(sub)

    def set_editavel(self, ed):
        self.widget.set_sensitive(ed and self.campo.enabled)

    def _mudou(self, *a):
        if self._bloq:
            return
        novo = self.widget.get_selected()
        if novo == Gtk.INVALID_LIST_POSITION or novo == self._sel:
            return

        def desfazer():
            self._bloq = True
            self.widget.set_selected(self._sel if self._sel >= 0 else Gtk.INVALID_LIST_POSITION)
            self._bloq = False

        nome_novo = item(self.campo.items[novo]) if novo < len(self.campo.items) else str(novo)
        self.widget.add_css_class("pendente")
        self.ctx.escrever(self.campo, novo, descricao="%s → %s" % (rotulo_campo(self.campo), nome_novo),
                          ao_cancelar=desfazer)


class LinhaChave(Linha):
    escreve = True

    def __init__(self, campo, ctx):
        super().__init__(campo, ctx)
        self.widget = Adw.ActionRow(title=rotulo_campo(campo))
        self.sw = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.widget.add_suffix(self.sw)
        self.widget.set_activatable_widget(self.sw)
        self._bloq = False
        self.sw.connect("state-set", self._estado)

    def atualizar(self, st):
        self._aplicar_visibilidade()
        v = self.campo.ler(st)
        self._bloq = True
        self.sw.set_active(bool(v.ligado))
        self.sw.set_state(bool(v.ligado))
        self._bloq = False
        self.widget.set_subtitle("Sem leitura no momento" if v.estado == "standby" else "")

    def set_editavel(self, ed):
        self.sw.set_sensitive(ed and self.campo.enabled)

    def _estado(self, sw, quer):
        if self._bloq:
            return False
        atual = self.campo.on

        def desfazer():
            self._bloq = True
            sw.set_active(atual)
            sw.set_state(atual)
            self._bloq = False

        self.ctx.escrever(self.campo, quer, descricao="%s: %s" % (rotulo_campo(self.campo), "ligar" if quer else "desligar"),
                          ao_cancelar=desfazer)
        return True   # o estado real vem na próxima leitura


class LinhaBotaoLiga(LinhaChave):
    """MbButton3 / MbButtonRf: bit liga/desliga apresentado como chave."""

    def atualizar(self, st):
        self._aplicar_visibilidade()
        v = self.campo.ler(st)
        self._bloq = True
        self.sw.set_active(bool(v.ligado))
        self.sw.set_state(bool(v.ligado))
        self._bloq = False
        sub = v.texto
        if v.extra.get("rf_global_off"):
            sub = "RF desligado pelo equipamento"
        self.widget.set_subtitle(item(sub) if sub else "")


class LinhaEntrada(Linha):
    """Números, IPs e textos: campo editável + botão aplicar."""
    escreve = True

    def __init__(self, campo, ctx):
        super().__init__(campo, ctx)
        self.widget = Adw.ActionRow(title=rotulo_campo(campo))
        self.entry = Gtk.Entry(valign=Gtk.Align.CENTER, width_chars=14, max_width_chars=18, xalign=1)
        self.entry.add_css_class("valor")
        self.btn = Gtk.Button(icon_name="object-select-symbolic", valign=Gtk.Align.CENTER,
                              tooltip_text="Aplicar no equipamento")
        self.btn.add_css_class("flat")
        self.btn.set_visible(False)
        self.widget.add_suffix(self.entry)
        self.widget.add_suffix(self.btn)
        self.entry.connect("activate", lambda *a: self._aplicar())
        self.btn.connect("clicked", lambda *a: self._aplicar())
        self.entry.connect("changed", self._mudou)
        k = Gtk.EventControllerKey()
        k.connect("key-pressed", self._tecla)
        self.entry.add_controller(k)
        self._texto = ""
        self._bloq = False
        self._editando = False
        fx = campo.faixa()
        if fx and isinstance(campo, C.Decimal):
            self._faixa_txt = lambda: "Faixa: %s a %s" % (campo.formatar(campo.dmin), campo.formatar(campo.dmax))
        elif fx and isinstance(campo, C.Numero) and not isinstance(campo, C.NumeroTexto):
            self._faixa_txt = lambda: "Faixa: %s a %s" % (fmt_num(campo.minimo, 0), fmt_num(campo.maximo, 0))
        else:
            self._faixa_txt = lambda: ""

    def _tecla(self, ctl, keyval, code, state):
        from gi.repository import Gdk
        if keyval == Gdk.KEY_Escape:
            self._restaurar()
            return True
        return False

    def _restaurar(self):
        self._bloq = True
        self.entry.set_text(self._texto)
        self._bloq = False
        self._editando = False
        self.btn.set_visible(False)

    def _mudou(self, *a):
        if self._bloq:
            return
        self._editando = self.entry.get_text() != self._texto
        self.btn.set_visible(self._editando)

    def atualizar(self, st):
        self._aplicar_visibilidade()
        v = self.campo.ler(st)
        self._texto = v.texto
        self.widget.set_subtitle(self._faixa_txt() if self.ctx.modo_edicao else "")
        if not self._editando and self.entry.get_text() != v.texto:
            self._bloq = True
            self.entry.set_text(v.texto)
            self._bloq = False

    def set_editavel(self, ed):
        ok = ed and self.campo.enabled and not getattr(self.campo, "read_only", False)
        self.entry.set_editable(ok)
        self.entry.set_can_focus(ok)
        self.entry.set_has_frame(ok)
        if not ok:
            self._restaurar()
        self.widget.set_subtitle(self._faixa_txt() if ed else "")

    def _converter(self, t):
        c = self.campo
        if isinstance(c, (C.EnderecoIP, C.NumeroTexto)):
            return t.strip()
        if isinstance(c, C.Decimal):
            return parse_num(t)
        return parse_num(t, inteiro=True)

    def _aplicar(self):
        if not self.ctx.modo_edicao:
            self._restaurar()
            return
        t = self.entry.get_text()
        try:
            novo = self._converter(t)
        except ValueError:
            self.ctx.aviso("Valor inválido: %s" % t)
            return
        self._editando = False
        self.btn.set_visible(False)
        self.ctx.escrever(self.campo, novo, descricao="%s → %s" % (rotulo_campo(self.campo), t),
                          ao_cancelar=self._restaurar)


class LinhaDataHora(Linha):
    escreve = True

    def __init__(self, campo, ctx):
        super().__init__(campo, ctx)
        self.widget = Adw.ActionRow(title=rotulo_campo(campo))
        self.lbl = Gtk.Label(xalign=1)
        self.lbl.add_css_class("valor")
        self.btn = Gtk.Button(icon_name="document-edit-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Alterar")
        self.btn.add_css_class("flat")
        self.btn.connect("clicked", self._editar)
        self.widget.add_suffix(self.lbl)
        self.widget.add_suffix(self.btn)

    def atualizar(self, st):
        self._aplicar_visibilidade()
        self.lbl.set_text(self.campo.ler(st).texto)

    def set_editavel(self, ed):
        self.btn.set_visible(ed)

    def _editar(self, *a):
        atual = getattr(self.campo, "atual", [2000, 1, 1, 0, 0, 0])
        dlg = Adw.AlertDialog(heading=rotulo_campo(self.campo), body="Data e hora no relógio do equipamento.")
        grade = Gtk.Grid(column_spacing=6, row_spacing=6, halign=Gtk.Align.CENTER)
        nomes = ["Dia", "Mês", "Ano", "Hora", "Min", "Seg"]
        faixas = [(1, 31), (1, 12), (2000, 2099), (0, 23), (0, 59), (0, 59)]
        valores = [atual[2], atual[1], atual[0], atual[3], atual[4], atual[5]]
        spins = []
        for k, (n, (lo, hi), v) in enumerate(zip(nomes, faixas, valores)):
            grade.attach(Gtk.Label(label=n), k, 0, 1, 1)
            s = Gtk.SpinButton.new_with_range(lo, hi, 1)
            s.set_value(min(max(v, lo), hi))
            grade.attach(s, k, 1, 1, 1)
            spins.append(s)
        dlg.set_extra_child(grade)
        dlg.add_response("cancelar", "Cancelar")
        dlg.add_response("ok", "Aplicar")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)

        def resp(d, r):
            if r == "ok":
                d_, m, a, h, mi, s = [int(x.get_value()) for x in spins]
                self.ctx.escrever(self.campo, (a, m, d_, h, mi, s), descricao="%s → %02d/%02d/%04d %02d:%02d:%02d"
                                  % (rotulo_campo(self.campo), d_, m, a, h, mi, s))
        dlg.connect("response", resp)
        dlg.present(self.ctx.janela)


class LinhaComposto(Linha):
    """Estatísticas ASI/GbE/SDI e travas: linha expansível."""

    def __init__(self, campo, ctx):
        super().__init__(campo, ctx)
        self.widget = Adw.ExpanderRow(title=rotulo_campo(campo))
        self.ponto = Gtk.Label(label="●", valign=Gtk.Align.CENTER)
        self.ponto.add_css_class("led")
        self.widget.add_suffix(self.ponto)
        self.filhas = []
        for s in campo.subcampos:
            ln = LinhaLed(s, ctx) if isinstance(s, C.Led) else LinhaValor(s, ctx)
            self.filhas.append(ln)
            self.widget.add_row(ln.widget)
        self._cls = None

    def atualizar(self, st):
        self._aplicar_visibilidade()
        v = self.campo.ler(st)
        resumo = v.texto
        if isinstance(self.campo, (C.EstatisticaASI, C.EstatisticaGbE)) and v.ligado:
            br = self.campo.packet if isinstance(self.campo, C.EstatisticaASI) else self.campo.bitrate
            bv = br.ler(st)
            if isinstance(bv.bruto, (int, float)):
                resumo = "Travado — %s Mbit/s" % fmt_num(bv.bruto / 1e6 * (8 if isinstance(self.campo, C.EstatisticaGbE) else 1), 2)
        if v.estado == "standby":
            resumo = "Não usado no modo atual"
        self.widget.set_subtitle(item(resumo) if resumo else "")
        cls = "led-cinza" if (v.ligado is None or v.estado == "standby" or not v.ligado) else "led-verde"
        if isinstance(self.campo, C.TravaSTV) and not v.ligado:
            cls = "led-vermelho"
        if cls != self._cls:
            if self._cls:
                self.ponto.remove_css_class(self._cls)
            self.ponto.add_css_class(cls)
            self._cls = cls
        if self.widget.get_expanded():
            for f in self.filhas:
                f.atualizar(st)


def criar_linha(campo: C.Campo, ctx):
    if campo.tipo == "MbButtonEmpty3":
        return None   # ações (reset etc.) ficam no menu
    if campo.composto:
        return LinhaComposto(campo, ctx)
    if isinstance(campo, C.Led):
        return LinhaLed(campo, ctx)
    if isinstance(campo, C.BarraNivel):
        return LinhaNivel(campo, ctx)
    if isinstance(campo, C.Escolha):
        return LinhaEscolha(campo, ctx)
    if isinstance(campo, C.Botao):
        return LinhaBotaoLiga(campo, ctx)
    if isinstance(campo, C.Chave):
        return LinhaChave(campo, ctx)
    if isinstance(campo, C.DataHora):
        return LinhaDataHora(campo, ctx)
    if isinstance(campo, (C.Numero, C.EnderecoIP)):
        if isinstance(campo, C.EnderecoIP) and campo.read_only:
            return LinhaValor(campo, ctx)
        return LinhaEntrada(campo, ctx)
    return LinhaValor(campo, ctx)
