"""Tela inicial: escolher ou cadastrar o equipamento."""
from __future__ import annotations

import ipaddress

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import config  # noqa: E402


class TelaConexao:
    def __init__(self, ao_conectar, ao_simulador):
        self.ao_conectar = ao_conectar
        self.ao_simulador = ao_simulador
        self.widget = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=560)
        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24, margin_top=36, margin_bottom=36,
                        margin_start=18, margin_end=18)
        clamp.set_child(caixa)
        self.widget.set_child(clamp)

        st = Adw.StatusPage(icon_name="io.github.aragonxpd154.ArkT", title="Conectar a um ARK-T",
                            description="Excitadores MB International / Screen Service pela porta de serviço "
                                        "(TCP 10001). Sem Java.")
        st.add_css_class("compact")
        caixa.append(st)

        self.grupo_salvos = Adw.PreferencesGroup(title="Equipamentos")
        caixa.append(self.grupo_salvos)
        self._linhas = []

        novo = Adw.PreferencesGroup(title="Novo equipamento")
        self.e_nome = Adw.EntryRow(title="Nome (ex.: Fonte Grande — principal)")
        self.e_ip = Adw.EntryRow(title="Endereço IP")
        self.e_ip.connect("entry-activated", lambda *a: self._conectar_novo())
        self.e_ip.set_input_purpose(Gtk.InputPurpose.FREE_FORM)
        avancado = Adw.ExpanderRow(title="Portas", subtitle="Comandos 10001 • arquivos HTTP 80")
        self.s_porta = Adw.SpinRow.new_with_range(1, 65535, 1)
        self.s_porta.set_title("Porta de comandos (TCP)")
        self.s_porta.set_value(10001)
        self.s_http = Adw.SpinRow.new_with_range(1, 65535, 1)
        self.s_http.set_title("Porta HTTP dos arquivos")
        self.s_http.set_value(80)
        avancado.add_row(self.s_porta)
        avancado.add_row(self.s_http)
        novo.add(self.e_nome)
        novo.add(self.e_ip)
        novo.add(avancado)
        caixa.append(novo)

        botoes = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        b = Gtk.Button(label="Conectar")
        b.add_css_class("suggested-action")
        b.add_css_class("pill")
        b.connect("clicked", lambda *a: self._conectar_novo())
        botoes.append(b)
        sim = Gtk.Button(label="Abrir simulador")
        sim.add_css_class("pill")
        sim.set_tooltip_text("Um ARK-T de mentira, para treinar e conhecer o programa")
        sim.connect("clicked", lambda *a: self.ao_simulador())
        botoes.append(sim)
        caixa.append(botoes)
        self.recarregar()

    def recarregar(self):
        for r in self._linhas:
            self.grupo_salvos.remove(r)
        self._linhas = []
        eqs = config.carregar()["equipamentos"]
        self.grupo_salvos.set_visible(bool(eqs))
        for e in eqs:
            sub = e["ip"] + ("" if e.get("porta", 10001) == 10001 else ":%d" % e["porta"])
            r = Adw.ActionRow(title=e.get("nome") or e["ip"], subtitle=sub, activatable=True)
            r.add_prefix(Gtk.Image(icon_name="network-transmit-receive-symbolic"))
            rm = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Esquecer")
            rm.add_css_class("flat")
            rm.connect("clicked", self._esquecer, e)
            r.add_suffix(rm)
            r.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
            r.connect("activated", lambda _r, e=e: self.ao_conectar(e.get("nome"), e["ip"], e.get("porta", 10001),
                                                                    e.get("porta_http", 80)))
            self.grupo_salvos.add(r)
            self._linhas.append(r)

    def _esquecer(self, b, e):
        config.esquecer(e["ip"], e.get("porta", 10001))
        self.recarregar()

    def _conectar_novo(self):
        ip = self.e_ip.get_text().strip()
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            if not ip or " " in ip:
                self.e_ip.add_css_class("error")
                return
        self.e_ip.remove_css_class("error")
        nome = self.e_nome.get_text().strip()
        self.ao_conectar(nome, ip, int(self.s_porta.get_value()), int(self.s_http.get_value()))
