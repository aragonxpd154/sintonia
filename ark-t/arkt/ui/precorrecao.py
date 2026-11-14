"""Página de pré-correção (MbPanPrecB + MbPanLinearPrecB do original).

Tudo aqui passa pela porta 5000, que só aceita um cliente por vez e tem
login próprio (usuário e senha diferentes do resto do equipamento).
"""
from __future__ import annotations

import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .. import campos as C  # noqa: E402
from .. import precorrecao as P  # noqa: E402
from ..arquivos import lista_de_arquivos, procurar  # noqa: E402
from ..protocolo import baixar_http  # noqa: E402
from .curvas import EditorCurva  # noqa: E402

NOME_MAX = 26
AJUDA = ("Clique num espaço vazio para criar um ponto, arraste para mover, botão direito ou Delete apaga. "
         "Setas movem o ponto selecionado (Shift = passo maior). A rolagem do mouse aproxima o eixo "
         "vertical e o botão do meio volta à escala inteira.")


def _caixa(rotulo, filho):
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    lb = Gtk.Label(label=rotulo, xalign=0)
    lb.add_css_class("caption-heading")
    lb.add_css_class("dim-label")
    b.append(lb)
    b.append(filho)
    return b


def _rotulo_am(y):
    return "%d" % round(P.AM.vmax - y)


def _rotulo_pm(y):
    return "%d" % round(P.PM.vmax - y)


def _amostra(x):
    return "%d" % round(x)


def _sem_menos_zero(v, casas):
    v = round(v, casas)
    return 0.0 if v == 0 else v


def _rot_db(y):
    return "%+.2f dB" % _sem_menos_zero(P.y_para_db(y), 2)


def _rot_ns(y):
    return "%+.0f ns" % _sem_menos_zero(P.y_para_ns(y), 0)


def _rot_mhz(x):
    return "%+.2f MHz" % P.x_para_mhz(x)


def _nome_valido(n):
    return 0 < len(n) <= NOME_MAX and all(c.isalnum() or c in "_-" for c in n)


class PaginaPrecorrecao:
    def __init__(self, janela):
        self.j = janela
        self.m = janela.modelo
        self.trab: P.Trabalhador5000 | None = None
        self.ativo = False
        self.lista = []
        self.digital = True
        self.ext_pre = ".dpre"
        self.ext_lin = ".dlin"
        self.pre: P.ArquivoPre | None = None
        self.pre_gravado: P.ArquivoPre | None = None
        self.lin: P.ArquivoLinear | None = None
        self.lin_gravado: P.ArquivoLinear | None = None
        self.sujos = set()
        self.lin_sujo = False
        self.canal = None
        self.pot = None
        self._mudanca_local = 0.0
        self._ignorar = False
        self._medida_hex = None

        self.widget = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self._montar_entrada()
        self._montar_editor()
        self.widget.set_visible_child_name("entrada")

    # ================================================================ montagem
    def _montar_entrada(self):
        st = Adw.StatusPage(icon_name="arkt-curva-symbolic", title="Pré-correção",
                            description="Curvas AM/AM e AM/PM por canal e potência, e a pré-correção linear "
                                        "(módulo e atraso de grupo).\nUsa a porta 5000, que aceita um "
                                        "computador por vez e tem usuário e senha próprios.")
        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER)
        self.btn_entrar = Gtk.Button(label="Entrar…")
        self.btn_entrar.add_css_class("pill")
        self.btn_entrar.add_css_class("suggested-action")
        self.btn_entrar.connect("clicked", lambda *a: self.pedir_login(self._entrou))
        caixa.append(self.btn_entrar)
        b2 = Gtk.Button(label="Trocar usuário e senha…")
        b2.add_css_class("flat")
        b2.connect("clicked", lambda *a: self.trocar_senha())
        caixa.append(b2)
        self.lbl_ocupada = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=50)
        self.lbl_ocupada.add_css_class("warning")
        self.lbl_ocupada.set_visible(False)
        caixa.append(self.lbl_ocupada)
        st.set_child(caixa)
        self.widget.add_named(st, "entrada")

        sp = Adw.StatusPage(title="Lendo a pré-correção do equipamento…")
        sp.set_child(Gtk.Spinner(spinning=True, width_request=32, height_request=32, halign=Gtk.Align.CENTER))
        self.widget.add_named(sp, "carregando")

    def _montar_editor(self):
        raiz = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        barra = Gtk.Box(spacing=8, margin_start=12, margin_end=12, margin_top=8, margin_bottom=4)
        self.vs = Adw.ViewStack()
        sw = Adw.ViewSwitcher(stack=self.vs, policy=Adw.ViewSwitcherPolicy.WIDE)
        barra.append(sw)
        barra.append(Gtk.Box(hexpand=True))
        self.lbl_sessao = Gtk.Label(xalign=1)
        self.lbl_sessao.add_css_class("dim-label")
        self.lbl_sessao.add_css_class("caption")
        barra.append(self.lbl_sessao)
        b = Gtk.Button(label="Liberar porta 5000…", tooltip_text="Sai da pré-correção e libera a porta 5000")
        b.connect("clicked", lambda *a: self.liberar())
        barra.append(b)
        raiz.append(barra)
        self.banner = Adw.Banner()
        raiz.append(self.banner)

        self.vs.add_titled_with_icon(self._aba_ampm(), "ampm", "AM/PM", "arkt-curva-symbolic")
        self.vs.add_titled_with_icon(self._aba_linear(), "linear", "Linear", "arkt-modulacao-symbolic")
        self.vs.set_vexpand(True)
        raiz.append(self.vs)

        self.rev_prog = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP)
        bp = Gtk.Box(spacing=12, margin_start=12, margin_end=12, margin_top=6, margin_bottom=8)
        self.lbl_prog = Gtk.Label(xalign=0)
        bp.append(self.lbl_prog)
        self.barra_prog = Gtk.ProgressBar(hexpand=True, valign=Gtk.Align.CENTER)
        bp.append(self.barra_prog)
        self.rev_prog.set_child(bp)
        raiz.append(self.rev_prog)
        self.widget.add_named(raiz, "editor")

    def _cartao_editor(self, ed, extras=()):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card.add_css_class("card")
        card.add_css_class("cartao-curva")
        card.append(ed)
        linha = Gtk.Box(spacing=6, margin_start=10, margin_end=10, margin_bottom=10)
        modo = Gtk.Box(css_classes=["linked"])
        b_lin = Gtk.ToggleButton(label="Linear", active=True)
        b_pol = Gtk.ToggleButton(label="Polinomial", group=b_lin)
        modo.append(b_lin)
        modo.append(b_pol)
        ed.btn_lin, ed.btn_pol = b_lin, b_pol

        def mudou_modo(btn, novo):
            if btn.get_active() and not self._ignorar and ed.curva.modo != novo:
                ed.set_modo(novo)
        b_lin.connect("toggled", mudou_modo, P.LINEAR)
        b_pol.connect("toggled", mudou_modo, P.POLINOMIAL)
        linha.append(modo)
        linha.append(Gtk.Box(hexpand=True))
        for w in extras:
            linha.append(w)
        b_zoom = Gtk.Button(icon_name="arkt-escala-symbolic", tooltip_text="Escala vertical inteira")
        b_zoom.add_css_class("flat")
        b_zoom.connect("clicked", lambda *a: ed.restaurar_vista())
        linha.append(b_zoom)
        b_limpar = Gtk.Button(label="Limpar", tooltip_text="Volta a curva para uma reta")
        b_limpar.connect("clicked", lambda *a: self.limpar(ed))
        linha.append(b_limpar)
        card.append(linha)
        return card

    def _grade(self, *cards):
        fb = Gtk.FlowBox(min_children_per_line=1, max_children_per_line=2, homogeneous=True,
                         selection_mode=Gtk.SelectionMode.NONE, column_spacing=12, row_spacing=12)
        for c in cards:
            fb.append(c)
            c.get_parent().set_focusable(False)
        return fb

    def _acoes(self, botoes):
        b = Gtk.Box(spacing=8, halign=Gtk.Align.END)
        for rot, fn, estilo, dica in botoes:
            bt = Gtk.Button(label=rot, tooltip_text=dica)
            if estilo:
                bt.add_css_class(estilo)
            bt.connect("clicked", lambda *a, f=fn: f())
            b.append(bt)
        return b

    def _aba_ampm(self):
        cx = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_start=12, margin_end=12,
                     margin_top=8, margin_bottom=12)
        topo = Gtk.Box(spacing=18)
        self.dd_canal = Gtk.DropDown(model=Gtk.StringList())
        self.dd_canal.connect("notify::selected", self._canal_escolhido)
        topo.append(_caixa("Canal", self.dd_canal))
        self.dd_pot = Gtk.DropDown(model=Gtk.StringList())
        self.dd_pot.connect("notify::selected", self._pot_escolhida)
        topo.append(_caixa("Potência", self.dd_pot))
        self.sw_vivo = Gtk.Switch(active=True, valign=Gtk.Align.CENTER, halign=Gtk.Align.START,
                                  tooltip_text="Envia a curva enquanto você arrasta (como o original). "
                                               "Desligado, envia só ao soltar o ponto.")
        topo.append(_caixa("Ao vivo", self.sw_vivo))
        topo.append(Gtk.Box(hexpand=True))
        self.lbl_arq_pre = Gtk.Label(xalign=1, ellipsize=3, max_width_chars=48, valign=Gtk.Align.END)
        self.lbl_arq_pre.add_css_class("dim-label")
        topo.append(self.lbl_arq_pre)
        cx.append(topo)

        self.ed_am = EditorCurva(P.AM, "AM/AM", _rotulo_am, _amostra, 320)
        self.ed_pm = EditorCurva(P.PM, "AM/PM", _rotulo_pm, _amostra, 320)
        for ed, am in ((self.ed_am, True), (self.ed_pm, False)):
            ed.connect("alterada", self._curva_alterada, am)
        cx.append(self._grade(self._cartao_editor(self.ed_am), self._cartao_editor(self.ed_pm)))
        ajuda = Gtk.Label(label=AJUDA, wrap=True, xalign=0)
        ajuda.add_css_class("dim-label")
        ajuda.add_css_class("caption")
        cx.append(ajuda)
        cx.append(self._acoes([
            ("Restaurar do arquivo", self.restaurar_ampm, None,
             "Descarta a edição deste canal/potência e o equipamento volta à curva gravada"),
            ("Exportar…", lambda: self.exportar(False), None, "Salva o arquivo neste computador"),
            ("Salvar como…", lambda: self.salvar(False, True), None, None),
            ("Salvar no equipamento", lambda: self.salvar(False), "suggested-action",
             "Grava todas as curvas no arquivo do equipamento"),
        ]))
        sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        sc.set_child(cx)
        return sc

    def _aba_linear(self):
        cx = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_start=12, margin_end=12,
                     margin_top=8, margin_bottom=12)
        topo = Gtk.Box(spacing=18)
        self.sw_vivo_lin = Gtk.Switch(active=True, valign=Gtk.Align.CENTER, halign=Gtk.Align.START,
                                      tooltip_text="Envia os coeficientes enquanto você arrasta")
        topo.append(_caixa("Ao vivo", self.sw_vivo_lin))
        topo.append(Gtk.Box(hexpand=True))
        self.lbl_arq_lin = Gtk.Label(xalign=1, ellipsize=3, max_width_chars=48, valign=Gtk.Align.END)
        self.lbl_arq_lin.add_css_class("dim-label")
        topo.append(self.lbl_arq_lin)
        cx.append(topo)
        self.ed_mod = EditorCurva(P.MODULO, "Módulo", _rot_db, _rot_mhz, 340)
        self.ed_fase = EditorCurva(P.FASE, "Atraso de grupo", _rot_ns, _rot_mhz, 340)
        for ed in (self.ed_mod, self.ed_fase):
            ed.connect("alterada", self._linear_alterada)
        cx.append(self._grade(self._cartao_editor(self.ed_mod), self._cartao_editor(self.ed_fase)))
        nota = Gtk.Label(wrap=True, xalign=0,
                         label="Em vermelho, a resposta calculada a partir dos coeficientes que o equipamento "
                               "está usando agora (o nível do módulo é relativo: os coeficientes são "
                               "normalizados). " + AJUDA)
        nota.add_css_class("dim-label")
        nota.add_css_class("caption")
        cx.append(nota)
        cx.append(self._acoes([
            ("Ler do equipamento", self.ler_resposta, None, "Atualiza a curva vermelha"),
            ("Restaurar do arquivo", self.restaurar_linear, None,
             "Descarta a edição e o equipamento volta aos coeficientes gravados"),
            ("Exportar…", lambda: self.exportar(True), None, "Salva o arquivo neste computador"),
            ("Salvar como…", lambda: self.salvar(True, True), None, None),
            ("Salvar no equipamento", lambda: self.salvar(True), "suggested-action", None),
        ]))
        sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        sc.set_child(cx)
        return sc

    # ================================================================ interface da página
    def set_editavel(self, b):
        pass

    def atualizar(self, st):
        if not self.ativo:
            ocupada = P.porta5000_ocupada(st) and self.trab is None
            self.lbl_ocupada.set_label("A porta 5000 está em uso por outro computador ou programa. "
                                       "Só é possível entrar quando ela for liberada.")
            self.lbl_ocupada.set_visible(ocupada)
            self.btn_entrar.set_sensitive(not ocupada)
            return
        if time.time() - self._mudanca_local < 4 or self.pre is None:
            return
        c, p = self._canal_pot_status(st)
        if (c, p) != (self.canal, self.pot):
            self._definir_canal_pot(c, p)

    def encerrar(self):
        """Janela fechando ou trocando de equipamento: solta a porta 5000."""
        if self.trab is not None:
            self.trab.ao_queda = None
            self.trab.fechar()
            self.trab = None
        self.ativo = False

    # ================================================================ login
    def pedir_login(self, continuar, titulo="Entrar na pré-correção"):
        dlg = Adw.AlertDialog(heading=titulo,
                              body="Usuário e senha da pré-correção (até 15 caracteres).")
        lista = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        lista.add_css_class("boxed-list")
        e_user = Adw.EntryRow(title="Usuário")
        e_pass = Adw.PasswordEntryRow(title="Senha")
        lista.append(e_user)
        lista.append(e_pass)
        dlg.set_extra_child(lista)
        dlg.add_response("cancelar", "Cancelar")
        dlg.add_response("entrar", "Entrar")
        dlg.set_response_appearance("entrar", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("entrar")
        dlg.set_close_response("cancelar")
        def ativou(*a):
            dlg.close()
            resp(dlg, "entrar")
        e_pass.connect("entry-activated", ativou)
        e_user.connect("entry-activated", lambda *a: e_pass.grab_focus())

        def resp(d, r):
            if r != "entrar":
                return
            u, s = e_user.get_text(), e_pass.get_text()
            if len(u) >= 16 or len(s) >= 16:
                self.j.aviso("Usuário e senha têm no máximo 15 caracteres", 5)
                return
            self._login(P.cmd_login(u, s), continuar)
        dlg.connect("response", resp)
        dlg.present(self.j)
        GLib.idle_add(lambda: e_user.grab_focus() and False)

    def trocar_senha(self):
        dlg = Adw.AlertDialog(heading="Trocar usuário e senha",
                              body="Novo usuário e nova senha: de 4 a 15 caracteres.")
        lista = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        lista.add_css_class("boxed-list")
        campos = [Adw.EntryRow(title="Usuário atual"), Adw.PasswordEntryRow(title="Senha atual"),
                  Adw.EntryRow(title="Novo usuário"), Adw.PasswordEntryRow(title="Nova senha"),
                  Adw.PasswordEntryRow(title="Repita a nova senha")]
        for c in campos:
            lista.append(c)
        dlg.set_extra_child(lista)
        dlg.add_response("cancelar", "Cancelar")
        dlg.add_response("trocar", "Trocar e entrar")
        dlg.set_response_appearance("trocar", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_close_response("cancelar")

        def resp(d, r):
            if r != "trocar":
                return
            u, s, nu, ns, ns2 = (c.get_text() for c in campos)
            if ns != ns2:
                self.j.aviso("As duas senhas novas não conferem", 5)
                return
            try:
                cmd = P.cmd_trocar_senha(u, s, nu, ns)
            except P.ErroPrecorrecao as e:
                self.j.aviso(str(e), 5)
                return
            self._login(cmd, self._entrou)
        dlg.connect("response", resp)
        dlg.present(self.j)

    def _login(self, cmd, continuar):
        cli = self.j.cliente
        if cli is None:
            return

        def f(c):
            r = c.comando(C.Cmd(cmd, 4))
            st = c.status()
            lista = lista_de_arquivos(c.pergunta("yh\n\r"))
            return r, st, lista

        def fim(res):
            GLib.idle_add(self._resposta_login, res, continuar)

        def erro(e):
            GLib.idle_add(self.j.aviso, "Falha no login: %s" % e, 6)
        cli.executar(f, fim, erro, ler_status=False)

    def _resposta_login(self, res, continuar):
        r, st, lista = res
        if P.porta5000_ocupada(st):
            self.j.aviso("A porta 5000 está em uso por outro computador — tente depois", 6)
            return False
        if len(r) < 4 or r[3] != ord("y"):
            self.j.aviso("Usuário ou senha incorretos", 5)
            return False
        self.lista = lista
        continuar()
        return False

    def _novo_trabalhador(self):
        t = P.Trabalhador5000(self.j.cliente.host, self.j.porta_prec)
        return t

    # ================================================================ sessão
    def _entrou(self):
        self.encerrar()
        self.trab = self._novo_trabalhador()
        self.trab.ao_queda = lambda msg: GLib.idle_add(self._caiu, msg)
        self.recarregar()

    def recarregar(self):
        """Lê de novo os arquivos de pré-correção do equipamento."""
        if self.trab is None:
            return
        m = self.j.modelo
        cfg = m.config_em_uso()
        self.digital = cfg not in (0, 3)                    # StateHolder.isDigital()
        self.ext_pre = ".dpre" if self.digital else ".apre"
        self.ext_lin = ".dlin" if cfg in (2, 4) else ".alin"  # Switcher (linear)
        self.widget.set_visible_child_name("carregando")
        host, porta_http = self.j.cliente.host, self.j.cliente.porta_http
        lista = self.lista

        def f(s):
            out = {}
            for chave, ext in (("pre", self.ext_pre), ("lin", self.ext_lin)):
                nome = procurar(lista, ext)
                out[chave] = (nome, baixar_http(host, nome, porta_http) if nome else None)
            out["coef"] = s.ler_coeficientes()
            return out

        self.trab.executar(f, lambda d: GLib.idle_add(self._carregado, d),
                           lambda e: GLib.idle_add(self._falha_carga, e))

    def _falha_carga(self, e):
        self.encerrar()
        self.rev_prog.set_reveal_child(False)
        self.widget.set_visible_child_name("entrada")
        self.j.aviso("Não foi possível abrir a pré-correção: %s" % e, 8)
        return False

    def _caiu(self, msg):
        self.trab = None
        self.ativo = False
        self.widget.set_visible_child_name("entrada")
        self.rev_prog.set_reveal_child(False)
        if self.j.cliente is not None:
            self.j.cliente.retomar()
        self.j.aviso("A conexão da porta 5000 caiu: %s" % msg, 8)
        return False

    def _carregado(self, d):
        m = self.j.modelo
        avisos = []
        canais = m.canais
        passos = (m.passos_dpwr if self.digital else m.passos_apwr) or []
        nome, dados = d["pre"]
        self.pre = None
        if dados:
            try:
                self.pre = P.ArquivoPre.ler(dados, nome, self.digital)
                self.pre_gravado = P.ArquivoPre.ler(dados, nome, self.digital)
            except Exception as e:  # noqa: BLE001
                avisos.append("%s inválido (%s)" % (nome, e))
        if self.pre is None and canais is not None and passos:
            self.pre = P.ArquivoPre(len(passos), len(canais.saida), digital=self.digital)
            self.pre_gravado = P.ArquivoPre(len(passos), len(canais.saida), digital=self.digital)
            avisos.append("o equipamento não tem arquivo %s: começando com curvas planas" % self.ext_pre)
        if self.pre is not None and canais is not None and self.pre.n_can != len(canais.saida):
            avisos.append("a canalização mudou desde que %s foi gravado (%d canais no arquivo, %d no .cdef): "
                          "ao salvar, os canais serão ajustados" % (nome, self.pre.n_can, len(canais.saida)))
        nome_l, dados_l = d["lin"]
        try:
            self.lin = P.ArquivoLinear.ler(dados_l, nome_l, self.ext_lin == ".dlin") if dados_l \
                else P.ArquivoLinear(digital=self.ext_lin == ".dlin")
            self.lin_gravado = P.ArquivoLinear.ler(dados_l, nome_l, self.ext_lin == ".dlin") if dados_l \
                else P.ArquivoLinear(digital=self.ext_lin == ".dlin")
        except Exception as e:  # noqa: BLE001
            avisos.append("%s inválido (%s)" % (nome_l, e))
            self.lin = P.ArquivoLinear(digital=self.ext_lin == ".dlin")
            self.lin_gravado = P.ArquivoLinear(digital=self.ext_lin == ".dlin")
        if not dados_l:
            avisos.append("o equipamento não tem arquivo %s" % self.ext_lin)
        self.sujos.clear()
        self.lin_sujo = False
        self.ativo = True

        # escolhas de canal e potência (Initializer.initialize / setPowerRanges)
        sa = m.defs.standalone
        self._ignorar = True
        self.dd_canal.set_model(Gtk.StringList.new([s[3] for s in canais.saida] if canais else []))
        self.dd_canal.set_sensitive(bool(canais) and sa)
        self.dd_canal.set_tooltip_text(None if sa else "O canal da pré-correção acompanha o canal de saída "
                                                       "(só muda aqui no modo de curvas standalone)")
        self.itens_pot = P.itens_potencia(passos, sa) if passos else []
        self.dd_pot.set_model(Gtk.StringList.new([i[0] for i in self.itens_pot]))
        self._ignorar = False
        self.canal = self.pot = None
        c, p = self._canal_pot_status(m.status)
        self._definir_canal_pot(c, p)

        self.ed_mod.set_curva(self.lin.modulo)
        self.ed_fase.set_curva(self.lin.fase)
        self._sincronizar_modo(self.ed_mod)
        self._sincronizar_modo(self.ed_fase)
        self._mostrar_resposta(d.get("coef"))
        self._rotulos()
        self.banner.set_title("; ".join(avisos).capitalize() if avisos else "")
        self.banner.set_revealed(bool(avisos))
        self.widget.set_visible_child_name("editor")
        return False

    def _rotulos(self):
        nome = self.pre.nome if self.pre is not None and self.pre.nome else "(sem arquivo)"
        self.lbl_arq_pre.set_label("Arquivo: %s%s" % (nome, " • alterações não salvas" if self.sujos else ""))
        nl = self.lin.nome if self.lin is not None and self.lin.nome else "(sem arquivo)"
        self.lbl_arq_lin.set_label("Arquivo: %s%s" % (nl, " • alterações não salvas" if self.lin_sujo else ""))
        self.lbl_sessao.set_label("Porta 5000 em uso por este computador")

    # ================================================================ canal e potência
    def _canal_pot_status(self, st):
        m = self.j.modelo
        modo_b = m.modo_atual(st) == 1
        c = None
        if m.canais is not None:
            c = P.canal_no_status(st, [int(s[0]) for s in m.canais.saida], modo_b)
        passos = (m.passos_dpwr if self.digital else m.passos_apwr) or []
        p = P.potencia_no_status(st, passos, m.defs.standalone, modo_b) if passos else None
        return c, p

    def _idx_arquivo(self, c):
        """Posição do canal -> índice no arquivo (CdefFile.getOutChannelsIndex)."""
        canais = self.j.modelo.canais
        if canais is not None and c is not None and c < len(canais.indices):
            i = canais.indices[c]
            if self.pre is not None and i < self.pre.n_can:
                return i
        return c

    def _plana(self):
        return self.pre is not None and self.pot is not None and self.pot >= self.pre.n_pot - 1 \
            and not self.j.modelo.defs.standalone

    def _definir_canal_pot(self, c, p):
        self.canal, self.pot = c, p
        self._ignorar = True
        if c is not None:
            self.dd_canal.set_selected(c)
        if p is not None and p < len(self.itens_pot):
            self.dd_pot.set_selected(p)
        self._ignorar = False
        self._carregar_ampm()

    def _carregar_ampm(self):
        c, p = self._idx_arquivo(self.canal), self.pot
        ok = self.pre is not None and c is not None and p is not None and c < self.pre.n_can and p < self.pre.n_pot
        plana = self._plana()
        for ed, am in ((self.ed_am, True), (self.ed_pm, False)):
            if not ok:
                ed.set_curva(P.Curva(ed.eixo))
                ed.set_referencia(None)
                ed.set_editavel(False)
                continue
            curva = (self.pre.am if am else self.pre.pm)[c][p]
            ed.set_curva(curva)
            grav = self.pre_gravado.curva_gravada(c, p, am)
            ys = P.equipamento_para_am(grav) if am else P.equipamento_para_pm(grav)
            ed.set_referencia(ys, "gravada no equipamento")
            ed.set_editavel(not plana)
            self._sincronizar_modo(ed)
        if plana:
            self.lbl_arq_pre.set_label("Curva plana selecionada: não há o que editar nesta potência")
        else:
            self._rotulos()
        # o original reenvia a curva do editor ao trocar de canal/potência;
        # aqui só reenviamos as que foram editadas e ainda não salvas.
        if ok and not plana and (c, p) in self.sujos:
            self._enviar_am(True)
            self._enviar_am(False)

    def _sincronizar_modo(self, ed):
        self._ignorar = True
        (ed.btn_lin if ed.curva.modo == P.LINEAR else ed.btn_pol).set_active(True)
        self._ignorar = False

    def _canal_escolhido(self, dd, _p):
        if self._ignorar or not self.ativo or self.trab is None:
            return
        i = dd.get_selected()
        canais = self.j.modelo.canais
        if canais is None or i >= len(canais.saida):
            return
        num = int(canais.saida[i][0])
        self._mudanca_local = time.time()
        self.trab.executar(lambda s: s.canal("%02x" % (num & 0xFF)), None,
                           lambda e: GLib.idle_add(self.j.aviso, "Falha ao trocar o canal: %s" % e, 6))
        self.canal = i
        self._carregar_ampm()

    def _pot_escolhida(self, dd, _p):
        if self._ignorar or not self.ativo or self.trab is None:
            return
        i = dd.get_selected()
        if i >= len(self.itens_pot):
            return
        _rot, cmd, porta = self.itens_pot[i]
        self._mudanca_local = time.time()
        err = lambda e: GLib.idle_add(self.j.aviso, "Falha ao trocar a potência: %s" % e, 6)  # noqa: E731
        if porta == 5000:
            self.trab.executar(lambda s: s.trocar(cmd.encode(), 1), None, err)
        else:
            self.j.cliente.escrever([C.Cmd(cmd, 1)], None, err)
        self.pot = i
        self._carregar_ampm()

    # ================================================================ envio das curvas
    def _curva_alterada(self, ed, final, am):
        if not self.ativo or self.canal is None or self.pot is None:
            return
        c = self._idx_arquivo(self.canal)
        self.sujos.add((c, self.pot))
        if final or self.sw_vivo.get_active():
            self._enviar_am(am)
        if final:
            self._rotulos()

    def _enviar_am(self, am):
        ed = self.ed_am if am else self.ed_pm
        pts = list(ed.pontos())
        c, p = self._idx_arquivo(self.canal), self.pot
        vals = P.am_para_equipamento(pts) if am else P.pm_para_equipamento(pts)
        self.pre.definir_curva(c, p, am, vals)          # WriterPrec.exec(): setCurve
        if self.trab is None:
            return
        fn = (lambda s: s.enviar_am(pts)) if am else (lambda s: s.enviar_pm(pts))
        self.trab.coalescer("am" if am else "pm", fn, None,
                            lambda e: GLib.idle_add(self.j.aviso, "Falha ao enviar a curva: %s" % e, 6))

    def _linear_alterada(self, ed, final):
        if not self.ativo:
            return
        self.lin_sujo = True
        if final or self.sw_vivo_lin.get_active():
            self._enviar_linear(ler=final)
        if final:
            self._rotulos()

    def _enviar_linear(self, ler=True):
        if self.trab is None:
            return
        pm, pf = list(self.ed_mod.pontos()), list(self.ed_fase.pontos())

        def f(s):
            s.enviar_linear(P.coeficientes_lineares(pm, pf))
            return s.ler_coeficientes() if ler else None

        def fim(hx):
            if hx:
                GLib.idle_add(self._mostrar_resposta, hx)
        self.trab.coalescer("lin", f, fim,
                            lambda e: GLib.idle_add(self.j.aviso, "Falha ao enviar a linear: %s" % e, 6))

    def _mostrar_resposta(self, hx):
        if not hx:
            return False
        self._medida_hex = hx
        try:
            m, f = P.resposta_no_editor(hx, self.ed_mod.pontos())
        except Exception:  # noqa: BLE001
            return False
        self.ed_mod.set_medida(m, "no equipamento")
        self.ed_fase.set_medida(f, "no equipamento")
        return False

    def ler_resposta(self):
        if self.trab is None:
            return
        self.trab.executar(lambda s: s.ler_coeficientes(), lambda hx: GLib.idle_add(self._mostrar_resposta, hx),
                           lambda e: GLib.idle_add(self.j.aviso, "Falha ao ler os coeficientes: %s" % e, 6))

    # ================================================================ limpar / restaurar
    def limpar(self, ed):
        if not self.ativo or not ed.editavel:
            return
        rf = self.j.modelo.status[559] & 1
        dlg = Adw.AlertDialog(heading="Voltar a curva para uma reta?",
                              body="A curva %s volta aos dois pontos padrão e é enviada ao equipamento.%s"
                                   % (ed.titulo, "\n\nComo no programa original, o RF é desligado por cerca de "
                                                 "1 segundo durante a troca para evitar transientes." if rf else ""))
        dlg.add_response("cancelar", "Cancelar")
        dlg.add_response("limpar", "Limpar")
        dlg.set_response_appearance("limpar", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.set_close_response("cancelar")

        def resp(d, r):
            if r != "limpar":
                return
            if rf:   # WriterPrec.muteRf(): w22600, 1 s, w22601
                self.j.cliente.escrever([C.Cmd("w22600\r\n", 6)])
                GLib.timeout_add(1000, lambda: self.j.cliente and self.j.cliente.escrever(
                    [C.Cmd("w22601\r\n", 6)]) and False)
            ed.curva.controles = [list(x) for x in ed.eixo.padrao()]
            ed.set_curva(ed.curva)
            ed.emit("alterada", True)
        dlg.connect("response", resp)
        dlg.present(self.j)

    def restaurar_ampm(self):
        """MbPanPrecB.readFile(): pontos do arquivo + o equipamento recarrega
        a curva gravada ('l' + canal + potência)."""
        if not self.ativo or self.pre is None or self.canal is None or self.pot is None or self._plana():
            return
        c, p = self._idx_arquivo(self.canal), self.pot
        for am in (True, False):
            orig = (self.pre_gravado.am if am else self.pre_gravado.pm)[c][p]
            (self.pre.am if am else self.pre.pm)[c][p] = orig.copia()
            self.pre.definir_curva(c, p, am, self.pre_gravado.curva_gravada(c, p, am))
        self.sujos.discard((c, p))
        canais = self.j.modelo.canais
        base = int(canais.saida[0][0]) if canais else 0
        num = self.canal + base
        self.trab.executar(lambda s: s.carregar_curva_gravada(num, p),
                           lambda _: GLib.idle_add(self.j.aviso, "Curvas restauradas do arquivo"),
                           lambda e: GLib.idle_add(self.j.aviso, "Falha ao recarregar: %s" % e, 6))
        self._carregar_ampm()

    def restaurar_linear(self):
        if not self.ativo or self.lin_gravado is None:
            return
        self.lin.modulo = self.lin_gravado.modulo.copia()
        self.lin.fase = self.lin_gravado.fase.copia()
        self.ed_mod.set_curva(self.lin.modulo)
        self.ed_fase.set_curva(self.lin.fase)
        self._sincronizar_modo(self.ed_mod)
        self._sincronizar_modo(self.ed_fase)
        self.lin_sujo = False
        self._rotulos()

        def f(s):
            s.carregar_linear_gravada()
            return s.ler_coeficientes()
        self.trab.executar(f, lambda hx: GLib.idle_add(self._mostrar_resposta, hx),
                           lambda e: GLib.idle_add(self.j.aviso, "Falha ao recarregar: %s" % e, 6))

    # ================================================================ salvar / exportar
    def _bytes(self, linear, nome_base):
        if linear:
            ext_knb = ".ldknb" if self.ext_lin == ".dlin" else ".laknb"
            self.lin.modulo, self.lin.fase = self.ed_mod.curva, self.ed_fase.curva
            return self.lin.bytes_completo(nome_base + ext_knb)
        canais = self.j.modelo.canais
        if canais is not None:
            self.pre.ajustar_canais(len(canais.saida))     # WriterPrec.writeFile()
            self.pre_gravado.ajustar_canais(len(canais.saida))
        return self.pre.bytes_completo(nome_base + self.ext_pre)

    def _nome_atual(self, linear):
        arq = self.lin if linear else self.pre
        ext = self.ext_lin if linear else self.ext_pre
        if arq is not None and arq.nome:
            return arq.nome[:-len(ext)] if arq.nome.endswith(ext) else arq.nome.rsplit(".", 1)[0]
        return None

    def _pedir_nome(self, padrao, ext, continuar):
        dlg = Adw.AlertDialog(heading="Nome do arquivo",
                              body="Até %d caracteres (letras, números, - e _). Extensão %s." % (NOME_MAX, ext))
        ent = Gtk.Entry(text=padrao or "precorrecao", activates_default=True, max_length=NOME_MAX)
        dlg.set_extra_child(ent)
        dlg.add_response("cancelar", "Cancelar")
        dlg.add_response("ok", "Salvar")
        dlg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("ok")
        dlg.set_close_response("cancelar")

        def resp(d, r):
            if r != "ok":
                return
            n = ent.get_text().strip()
            if n.lower().endswith(ext):
                n = n[:-len(ext)]
            if not _nome_valido(n):
                self.j.aviso("Nome inválido: use até %d letras, números, - ou _" % NOME_MAX, 5)
                return
            continuar(n)
        dlg.connect("response", resp)
        dlg.present(self.j)

    def salvar(self, linear, como=False, depois=None):
        if not self.ativo or (not linear and self.pre is None):
            return
        ext = self.ext_lin if linear else self.ext_pre
        atual = self._nome_atual(linear)
        if como or not atual:
            self._pedir_nome(atual, ext, lambda n: self._gravar(linear, n, depois))
        else:
            self._gravar(linear, atual, depois)

    def _gravar(self, linear, nome_base, depois=None):
        ext = self.ext_lin if linear else self.ext_pre
        nome = nome_base + ext
        try:
            dados = self._bytes(linear, nome_base)
        except Exception as e:  # noqa: BLE001
            self.j.aviso("Não foi possível montar o arquivo: %s" % e, 6)
            return
        self.enviar_arquivos([(nome, dados)], "Gravando %s" % nome,
                             lambda: self._gravado(linear, nome, dados, depois))

    def _gravado(self, linear, nome, dados, depois):
        if linear:
            self.lin.nome = nome
            self.lin_gravado = P.ArquivoLinear.ler(dados, nome, self.ext_lin == ".dlin")
            self.lin_sujo = False
        else:
            self.pre.nome = nome
            self.pre_gravado = P.ArquivoPre.ler(dados, nome, self.digital)
            self.sujos.clear()
            self._carregar_ampm()
        self._rotulos()
        self.j.aviso("%s gravado no equipamento" % nome)
        if depois:
            depois()

    def enviar_arquivos(self, arquivos, titulo, ao_fim=None, trab=None, sempre=None):
        """RunLoadFiles para uma lista [(nome, bytes)], com a leitura de
        status da porta 10001 suspensa durante a gravação (como o original)."""
        trab = trab or self.trab
        if trab is None:
            return
        cli = self.j.cliente
        total = sum(len(d) for _, d in arquivos) or 1
        self.lbl_prog.set_label(titulo + "…")
        self.barra_prog.set_fraction(0)
        self.rev_prog.set_reveal_child(True)
        if cli is not None:
            cli.suspender()

        def f(s):
            feito = 0
            for nome, dados in arquivos:
                base = feito
                s.enviar_arquivo(nome, dados,
                                 lambda a, t, b=base: GLib.idle_add(self.barra_prog.set_fraction, (b + a) / total))
                feito += len(dados)
            return True

        def fim(_):
            GLib.idle_add(acabou, None)

        def erro(e):
            GLib.idle_add(acabou, e)

        def acabou(e):
            if cli is not None:
                cli.retomar()
            self.rev_prog.set_reveal_child(False)
            if sempre:
                sempre()
            if e:
                dlg = Adw.AlertDialog(heading="A gravação falhou", body=str(e))
                dlg.add_response("ok", "OK")
                dlg.present(self.j)
            else:
                self.atualizar_lista()
                if ao_fim:
                    ao_fim()
            return False
        trab.executar(f, fim, erro)

    def atualizar_lista(self):
        cli = self.j.cliente
        if cli is None:
            return

        def fim(lista):
            self.lista = lista
            if self.j.modelo is not None:
                self.j.modelo.arquivos = list(lista)
        cli.executar(lambda c: lista_de_arquivos(c.pergunta("yh\n\r")), fim, ler_status=False)

    def exportar(self, linear):
        if not self.ativo:
            return
        ext = self.ext_lin if linear else self.ext_pre
        base = self._nome_atual(linear) or "precorrecao"
        dlg = Gtk.FileDialog(title="Exportar pré-correção", initial_name=base + ext)

        def fim(d, res):
            try:
                arq = d.save_finish(res)
            except GLib.Error:
                return
            try:
                with open(arq.get_path(), "wb") as fh:
                    fh.write(self._bytes(linear, base))
                self.j.aviso("Exportado para %s" % arq.get_basename())
            except Exception as e:  # noqa: BLE001
                self.j.aviso("Falha ao exportar: %s" % e, 6)
        dlg.save(self.j, None, fim)

    # ================================================================ liberar
    def liberar(self):
        if self.trab is None:
            self.widget.set_visible_child_name("entrada")
            return
        pend = []
        if self.sujos:
            pend.append("curvas AM/PM")
        if self.lin_sujo:
            pend.append("pré-correção linear")
        dlg = Adw.AlertDialog(heading="Liberar a porta 5000?")
        if pend:
            dlg.set_body("Há alterações não salvas (%s). Se liberar sem salvar, o equipamento volta às "
                         "curvas gravadas." % " e ".join(pend))
            dlg.add_response("cancelar", "Cancelar")
            dlg.add_response("descartar", "Liberar sem salvar")
            dlg.add_response("salvar", "Salvar e liberar")
            dlg.set_response_appearance("descartar", Adw.ResponseAppearance.DESTRUCTIVE)
            dlg.set_response_appearance("salvar", Adw.ResponseAppearance.SUGGESTED)
        else:
            dlg.set_body("Outro computador poderá entrar na pré-correção.")
            dlg.add_response("cancelar", "Cancelar")
            dlg.add_response("descartar", "Liberar")
            dlg.set_response_appearance("descartar", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_close_response("cancelar")

        def resp(d, r):
            if r == "descartar":
                self._soltar(descartar=True)
            elif r == "salvar":
                def depois_lin():
                    self._soltar(False)

                def depois_pre():
                    if self.lin_sujo:
                        self.salvar(True, depois=depois_lin)
                    else:
                        self._soltar(False)
                if self.sujos:
                    self.salvar(False, depois=depois_pre)
                else:
                    depois_pre()
        dlg.connect("response", resp)
        dlg.present(self.j)

    def _soltar(self, descartar):
        trab = self.trab
        if trab is None:
            return
        if descartar and self.sujos and self.canal is not None and self.pot is not None and not self._plana():
            canais = self.j.modelo.canais
            num = self.canal + (int(canais.saida[0][0]) if canais else 0)
            p = self.pot
            trab.executar(lambda s: s.carregar_curva_gravada(num, p))
        if descartar and self.lin_sujo:
            trab.executar(lambda s: s.carregar_linear_gravada())
        trab.ao_queda = None
        trab.fechar()
        self.trab = None
        self.ativo = False
        self.sujos.clear()
        self.lin_sujo = False
        self.widget.set_visible_child_name("entrada")
        self.j.aviso("Porta 5000 liberada")

    # ================================================================ sessão avulsa
    def com_sessao(self, fn, pedir_login=True):
        """Executa fn(trabalhador, avulso) com uma sessão na porta 5000: a da
        página, se aberta, ou uma temporária (com login, se pedido)."""
        if self.trab is not None:
            fn(self.trab, False)
            return
        if P.porta5000_ocupada(self.j.modelo.status):
            self.j.aviso("A porta 5000 está em uso por outro computador — tente depois", 6)
            return

        def abrir():
            t = self._novo_trabalhador()
            t.ao_queda = lambda msg: GLib.idle_add(self.j.aviso, "A porta 5000 caiu: %s" % msg, 6)
            fn(t, True)
        if pedir_login:
            self.pedir_login(abrir, "Login da pré-correção")
        else:
            abrir()
