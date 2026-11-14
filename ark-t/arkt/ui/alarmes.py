"""Tabela de alarmes: estado de cada alarme e onde ele é sinalizado
(programa, LCD, histórico, relés, traps SNMP, desligamento de RF)."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ..modelo import COLUNAS, DESCRICAO_COLUNAS  # noqa: E402

NOMES_PT = {
    "Up Converter Osc. Unlock": "Oscilador do up-converter destravado",
    "PS Voltage out of range": "Tensão da fonte fora da faixa",
    "PS Current out of range": "Corrente da fonte fora da faixa",
    "PS1/PS2 Voltage Alarm": "Tensão PS1/PS2",
    "PS1/PS2 Current Alarm": "Corrente PS1/PS2",
    "Absolute Power Limiter": "Limitador absoluto de potência",
    "Up Converter Communication Error": "Falha de comunicação com o up-converter",
    "Temperature High Alarm": "Temperatura alta (alarme)",
    "Temperature Level -3dB": "Temperatura — redução de 3 dB",
    "Temperature High Warning": "Temperatura alta (aviso)",
    "Forward Power High": "Potência direta alta",
    "Forward Power Low Warning": "Potência direta baixa (aviso)",
    "Forward Power Low Alarm": "Potência direta baixa (alarme)",
    "Reflex Power High": "Potência refletida alta",
    "Fan speed": "Rotação dos ventiladores",
    "Not Used": "Não usado",
    "GPS Lock": "Trava do GPS",
    "GPS Communication Error": "Falha de comunicação com o GPS",
    "Signal 10 MHz Lock": "Trava do sinal de 10 MHz",
    "Signal 120 MHz Lock": "Trava do sinal de 120 MHz",
    "Signal 960 MHz Lock": "Trava do sinal de 960 MHz",
    "File System Error": "Erro no sistema de arquivos",
    "Bad File in File System": "Arquivo inválido no sistema de arquivos",
    "1PPS Lock": "Trava do 1PPS",
    "PPS Phase": "Fase do PPS",
    "System Delay": "Atraso do sistema",
    "IIP Error": "Erro de IIP",
    "Input Error": "Erro de entrada",
    "FPGA Boot Alarm": "Falha na inicialização da FPGA",
    "Warm UP Alarm": "Aquecimento",
    "Down Converter Osc. Unlock": "Oscilador do down-converter destravado",
    "No RF Input": "Sem RF na entrada", "No IF Input": "Sem FI na entrada",
    "RF Input Squelch": "Squelch da entrada de RF", "IF Input Squelch": "Squelch da entrada de FI",
    "Interlock alarm": "Intertravamento",
    "Input Not Present Alarm": "Entrada ausente",
    "Input Not Valid Alarm": "Entrada inválida",
    "Late MIP Alarm": "MIP atrasado",
    "Network Delay Alarm": "Atraso de rede",
    "DVB-T 1PPS Lock": "Trava do 1PPS (DVB-T)",
    "DVB-T PPS Phase": "Fase do PPS (DVB-T)",
    "DVB-T System Delay": "Atraso do sistema (DVB-T)",
    "DVB-T MIP Error": "Erro de MIP (DVB-T)",
    "No Input": "Sem entrada",
}


def nome_alarme(n):
    if n.startswith("Fan speed ("):
        return "Rotação dos ventiladores " + n[len("Fan speed "):]
    return NOMES_PT.get(n, n)


class PaginaAlarmes:
    def __init__(self, modelo, ctx):
        self.m = modelo
        self.ctx = ctx
        self.widget = Gtk.ScrolledWindow()
        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18, margin_bottom=24,
                        margin_start=18, margin_end=18)
        self.widget.set_child(caixa)

        topo = Gtk.Box(spacing=12)
        t = Gtk.Label(label="Alarmes", xalign=0, hexpand=True)
        t.add_css_class("titulo-tela")
        topo.append(t)
        self.btn_todos = Gtk.Button(label="Habilitar todos")
        self.btn_nenhum = Gtk.Button(label="Desabilitar todos")
        for b in (self.btn_todos, self.btn_nenhum):
            b.set_valign(Gtk.Align.CENTER)
            topo.append(b)
        self.btn_todos.connect("clicked", lambda *a: self._total(True))
        self.btn_nenhum.connect("clicked", lambda *a: self._total(False))
        caixa.append(topo)
        dica = Gtk.Label(xalign=0, wrap=True, label=(
            "Cada coluna diz onde o alarme é sinalizado: GUI (programa), LCD, Evento (histórico), "
            "relés R0–R3, traps SNMP para os destinos T0–T7 e RF (desliga a transmissão). "
            "Ative o Modo edição para alterar."))
        dica.add_css_class("dim-label")
        caixa.append(dica)

        cartao = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        cartao.add_css_class("card")
        self.grade = Gtk.Grid(column_spacing=2, row_spacing=2, margin_top=10, margin_bottom=10, margin_start=10,
                              margin_end=10)
        cartao.append(self.grade)
        caixa.append(cartao)

        cab = Gtk.Label(label="Alarme", xalign=0)
        cab.add_css_class("coluna-alarme")
        self.grade.attach(cab, 1, 0, 1, 1)
        for k, nome in enumerate(COLUNAS):
            lb = Gtk.Label(label=nome, width_chars=4, tooltip_text=DESCRICAO_COLUNAS.get(nome, nome))
            lb.add_css_class("coluna-alarme")
            self.grade.attach(lb, k + 2, 0, 1, 1)
        self.linhas = []
        for r, _ in enumerate(self.m.alarmes.linhas):
            ponto = Gtk.Label(label="●", width_chars=2)
            ponto.add_css_class("led")
            nome = Gtk.Label(xalign=0, hexpand=True, margin_start=4, margin_end=12)
            self.grade.attach(ponto, 0, r + 1, 1, 1)
            self.grade.attach(nome, 1, r + 1, 1, 1)
            checks = []
            for k in range(16):
                ch = Gtk.CheckButton(halign=Gtk.Align.CENTER)
                ch.connect("toggled", self._marcou, r, k + 1)
                self.grade.attach(ch, k + 2, r + 1, 1, 1)
                checks.append(ch)
            self.linhas.append((ponto, nome, checks))
        self._bloq = False
        self._cls = {}
        self._editavel = False
        self.set_editavel(False)

    def atualizar(self, st):
        dados = self.m.alarmes.ler(st)
        self._bloq = True
        for (ponto, nome, checks), a in zip(self.linhas, dados):
            nome.set_text(nome_alarme(a["nome"]))
            cls = "led-vermelho" if a["ativo"] else ("led-cinza" if a["nao_usada"] else "led-verde")
            if self._cls.get(id(ponto)) != cls:
                if id(ponto) in self._cls:
                    ponto.remove_css_class(self._cls[id(ponto)])
                ponto.add_css_class(cls)
                self._cls[id(ponto)] = cls
            if a["nao_usada"]:
                nome.add_css_class("alarme-nao-usado")
            else:
                nome.remove_css_class("alarme-nao-usado")
            if a["ativo"]:
                nome.add_css_class("error")
            else:
                nome.remove_css_class("error")
            for k, ch in enumerate(checks):
                ch.set_active(a["colunas"][k])
                ch.set_sensitive(self._editavel and self.m.alarmes.editavel(a["linha"], k + 1))
        self._bloq = False

    def set_editavel(self, ed):
        self._editavel = ed
        self.btn_todos.set_sensitive(ed)
        self.btn_nenhum.set_sensitive(ed)
        for r, (_, _, checks) in enumerate(self.linhas):
            for k, ch in enumerate(checks):
                ch.set_sensitive(ed and self.m.alarmes.editavel(r, k + 1))

    def _marcou(self, ch, linha, coluna):
        if self._bloq:
            return
        valor = ch.get_active()
        try:
            cmd = self.m.alarmes.comando(linha, coluna, valor)
        except Exception as e:  # noqa: BLE001
            self.ctx.aviso(str(e))
            return
        nome = nome_alarme(self.m.alarmes.linhas[linha])

        def desfazer():
            self._bloq = True
            ch.set_active(not valor)
            self._bloq = False
        self.ctx.enviar([cmd], "%s — %s: %s" % (nome, COLUNAS[coluna - 1], "sim" if valor else "não"),
                        confirmar=coluna == 16, ao_cancelar=desfazer)

    def _total(self, ligar):
        cmds = self.m.alarmes.comandos_total(ligar)
        self.ctx.enviar(cmds, "Todos os alarmes: %s" % ("habilitar" if ligar else "desabilitar"), confirmar=True,
                        corpo="Isto grava %d registros de alarme no equipamento." % len(cmds))


_ = Adw
