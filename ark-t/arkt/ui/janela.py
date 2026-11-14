"""Janela principal."""
from __future__ import annotations

import math
import os
import socket
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import NOME, VERSAO, config  # noqa: E402
from .. import backup as B  # noqa: E402
from .. import campos as C  # noqa: E402
from .. import eventos as E  # noqa: E402
from .. import jar as J  # noqa: E402
from ..arquivos import DefinicaoSistema, TabelaCanais, lista_de_arquivos, passos_potencia, procurar, projeto_cfg  # noqa: E402
from ..modelo import Modelo  # noqa: E402
from ..protocolo import Cliente, Conexao, baixar_http, ler_sobre  # noqa: E402
from .alarmes import PaginaAlarmes  # noqa: E402
from .conexao import TelaConexao  # noqa: E402
from .eventos import PaginaEventos  # noqa: E402
from .linhas import rotulo_campo  # noqa: E402
from .paginas import Pagina  # noqa: E402
from .precorrecao import PaginaPrecorrecao  # noqa: E402
from .visao_geral import VisaoGeral  # noqa: E402

# alterações que pedem confirmação antes de ir para o equipamento
NOMES_ARRISCADOS = {"Mode A", "Mode B", "Manual", "Switch Mode", "Frequency Reference", "MFN-SFN",
                    "cho_channel_a_out", "cho_channel_b_out", "channel_a_in", "channel_b_in"}
TITULOS_ARRISCADOS = {"CW", "Use Local Parameters", "Layer A", "Layer B", "Layer C", "CW A/V", "RF",
                      "Gain Fine Tuning", "Equipment ID"}


def _porta_livre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Janela(Adw.ApplicationWindow):
    def __init__(self, app, alvo=None):
        super().__init__(application=app, title=NOME, default_width=1320, default_height=860)
        self.set_size_request(360, 480)
        self.set_icon_name("io.github.aragonxpd154.ArkT")
        self.cliente: Cliente | None = None
        self.modelo: Modelo | None = None
        self.modo_edicao = False
        self.mostrar_ocultos = False
        self.endereco = ""
        self.nome_eq = ""
        self.paginas = {}
        self.pagina_atual = None
        self.n_eventos = None
        self.ultimo_evento = None
        self._ultimo_uso_edicao = 0
        self._ocupado = 0
        self._simulador = None
        self.porta_prec = 5000
        self.pag_prec = None

        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)
        self.raiz = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.toasts.set_child(self.raiz)

        # --- tela de conexão
        tv = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        hb.pack_end(self._menu_app())
        tv.add_top_bar(hb)
        self.tela_conexao = TelaConexao(self.conectar, self.abrir_simulador)
        tv.set_content(self.tela_conexao.widget)
        self.raiz.add_named(tv, "conexao")

        # --- carregando
        tv2 = Adw.ToolbarView()
        tv2.add_top_bar(Adw.HeaderBar())
        self.st_carregando = Adw.StatusPage(title="Conectando…")
        sp = Gtk.Spinner(spinning=True, width_request=32, height_request=32, halign=Gtk.Align.CENTER)
        self.st_carregando.set_child(sp)
        tv2.set_content(self.st_carregando)
        self.raiz.add_named(tv2, "carregando")
        self.raiz.set_visible_child_name("conexao")

        self._acoes()
        GLib.timeout_add_seconds(1, self._relogio)
        self.connect("close-request", self._fechar)
        if alvo:
            nome, ip, porta, http, *resto = alvo
            prec = resto[0] if resto else (5000 if porta == 10001 else porta + 1)
            GLib.idle_add(lambda: self.conectar(nome, ip, porta, http, porta_prec=prec) and False)

    # ================================================================ ações e menu
    def _acoes(self):
        def add(nome, fn, atalho=None, estado=None):
            if estado is None:
                a = Gio.SimpleAction.new(nome, None)
                a.connect("activate", lambda *x: fn())
            else:
                a = Gio.SimpleAction.new_stateful(nome, None, GLib.Variant.new_boolean(estado))
                a.connect("change-state", fn)
            self.add_action(a)
            if atalho:
                self.get_application().set_accels_for_action("win." + nome, [atalho])
            return a
        add("salvar", self.salvar_no_equipamento)
        add("carregar", self.carregar_do_equipamento)
        add("exportar", self.exportar_sav)
        add("reiniciar", self.reiniciar)
        add("sobre-eq", self.sobre_equipamento)
        add("importar", self.importar_config)
        add("backup-prec", self.baixar_backup_prec)
        add("restaurar-prec", self.restaurar_backup_prec)
        add("desconectar", self.desconectar)
        add("atualizar", lambda: self.cliente and self.cliente.executar(None), "<Control>r")
        add("edicao", lambda: hasattr(self, "btn_edicao") and self.btn_edicao.set_active(not self.btn_edicao.get_active()), "<Control>e")
        self.acao_ocultos = add("ocultos", self._alternar_ocultos, estado=False)
        add("sobre", self.sobre_app)
        add("importar-jar", lambda: self.importar_jar())

    def _menu_app(self):
        m = Gio.Menu()
        m.append("Importar telas do programa original (.jar)…", "win.importar-jar")
        m.append("Sobre o Ark-T", "win.sobre")
        return Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=m, tooltip_text="Menu")

    def _menu_equipamento(self):
        m = Gio.Menu()
        s1 = Gio.Menu()
        s1.append("Salvar configuração no equipamento…", "win.salvar")
        s1.append("Recarregar configuração salva…", "win.carregar")
        s1.append("Exportar configuração (.sav)…", "win.exportar")
        s1.append("Importar configuração (.sav)…", "win.importar")
        m.append_section(None, s1)
        s1 = Gio.Menu()
        s1.append("Baixar backup da pré-correção…", "win.backup-prec")
        s1.append("Restaurar backup da pré-correção…", "win.restaurar-prec")
        m.append_section(None, s1)
        s2 = Gio.Menu()
        s2.append("Reiniciar a placa…", "win.reiniciar")
        s2.append("Informações do equipamento", "win.sobre-eq")
        m.append_section(None, s2)
        s3 = Gio.Menu()
        s3.append("Mostrar campos indisponíveis", "win.ocultos")
        s3.append("Trocar de equipamento", "win.desconectar")
        s3.append("Sobre o Ark-T", "win.sobre")
        m.append_section(None, s3)
        return Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=m, tooltip_text="Menu", primary=True)

    # ================================================================ conexão
    def abrir_simulador(self):
        from .. import simulador
        if self._simulador is None:
            p, h = _porta_livre(), _porta_livre()
            self._simulador = (simulador.rodar(p, h, em_thread=True), p, h)
        (eq, _t, _w), p, h = self._simulador
        self.conectar("Simulador ARK-T", "127.0.0.1", p, h, lembrar=False, porta_prec=eq.porta_prec or 5000)

    def conectar(self, nome, ip, porta=10001, porta_http=80, lembrar=True, porta_prec=5000):
        self.nome_eq = nome or ip
        self.porta_prec = porta_prec
        self.endereco = ip if porta == 10001 else "%s:%d" % (ip, porta)
        self.st_carregando.set_title("Conectando a %s…" % self.nome_eq)
        self.st_carregando.set_description(self.endereco)
        self.raiz.set_visible_child_name("carregando")

        def trabalho():
            try:
                with Conexao(ip, porta, timeout=8.0) as c:
                    lista = lista_de_arquivos(c.pergunta("yh\n\r"))
                    st = c.status()
            except Exception as e:  # noqa: BLE001
                GLib.idle_add(self._falhou, str(e))
                return
            avisos = []
            if not J.disponivel():
                # o equipamento publica o próprio programa (.jar): as telas saem dele
                nome_jar = procurar(lista, ".jar")
                if nome_jar:
                    GLib.idle_add(self.st_carregando.set_title, "Lendo as telas do programa do equipamento…")
                    try:
                        J.importar(baixar_http(ip, nome_jar, porta_http), "%s (%s)" % (nome_jar, ip))
                    except Exception as e:  # noqa: BLE001
                        avisos.append("não foi possível ler %s do equipamento: %s" % (nome_jar, e))
                if not J.disponivel():
                    GLib.idle_add(self._pedir_jar, (nome, ip, porta, porta_http, lembrar, porta_prec))
                    return

            def http(ext, binario=False):
                nome_arq = procurar(lista, ext)
                if not nome_arq:
                    return None
                try:
                    d = baixar_http(ip, nome_arq, porta_http)
                    return d if binario else d.decode("latin-1")
                except Exception as e:  # noqa: BLE001
                    avisos.append("%s: %s" % (nome_arq, e))
                    return None
            t_def = http(".def")
            defs = DefinicaoSistema.ler(t_def, procurar(lista, ".def")) if t_def else DefinicaoSistema()
            if not t_def:
                avisos.append("arquivo .def não lido — telas no padrão ISDB-T")
            canais = None
            t = http(".cdef")
            if t:
                try:
                    canais = TabelaCanais.ler(t)
                except Exception as e:  # noqa: BLE001
                    avisos.append(".cdef inválido: %s" % e)
            dp = http(".dpwr", True)
            ap = http(".apwr", True)
            gd = http(".gdly2")
            cfg = http(".cfg")
            try:
                dp = passos_potencia(dp) if dp else None
                ap = passos_potencia(ap) if ap else None
            except Exception:  # noqa: BLE001
                avisos.append("arquivo de potência inválido")
            gdl = None
            if gd:
                try:
                    ls = gd.split("\n")
                    gdl = [x.strip() for x in ls[1:1 + int(ls[0].strip())]]
                except Exception:  # noqa: BLE001
                    pass
            m = Modelo(defs)
            m.aplicar_arquivos(lista, defs, canais, dp, ap, gdl)
            m.projeto = projeto_cfg(cfg) if cfg else ""
            m.atualizar(st)
            GLib.idle_add(self._montar, m, st, ip, porta, porta_http, avisos, lembrar)
        threading.Thread(target=trabalho, daemon=True).start()

    def _pedir_jar(self, alvo=None):
        """Primeira vez sem a descrição das telas: pede o .jar original."""
        if alvo is not None:
            self.raiz.set_visible_child_name("conexao")
        dlg = Adw.AlertDialog(
            heading="Importar as telas do programa original",
            body="O Ark-T monta as telas a partir do programa do fabricante (ARK-T Installer Utility, "
                 "um arquivo .jar como arkT_v5_5s.jar), que não vem junto com ele."
                 + ("\n\nEste equipamento não publicou o .jar na lista de arquivos." if alvo else "")
                 + "\n\nEscolha o .jar: ele só é lido (nada dele é executado) e a descrição das telas fica "
                   "guardada neste computador. Isto é feito uma vez só.")
        dlg.add_response("cancelar", "Cancelar")
        dlg.add_response("escolher", "Escolher o .jar…")
        dlg.set_response_appearance("escolher", Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("escolher")
        dlg.set_close_response("cancelar")

        def resp(_d, r):
            if r == "escolher":
                self.importar_jar(alvo)
        dlg.connect("response", resp)
        dlg.present(self)
        return False

    def importar_jar(self, alvo=None):
        fd = Gtk.FileDialog(title="Programa original do ARK-T (.jar)")
        flt = Gtk.FileFilter(name="Programa Java (*.jar)")
        flt.add_pattern("*.jar")
        filtros = Gio.ListStore.new(Gtk.FileFilter)
        filtros.append(flt)
        fd.set_filters(filtros)

        def fim(d, res):
            try:
                arq = d.open_finish(res)
            except GLib.Error:
                return
            try:
                with open(arq.get_path(), "rb") as fh:
                    J.importar(fh.read(), arq.get_basename())
            except Exception as e:  # noqa: BLE001
                err = Adw.AlertDialog(heading="Não foi possível importar", body=str(e))
                err.add_response("ok", "OK")
                err.present(self)
                return
            self.aviso("Telas importadas de %s" % arq.get_basename(), 5)
            if alvo is not None:
                nome, ip, porta, http, lembrar, prec = alvo
                self.conectar(nome, ip, porta, http, lembrar=lembrar, porta_prec=prec)
            elif self.modelo is not None and self.cliente is not None:
                self.aviso("Reconecte ao equipamento para usar as telas novas", 6)
        fd.open(self, None, fim)

    def _falhou(self, msg):
        self.raiz.set_visible_child_name("conexao")
        self.aviso("Falha ao conectar: %s" % msg, 6)

    def desconectar(self):
        if self.pag_prec is not None:
            self.pag_prec.encerrar()
            self.pag_prec = None
        if self.cliente:
            self.cliente.parar()
            self.cliente = None
        self.modelo = None
        self.btn_edicao_set(False)
        filho = self.raiz.get_child_by_name("painel")
        if filho is not None:
            self.raiz.remove(filho)
        self.tela_conexao.recarregar()
        self.raiz.set_visible_child_name("conexao")
        self.set_title(NOME)

    def _fechar(self, *a):
        if self.pag_prec is not None:
            self.pag_prec.encerrar()
        if self.cliente:
            self.cliente.parar()
        return False

    # ================================================================ painel
    def _montar(self, m: Modelo, st, ip, porta, porta_http, avisos, lembrar):
        self.modelo = m
        if lembrar:
            config.lembrar(self.nome_eq if self.nome_eq != ip else (m.defs.sys_name or ip), ip, porta, porta_http)
        self.set_title("%s — %s" % (self.nome_eq, NOME))

        split = Adw.NavigationSplitView(min_sidebar_width=230, max_sidebar_width=280)
        # barra lateral
        lado = Adw.ToolbarView()
        hb = Adw.HeaderBar()
        tit = Adw.WindowTitle(title=self.nome_eq, subtitle=self.endereco)
        hb.set_title_widget(tit)
        lado.add_top_bar(hb)
        self.lista_nav = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.lista_nav.add_css_class("navigation-sidebar")
        sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        sc.set_child(self.lista_nav)
        lado.set_content(sc)
        pag_lado = Adw.NavigationPage(title=self.nome_eq, child=lado)
        split.set_sidebar(pag_lado)

        # conteúdo
        cont = Adw.ToolbarView()
        self.hb = Adw.HeaderBar()
        self.titulo = Adw.WindowTitle(title="Visão geral")
        self.hb.set_title_widget(self.titulo)
        self.btn_edicao = Gtk.ToggleButton(icon_name="changes-prevent-symbolic",
                                           tooltip_text="Modo edição (Ctrl+E): libera alterações no equipamento")
        self.btn_edicao.connect("toggled", self._alternar_edicao)
        self.hb.pack_end(self._menu_equipamento())
        self.hb.pack_end(self.btn_edicao)
        self.spinner = Gtk.Spinner()
        self.hb.pack_start(self.spinner)
        cont.add_top_bar(self.hb)
        self.banner = Adw.Banner(title="Modo edição ligado — cada alteração é enviada na hora ao equipamento",
                                 button_label="Desligar")
        self.banner.connect("button-clicked", lambda *a: self.btn_edicao.set_active(False))
        cont.add_top_bar(self.banner)
        self.banner_falha = Adw.Banner(title="")
        cont.add_top_bar(self.banner_falha)
        self.pilha = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        cont.set_content(self.pilha)
        self.pag_cont = Adw.NavigationPage(title="Visão geral", child=cont)
        split.set_content(self.pag_cont)

        # páginas
        self.paginas = {}
        self._linhas_nav = {}
        self.visao = VisaoGeral(m, self)
        self._add_pagina("visao", "Visão geral", "arkt-visao-symbolic", self.visao)
        for t in m.telas:
            self._add_pagina(t.id, t.titulo, t.icone, Pagina(t, self))
        if self.pag_prec is not None:
            self.pag_prec.encerrar()
        self.pag_prec = PaginaPrecorrecao(self)
        self._add_pagina("precorrecao", "Pré-correção", "arkt-curva-symbolic", self.pag_prec)
        self.pag_alarmes = PaginaAlarmes(m, self)
        self._add_pagina("alarmes", "Alarmes", "dialog-warning-symbolic", self.pag_alarmes)
        self.pag_eventos = PaginaEventos(self)
        self._add_pagina("eventos", "Eventos", "document-open-recent-symbolic", self.pag_eventos)
        self.lista_nav.connect("row-selected", self._navegar)
        self.lista_nav.select_row(self.lista_nav.get_row_at_index(0))

        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 760sp"))
        bp.add_setter(split, "collapsed", True)
        self.add_breakpoint(bp)

        antigo = self.raiz.get_child_by_name("painel")
        if antigo is not None:
            self.raiz.remove(antigo)
        self.raiz.add_named(split, "painel")
        self.raiz.set_visible_child_name("painel")
        self.split = split

        self.n_eventos = None
        self._aplicar_status(st)
        for p in self.paginas.values():
            p.set_editavel(False)

        self.cliente = Cliente(ip, porta, porta_http, config.carregar().get("intervalo", 2.0))
        self.cliente.ao_status = lambda s: GLib.idle_add(self._aplicar_status, s)
        self.cliente.ao_erro = lambda e: GLib.idle_add(self._erro_leitura, e)
        self.cliente.ao_ocupado = lambda b: GLib.idle_add(self._set_ocupado, b)
        self.cliente.ultimo_ok = time.time()
        self.cliente.iniciar()
        for a in avisos:
            self.aviso(a, 5)

    def _add_pagina(self, id_, titulo, icone, pagina):
        self.paginas[id_] = pagina
        self.pilha.add_named(pagina.widget, id_)
        row = Gtk.ListBoxRow()
        box = Gtk.Box(spacing=12, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        box.append(Gtk.Image(icon_name=icone))
        lbl = Gtk.Label(label=titulo, xalign=0, hexpand=True)
        box.append(lbl)
        selo = Gtk.Label()
        selo.add_css_class("error")
        selo.set_visible(False)
        box.append(selo)
        row.set_child(box)
        row.id_pagina = id_
        row.titulo = titulo
        self._linhas_nav[id_] = selo
        self.lista_nav.append(row)

    def _navegar(self, lb, row):
        if row is None:
            return
        self.pagina_atual = row.id_pagina
        self.pilha.set_visible_child_name(row.id_pagina)
        self.titulo.set_title(row.titulo)
        self.pag_cont.set_title(row.titulo)
        if self.modelo is not None:
            self._atualizar_pagina(self.pagina_atual, self.modelo.status)
        if getattr(self, "split", None) is not None:
            self.split.set_show_content(True)

    # ================================================================ leituras
    def _atualizar_pagina(self, id_, st):
        p = self.paginas.get(id_)
        if p is None:
            return
        if id_ == "visao":
            return
        if id_ == "eventos":
            return
        p.atualizar(st)

    def _aplicar_status(self, st):
        if self.modelo is None:
            return False
        self.modelo.atualizar(st)
        self.visao.atualizar(st, self.ultimo_evento)
        if self.pagina_atual and self.pagina_atual != "visao":
            self._atualizar_pagina(self.pagina_atual, st)
        ativos = sum(1 for a in self.modelo.alarmes.ler(st) if a["ativo"])
        selo = self._linhas_nav.get("alarmes")
        if selo is not None:
            selo.set_text(str(ativos))
            selo.set_visible(ativos > 0)
        self.banner_falha.set_revealed(False)
        n, cheia, maximo = E.contagem(st)
        chave = (n, cheia)
        if chave != self.n_eventos:
            self.n_eventos = chave
            self._baixar_eventos(n, cheia, maximo)
        return False

    def _erro_leitura(self, msg):
        if self.modelo is None:
            return False
        self.banner_falha.set_title("Sem comunicação com o equipamento: %s" % msg)
        self.banner_falha.set_revealed(True)
        return False

    def _set_ocupado(self, b):
        self._ocupado += 1 if b else -1
        if hasattr(self, "spinner"):
            self.spinner.set_spinning(self._ocupado > 0)
        return False

    def _relogio(self):
        if self.cliente and self.modelo is not None and hasattr(self, "titulo"):
            dt = time.time() - self.cliente.ultimo_ok
            if dt < 4:
                sub = "%s • ao vivo" % self.nome_eq
            else:
                sub = "%s • última leitura há %d s" % (self.nome_eq, dt)
            self.titulo.set_subtitle(sub)
        if self.modo_edicao and time.time() - self._ultimo_uso_edicao > 15 * 60:
            self.btn_edicao.set_active(False)
            self.aviso("Modo edição desligado por inatividade")
        return True

    def recarregar_eventos(self):
        self.n_eventos = None
        if self.modelo is not None:
            n, cheia, maximo = E.contagem(self.modelo.status)
            self.n_eventos = (n, cheia)
            self._baixar_eventos(n, cheia, maximo)

    def _baixar_eventos(self, n, cheia, maximo):
        if not self.cliente and self.modelo is None:
            return
        self.pag_eventos.carregando()
        paginas = (maximo // 8) if cheia else math.ceil(n / 8)

        def f(c):
            buf = []
            for p in range(paginas):
                c.enviar(("g4%02x\n\r" % p).encode())
                d = c.ler_exato(516)
                buf.append(d[4:516].decode("latin-1"))
            texto = "".join(buf)
            if not cheia:
                texto = texto[:n * 64]
            return E.montar_historico(texto, n, cheia, maximo)

        def fim(lista):
            GLib.idle_add(self._eventos_prontos, lista)

        if self.cliente is None:
            GLib.timeout_add(500, lambda: self._baixar_eventos(n, cheia, maximo) and False)
            return
        self.cliente.executar(f, fim, lambda e: GLib.idle_add(self.aviso, "Histórico: %s" % e), ler_status=False)

    def _eventos_prontos(self, lista):
        self.ultimo_evento = lista[0] if lista else None
        self.pag_eventos.definir(lista)
        if self.modelo is not None:
            self.visao.atualizar(self.modelo.status, self.ultimo_evento)
        return False

    # ================================================================ edição
    def btn_edicao_set(self, v):
        if hasattr(self, "btn_edicao"):
            self.btn_edicao.set_active(v)

    def _alternar_edicao(self, b):
        self.modo_edicao = b.get_active()
        self._ultimo_uso_edicao = time.time()
        b.set_icon_name("changes-allow-symbolic" if self.modo_edicao else "changes-prevent-symbolic")
        if self.modo_edicao:
            b.add_css_class("warning")
        else:
            b.remove_css_class("warning")
        self.banner.set_revealed(self.modo_edicao)
        for p in self.paginas.values():
            p.set_editavel(self.modo_edicao)
        if self.modelo is not None and self.pagina_atual:
            self._atualizar_pagina(self.pagina_atual, self.modelo.status)

    def _alternar_ocultos(self, acao, valor):
        acao.set_state(valor)
        self.mostrar_ocultos = valor.get_boolean()
        if self.modelo is not None and self.pagina_atual:
            self._atualizar_pagina(self.pagina_atual, self.modelo.status)

    def aviso(self, texto, segundos=3):
        t = Adw.Toast(title=GLib.markup_escape_text(texto), timeout=segundos)
        self.toasts.add_toast(t)
        return False

    def _arriscado(self, campo):
        return (campo.name in NOMES_ARRISCADOS or campo.title in TITULOS_ARRISCADOS
                or isinstance(campo, C.Botao) or (isinstance(campo, C.Decimal) and campo.tipo == "MbNumericPower"))

    def escrever(self, campo, valor, descricao="", ao_cancelar=None):
        if not self.modo_edicao:
            self.aviso("Ligue o Modo edição (cadeado no alto) para alterar")
            if ao_cancelar:
                ao_cancelar()
            return
        self._ultimo_uso_edicao = time.time()
        try:
            cmds = self._comandos_especiais(campo, valor)
            if cmds is None:
                cmds = campo.comandos(valor)
        except C.Recusado as e:
            self.aviso(str(e), 4)
            if ao_cancelar:
                ao_cancelar()
            return
        if not cmds:
            return
        self.enviar(cmds, descricao or rotulo_campo(campo), confirmar=self._arriscado(campo), ao_cancelar=ao_cancelar)

    def _comandos_especiais(self, campo, valor):
        """Regras extras que no Java ficavam em addExecutableBefore()."""
        m = self.modelo
        if campo.name == "Frequency Reference" and m.familia != "isdbt":
            # MbPanOutputDvbt: só o comando prévio do registro 3
            pre = C.Cmd("w000300000\n\r" if int(valor) == 1 else "w000300001\n\r", 8)
            return [pre] + campo.comandos(valor)
        if campo.name == "Frequency Reference" and m.familia == "isdbt":
            mfn = m.nome("MFN-SFN")
            if int(valor) == 1 and mfn is not None and mfn.sel == 1:
                raise C.Recusado("Em SFN não é possível usar a referência interna")
            pre = C.Cmd("w000300000\n\r" if int(valor) == 1 else "w000300001\n\r", 8)
            return [pre] + campo.comandos(valor)
        if campo.tipo == "MbChoiceMfnSfnIsdbt":
            ref = m.nome("Frequency Reference")
            if m.config_em_uso() == 4 and ref is not None and ref.sel == 1 and int(valor) == 1:
                self.aviso("Em SFN a referência de frequência será forçada para externa", 5)
                return [C.Cmd(ref.command + "0000\n\r", "linha"), C.Cmd("w000300001\n\r", "linha")] + campo.comandos(valor)
        return None

    def enviar(self, cmds, descricao, confirmar=False, corpo=None, ao_cancelar=None, destrutivo=False, ao_fim=None):
        def vai():
            self._ultimo_uso_edicao = time.time()

            def ok(_):
                GLib.idle_add(self.aviso, "Enviado: %s" % descricao)
                if ao_fim:
                    GLib.idle_add(ao_fim)

            def erro(e):
                GLib.idle_add(self.aviso, "Falhou (%s): %s" % (descricao, e), 6)
                if ao_cancelar:
                    GLib.idle_add(ao_cancelar)
            self.cliente.escrever(cmds, ok, erro)

        if self.cliente is None:
            return
        if not confirmar:
            vai()
            return
        detalhe = corpo or "Comando%s: %s" % ("s" if len(cmds) > 1 else "",
                                                ", ".join(c.texto.strip() for c in cmds[:6]) + ("…" if len(cmds) > 6 else ""))
        dlg = Adw.AlertDialog(heading="Confirmar alteração no equipamento?", body="%s\n\n%s" % (descricao, detalhe))
        dlg.add_response("cancelar", "Cancelar")
        dlg.add_response("enviar", "Enviar")
        dlg.set_response_appearance("enviar", Adw.ResponseAppearance.DESTRUCTIVE if destrutivo
                                    else Adw.ResponseAppearance.SUGGESTED)
        dlg.set_default_response("cancelar")
        dlg.set_close_response("cancelar")

        def resp(d, r):
            if r == "enviar":
                vai()
            elif ao_cancelar:
                ao_cancelar()
        dlg.connect("response", resp)
        dlg.present(self)

    def enviar_bruto(self, texto, esperado, descricao, confirmar=True, corpo=None, destrutivo=False, ao_fim=None):
        self.enviar([C.Cmd(texto, esperado)], descricao, confirmar=confirmar, corpo=corpo, destrutivo=destrutivo,
                    ao_fim=ao_fim)

    # ================================================================ menu do equipamento
    def _precisa_edicao(self):
        if not self.modo_edicao:
            self.aviso("Ligue o Modo edição para esta ação")
            return False
        return True

    def salvar_no_equipamento(self):
        if self.cliente and self._precisa_edicao():
            self.enviar_bruto("s\r\n", 3, "Salvar a configuração atual na memória do equipamento",
                              corpo="A configuração em uso passa a ser a carregada quando o ARK-T reiniciar.")

    def carregar_do_equipamento(self):
        if self.cliente and self._precisa_edicao():
            self.enviar_bruto("l\r\n", 3, "Recarregar a configuração salva no equipamento",
                              corpo="As alterações não salvas serão descartadas.", destrutivo=True)

    def reiniciar(self):
        if not (self.cliente and self._precisa_edicao()):
            return

        def depois():
            self.cliente.pausar(14)
            self.aviso("Reiniciando… a leitura volta em cerca de 15 s", 6)
        self.enviar_bruto("$\n\r", 2, "Reiniciar a placa do ARK-T", destrutivo=True,
                          corpo="O excitador reinicia e a transmissão é interrompida por alguns segundos.", ao_fim=depois)

    def exportar_sav(self):
        if not self.modelo:
            return
        savs = [a for a in self.modelo.arquivos if a.endswith(".sav")]
        if not savs:
            self.aviso("O equipamento não publicou arquivo .sav")
            return
        dlg = Gtk.FileDialog(title="Pasta para salvar a configuração")

        def fim(d, res):
            try:
                pasta = d.select_folder_finish(res).get_path()
            except GLib.Error:
                return

            def trabalho():
                ok = []
                for nome in savs:
                    try:
                        dados = baixar_http(self.cliente.host, nome, self.cliente.porta_http)
                        with open(os.path.join(pasta, nome), "wb") as fh:
                            fh.write(dados)
                        ok.append(nome)
                    except Exception as e:  # noqa: BLE001
                        GLib.idle_add(self.aviso, "%s: %s" % (nome, e), 5)
                if ok:
                    GLib.idle_add(self.aviso, "Salvo em %s: %s" % (pasta, ", ".join(ok)), 6)
            threading.Thread(target=trabalho, daemon=True).start()
        dlg.select_folder(self, None, fim)

    # ================================================================ importar / backup
    def importar_config(self):
        """ImportSavFile: envia um .sav pela porta 5000 (sem login)."""
        if not self.cliente or self.pag_prec is None or not self._precisa_edicao():
            return
        dlg = Gtk.FileDialog(title="Importar configuração")
        flt = Gtk.FileFilter(name="Configuração do ARK-T (*.sav)")
        flt.add_pattern("*.sav")
        filtros = Gio.ListStore.new(Gtk.FileFilter)
        filtros.append(flt)
        dlg.set_filters(filtros)

        def fim(d, res):
            try:
                arq = d.open_finish(res)
            except GLib.Error:
                return
            nome = arq.get_basename()
            try:
                with open(arq.get_path(), "rb") as fh:
                    dados = fh.read()
                nome.encode("latin-1")
            except (OSError, UnicodeEncodeError) as e:
                self.aviso("Não foi possível ler o arquivo: %s" % e, 6)
                return
            if not nome.endswith(".sav") or len(nome) > 255:
                self.aviso("Escolha um arquivo .sav", 5)
                return
            atual = [a for a in self.modelo.arquivos if a.endswith(".sav")]
            corpo = ("O arquivo %s (%d bytes) será gravado no equipamento%s.\n\nDepois use "
                     "\u201cRecarregar configuração salva\u201d para aplicá-lo."
                     % (nome, len(dados), (" no lugar de %s" % ", ".join(atual)) if atual and nome not in atual else ""))
            conf = Adw.AlertDialog(heading="Importar configuração?", body=corpo)
            conf.add_response("cancelar", "Cancelar")
            conf.add_response("enviar", "Importar")
            conf.set_response_appearance("enviar", Adw.ResponseAppearance.SUGGESTED)
            conf.set_close_response("cancelar")

            def resp(_d, r):
                if r == "enviar":
                    self.pag_prec.com_sessao(lambda t, avulso: self._enviar_sav(t, avulso, nome, dados),
                                             pedir_login=False)
            conf.connect("response", resp)
            conf.present(self)
        dlg.open(self, None, fim)

    def _enviar_sav(self, trab, avulso, nome, dados):
        def ok():
            t = Adw.Toast(title=GLib.markup_escape_text("Arquivo \u201c%s\u201d carregado no equipamento" % nome),
                          timeout=10, button_label="Aplicar agora")
            t.connect("button-clicked", lambda *a: self.carregar_do_equipamento())
            self.toasts.add_toast(t)
        self.pag_prec.enviar_arquivos([(nome, dados)], "Importando %s" % nome, ok, trab=trab,
                                      sempre=(lambda: trab.fechar()) if avulso else None)

    def baixar_backup_prec(self):
        if not self.cliente or self.modelo is None:
            return
        base = (self.modelo.defs.sys_name or self.nome_eq or "arkt").strip().replace(" ", "_")
        base = "".join(c for c in base if c.isalnum() or c in "_-") or "arkt"
        dlg = Gtk.FileDialog(title="Salvar backup da pré-correção",
                             initial_name="precorrecao-%s-%s.zip" % (base, time.strftime("%Y%m%d-%H%M")))

        def fim(d, res):
            try:
                destino = d.save_finish(res).get_path()
            except GLib.Error:
                return
            host, porta_http = self.cliente.host, self.cliente.porta_http
            info = {"equipamento": self.modelo.defs.sys_name or self.nome_eq, "endereco": self.endereco,
                    "cliente": self.modelo.defs.sys_cust}

            def com_lista(lista):
                prec, ref = B.escolher(lista)
                if not prec:
                    GLib.idle_add(self.aviso, "O equipamento não tem arquivos de pré-correção", 6)
                    return
                try:
                    a = {n: baixar_http(host, n, porta_http) for n in prec}
                    r = {}
                    for n in ref:
                        try:
                            r[n] = baixar_http(host, n, porta_http)
                        except Exception:  # noqa: BLE001 - referência é opcional
                            pass
                    with open(destino, "wb") as fh:
                        fh.write(B.montar(a, r, info))
                except Exception as e:  # noqa: BLE001
                    GLib.idle_add(self.aviso, "Falha no backup: %s" % e, 8)
                    return
                GLib.idle_add(self.aviso, "Backup salvo: %s (%s)" % (os.path.basename(destino), ", ".join(prec)), 8)

            def ok(lista):
                threading.Thread(target=com_lista, args=(lista,), daemon=True).start()
            self.cliente.executar(lambda c: lista_de_arquivos(c.pergunta("yh\n\r")), ok,
                                  lambda e: GLib.idle_add(self.aviso, "Falha ao listar arquivos: %s" % e, 6),
                                  ler_status=False)
        dlg.save(self, None, fim)

    def restaurar_backup_prec(self):
        if not self.cliente or self.pag_prec is None:
            return
        dlg = Gtk.FileDialog(title="Restaurar backup da pré-correção")
        flt = Gtk.FileFilter(name="Backup da pré-correção (*.zip)")
        flt.add_pattern("*.zip")
        filtros = Gio.ListStore.new(Gtk.FileFilter)
        filtros.append(flt)
        dlg.set_filters(filtros)

        def fim(d, res):
            try:
                arq = d.open_finish(res)
                with open(arq.get_path(), "rb") as fh:
                    man, arquivos = B.ler(fh.read())
            except GLib.Error:
                return
            except (OSError, B.ErroBackup) as e:
                self.aviso("Backup inválido: %s" % e, 8)
                return
            origem = man.get("equipamento") or "?"
            quando = man.get("criado", "")[:16].replace("T", " ")
            itens = "\n".join("• %s (%d bytes)" % (n, len(b)) for n, b in arquivos)
            conf = Adw.AlertDialog(
                heading="Restaurar a pré-correção?",
                body="Backup de %s%s.\n\n%s\n\nOs arquivos atuais com a mesma extensão serão substituídos. "
                     "É preciso o login da pré-correção." % (origem, (", " + quando) if quando else "", itens))
            conf.add_response("cancelar", "Cancelar")
            conf.add_response("restaurar", "Restaurar")
            conf.set_response_appearance("restaurar", Adw.ResponseAppearance.DESTRUCTIVE)
            conf.set_close_response("cancelar")

            def resp(_d, r):
                if r == "restaurar":
                    self.pag_prec.com_sessao(lambda t, avulso: self._restaurar(t, avulso, arquivos))
            conf.connect("response", resp)
            conf.present(self)
        dlg.open(self, None, fim)

    def _restaurar(self, trab, avulso, arquivos):
        def ok():
            self.aviso("Pré-correção restaurada: %s" % ", ".join(n for n, _ in arquivos), 8)
            if not avulso:
                self.pag_prec.recarregar()
        self.pag_prec.enviar_arquivos(arquivos, "Restaurando a pré-correção", ok, trab=trab,
                                      sempre=(lambda: trab.fechar()) if avulso else None)

    def sobre_equipamento(self):
        if not self.cliente:
            return

        def f(c):
            return ler_sobre(c.pergunta("\xa7\r\n"))

        def fim(info):
            GLib.idle_add(self._mostrar_info, info)
        self.cliente.executar(f, fim, lambda e: GLib.idle_add(self.aviso, "Informações: %s" % e))

    def _mostrar_info(self, info):
        m = self.modelo
        d = Adw.Dialog(title="Informações do equipamento", content_width=560, content_height=640)
        tv = Adw.ToolbarView()
        tv.add_top_bar(Adw.HeaderBar())
        pg = Adw.PreferencesPage()
        tv.set_content(pg)
        d.set_child(tv)

        def grupo(titulo, itens):
            g = Adw.PreferencesGroup(title=titulo)
            for k, v in itens:
                r = Adw.ActionRow(title=k, subtitle=v or "—", subtitle_selectable=True)
                r.add_css_class("property")
                g.add(r)
            pg.add(g)
        grupo("Versões", [("FPGA", info.get("fpga", "")), ("Microcontrolador", info.get("micro", "")),
                          ("GPS", info.get("gps", "")), ("Up-converter", m.versao_upconverter()),
                          ("Ark-T", VERSAO)])
        grupo("Sistema", [("Nome", m.defs.sys_name), ("Cliente", m.defs.sys_cust), ("Instalador / projeto", getattr(m, "projeto", "")),
                          ("Modo de curva", "Standalone" if m.defs.standalone else "Driver"),
                          ("Endereço", self.endereco)])
        grupo("Números de série", m.numeros_de_serie())
        grupo("Arquivos no equipamento", [(a, "") for a in m.arquivos] or [("nenhum", "")])
        d.present(self)
        return False

    def sobre_app(self):
        a = Adw.AboutDialog(application_name="Ark-T", application_icon="io.github.aragonxpd154.ArkT",
                            version=VERSAO, developer_name="Marcos Santos",
                            comments="Gerência dos excitadores ARK-T (MB International / Screen Service) "
                                     "sem Java — substitui o ARK-T Installer Utility 5.5.\n"
                                     "Parte do Sintonia: programas nativos para equipamentos de transmissão.",
                            website="https://github.com/aragonxpd154/sintonia/tree/main/ark-t",
                            issue_url="https://github.com/aragonxpd154/sintonia/issues",
                            license_type=Gtk.License.MIT_X11)
        a.present(self)
