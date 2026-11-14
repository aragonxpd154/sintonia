"""Monta as páginas a partir da árvore de grupos/abas/campos do modelo."""
from __future__ import annotations

import re

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import campos as C  # noqa: E402
from ..i18n import item, titulo  # noqa: E402
from .linhas import LinhaEscolha, criar_linha, rotulo_campo  # noqa: E402

# ordem preferida dos grupos de primeiro nível (var do JPanel no Java)
ORDEM = {
    "saida": ["panActMode", "panRF", "panModeA", "panModeB", "panCenterFrequency", "panAGC", "panStatus",
              "panOptoRelay", "panFWDP", "panTempTher", "panGbe1", "panAsiOutLP"],
    "modos": ["panAutoMode", "panModA", "panSwitchA", "panModB", "panSwitchB", "panInputAutoswitch"],
}


class Bloco:
    def __init__(self, tipo, titulo="", var=""):
        self.tipo = tipo          # campos | abas | matriz
        self.titulo = titulo
        self.var = var
        self.nos = []             # campos
        self.abas = []            # [(titulo, [Bloco])]
        self.visivel = True


def _achatar(nos, titulo_pai, var_pai, saida, visivel=True):
    """Transforma a árvore em uma lista de blocos com título."""
    atual = Bloco("campos", titulo_pai, var_pai)
    atual.visivel = visivel

    def fechar():
        nonlocal atual
        if atual.nos:
            saida.append(atual)
        atual = Bloco("campos", titulo_pai, var_pai)
        atual.visivel = visivel

    for n in nos:
        if n.tipo == "campo":
            atual.nos.append(n)
        elif n.tipo == "grupo":
            vis = visivel and n.visivel
            if n.titulo:
                fechar()
                _achatar(n.filhos, titulo(n.titulo), n.var, saida, vis)
            else:
                # grupo sem título: se só tem campos, junta ao bloco atual
                if all(f.tipo == "campo" for f in n.filhos) and vis == visivel:
                    atual.nos.extend(n.filhos)
                else:
                    fechar()
                    _achatar(n.filhos, titulo_pai, n.var or var_pai, saida, vis)
        elif n.tipo == "abas":
            fechar()
            b = Bloco("abas", titulo_pai, n.var)
            for aba in n.filhos:
                sub = []
                _achatar(aba.filhos, "", "", sub)
                b.abas.append((titulo(aba.titulo.strip()), sub))
            saida.append(_talvez_matriz(b))
    fechar()
    return saida


def _talvez_matriz(b: Bloco):
    """Abas com os mesmos campos (Camada A/B/C) viram uma tabela."""
    if len(b.abas) < 2:
        return b
    seqs = []
    for _, blocos in b.abas:
        if len(blocos) != 1 or blocos[0].tipo != "campos":
            return b
        seqs.append([n.campo.title for n in blocos[0].nos])
    if all(s == seqs[0] for s in seqs) and seqs[0]:
        m = Bloco("matriz", (b.titulo + " — camadas") if b.titulo else "Camadas", b.var)
        m.abas = b.abas
        return m
    return b


def _ordenar(blocos, ordem):
    if not ordem:
        return blocos
    pos = {v: i for i, v in enumerate(ordem)}
    return sorted(blocos, key=lambda b: pos.get(b.var, len(ordem) + blocos.index(b)))


def _ordenar_destinos(nos):
    """Trap 0..7 vêm embaralhados no layout original."""
    if nos and all(n.campo.title.strip().isdigit() for n in nos):
        return sorted(nos, key=lambda n: int(n.campo.title.strip()))
    return nos


def _titulo_padrao(nos):
    cs = [n.campo for n in nos]
    if cs and all(isinstance(c, C.EstatisticaSDI) for c in cs):
        return "SDI"
    if cs and all("Equalizer" in (c.title or "") for c in cs):
        return "Equalizadores de entrada"
    return ""


class Pagina:
    """Uma tela: guarda as linhas para atualizar a cada leitura."""

    def __init__(self, tela, ctx):
        self.tela = tela
        self.ctx = ctx
        self.linhas = []
        self.grupos = []   # (widget, [linhas])
        self.widget = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=1280, tightening_threshold=900)
        self.caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18,
                             margin_top=18, margin_bottom=24, margin_start=18, margin_end=18)
        clamp.set_child(self.caixa)
        self.widget.set_child(clamp)
        blocos = _achatar(tela.raiz, "", "", [])
        blocos = _ordenar(blocos, ORDEM.get(tela.id))
        self._montar(blocos, self.caixa)

    def _montar(self, blocos, destino):
        fluxo = None
        for b in blocos:
            if b.tipo == "campos":
                if fluxo is None:
                    fluxo = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=False,
                                        min_children_per_line=1, max_children_per_line=2,
                                        column_spacing=18, row_spacing=18, valign=Gtk.Align.START)
                    destino.append(fluxo)
                g = self._grupo(b)
                if g is not None:
                    fluxo.append(g)
            else:
                fluxo = None
                w = self._matriz(b) if b.tipo == "matriz" else self._abas(b)
                destino.append(w)

    def _grupo(self, b: Bloco):
        g = Adw.PreferencesGroup(title=b.titulo or _titulo_padrao(b.nos), width_request=420, valign=Gtk.Align.START)
        linhas = []
        for n in _ordenar_destinos(b.nos):
            ln = criar_linha(n.campo, self.ctx)
            if ln is None:
                continue
            g.add(ln.widget)
            linhas.append(ln)
        if not linhas:
            return None
        self.linhas.extend(linhas)
        self.grupos.append((g, linhas, b.visivel))
        return g

    def _abas(self, b: Bloco):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        if b.titulo:
            lbl = Gtk.Label(label=b.titulo, xalign=0)
            lbl.add_css_class("heading")
            box.append(lbl)
        pilha = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vhomogeneous=False)
        sw = Gtk.StackSwitcher(stack=pilha, halign=Gtk.Align.START)
        box.append(sw)
        box.append(pilha)
        for tit, blocos in b.abas:
            interno = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
            self._montar(blocos, interno)
            pilha.add_titled(interno, None, tit)
        return box

    def _matriz(self, b: Bloco):
        quadro = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        if b.titulo:
            lbl = Gtk.Label(label=b.titulo, xalign=0)
            lbl.add_css_class("heading")
            quadro.append(lbl)
        cartao = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        cartao.add_css_class("card")
        grade = Gtk.Grid(column_spacing=24, row_spacing=10, column_homogeneous=False)
        grade.add_css_class("matriz")
        cartao.append(grade)
        quadro.append(cartao)
        for col, (tit, _) in enumerate(b.abas):
            h = Gtk.Label(label=tit, xalign=0)
            h.add_css_class("matriz-cabecalho")
            grade.attach(h, col + 1, 0, 1, 1)
        linhas_campos = list(zip(*[blocos[0].nos for _, blocos in b.abas]))
        for r, nos in enumerate(linhas_campos):
            lr = Gtk.Label(label=rotulo_campo(nos[0].campo), xalign=0, hexpand=False)
            lr.add_css_class("matriz-rotulo")
            grade.attach(lr, 0, r + 1, 1, 1)
            for col, n in enumerate(nos):
                cel = CelulaMatriz(n.campo, self.ctx)
                grade.attach(cel.widget, col + 1, r + 1, 1, 1)
                self.linhas.append(cel)
        return quadro

    def atualizar(self, st):
        for ln in self.linhas:
            try:
                ln.atualizar(st)
            except Exception as e:  # noqa: BLE001
                print("erro ao atualizar", ln.campo, e)
        for g, linhas, vis in self.grupos:
            g.set_visible(vis and any(ln.widget.get_visible() for ln in linhas))

    def set_editavel(self, ed):
        for ln in self.linhas:
            ln.set_editavel(ed)


class CelulaMatriz:
    """Célula da tabela de camadas: texto (somente leitura) ou lista."""

    def __init__(self, campo, ctx):
        self.campo = campo
        self.ctx = ctx
        self.escolha = isinstance(campo, C.Escolha) and campo.command is not None
        if self.escolha:
            self.modelo = Gtk.StringList()
            self.widget = Gtk.DropDown(model=self.modelo, hexpand=True)
            self._itens = None
            self._sel = -1
            self._bloq = False
            self.widget.connect("notify::selected", self._mudou)
        else:
            self.widget = Gtk.Label(xalign=0, hexpand=True, selectable=True)
            self.widget.add_css_class("valor")

    def atualizar(self, st):
        v = self.campo.ler(st)
        if not self.escolha:
            self.widget.set_text(item(v.texto) if v.texto else "—")
            return
        itens = list(self.campo.items)
        if itens != self._itens:
            self._bloq = True
            self.modelo.splice(0, self.modelo.get_n_items(), [item(i) for i in itens])
            self._itens = itens
            self._bloq = False
        sel = v.bruto if isinstance(v.bruto, int) else -1
        if sel != self._sel:
            self._bloq = True
            self.widget.set_selected(sel if sel >= 0 else Gtk.INVALID_LIST_POSITION)
            self._bloq = False
            self._sel = sel

    def set_editavel(self, ed):
        if self.escolha:
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

        self.ctx.escrever(self.campo, novo, descricao="%s → %s" % (rotulo_campo(self.campo), item(self.campo.items[novo])),
                          ao_cancelar=desfazer)


_ = (LinhaEscolha, re)
