"""Modelo do equipamento: monta as telas a partir da descrição importada do
programa original (veja jar.py), aplica os arquivos de definição do excitador e reproduz
as regras dinâmicas de cada painel (setState/setBolMode do Java)."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import campos as C
from .arquivos import DefinicaoSistema, TabelaCanais
from .jar import carregar as carregar_telas


@dataclass
class No:
    tipo: str                 # grupo | abas | aba | campo
    titulo: str = ""
    filhos: list = field(default_factory=list)
    campo: C.Campo | None = None
    var: str = ""
    visivel: bool = True


@dataclass
class Tela:
    id: str
    titulo: str
    icone: str
    painel: str | None        # classe Java de origem
    raiz: list = field(default_factory=list)
    campos: dict = field(default_factory=dict)   # var -> Campo


TELAS_ISDBT = [
    ("geral", "Geral", "arkt-geral-symbolic", "MbPanGeneral2"),
    ("entrada", "Entrada", "arkt-entrada-symbolic", "MbPanInputIsdbt"),
    ("modos", "Modos e comutação", "arkt-modos-symbolic", "MbPanSwitchIsdbtItu"),
    ("modulacao", "Modulação", "arkt-modulacao-symbolic", "MbPanModIsdbtItu"),
    ("saida", "Saída / RF", "arkt-saida-symbolic", "MbPanOutputIsdbt"),
    ("rede", "Rede", "network-workgroup-symbolic", "MbPanNetworkIsdbt"),
    ("gps", "GPS", "find-location-symbolic", "MbPanGps2"),
]
TELAS_DVBT = [
    ("geral", "Geral", "arkt-geral-symbolic", "MbPanGeneral2"),
    ("entrada", "Entrada", "arkt-entrada-symbolic", "MbPanInputDvbt"),
    ("modos", "Modos e comutação", "arkt-modos-symbolic", "MbPanSwitchDvbtItu"),
    ("modulacao", "Modulação", "arkt-modulacao-symbolic", "MbPanModDvbtItu"),
    ("saida", "Saída / RF", "arkt-saida-symbolic", "MbPanOutputDvbt"),
    ("rede", "Rede", "network-workgroup-symbolic", "MbPanNetworkDvbt"),
    ("gps", "GPS", "find-location-symbolic", "MbPanGps2"),
]

SUBPAINEIS = {"PanLocalIP": "Endereço da placa", "PanTrap": "Destinos de trap SNMP",
             "PanComunity": "Communities SNMP", "panLedInput": "Estado das entradas"}

MODOS_NOMES = ["Rep. analógico", "inválido", "Tx DVB-T", "Tx analógico", "ISDB-T"]
STD_ANA = ["B,G / PAL", "D,K / PAL", "M / PAL", "NTSC", "N / PAL"]


class Modelo:
    def __init__(self, definicao: DefinicaoSistema | None = None):
        dados = carregar_telas() or {"panels": {}, "bundle": {}}
        self.paineis = dados["panels"]
        self.bundle = dados["bundle"]
        self.defs = definicao or DefinicaoSistema()
        self.canais: TabelaCanais | None = None
        self.passos_dpwr = None
        self.passos_apwr = None
        self.curvas_gdly = None
        self.arquivos: list[str] = []
        self.status = bytes(1405)
        self.telas: list[Tela] = []
        self.por_nome: dict[str, C.Campo] = {}
        self.todos: list[C.Campo] = []
        self.familia = self.defs.familia
        lista = TELAS_ISDBT if self.familia == "isdbt" else TELAS_DVBT
        for id_, tit, ico, painel in lista:
            if id_ == "modos" and self.familia == "isdbt" and self.defs.mode_dis[0]:
                painel = "MbPanSwitchRepAna"
            self.telas.append(self._montar_tela(id_, tit, ico, painel))
        self.alarmes = Alarmes(self)

    # ------------------------------------------------------------ montagem
    def _montar_tela(self, id_, titulo, icone, painel):
        tela = Tela(id_, titulo, icone, painel)
        tela.raiz = self._nos(self.paineis.get(painel, {"tree": []})["tree"], tela, painel)
        return tela

    def _nos(self, lista, tela, painel):
        out = []
        for x in lista:
            k = x["kind"]
            if k == "group":
                n = No("grupo", x.get("title", ""), self._nos(x["children"], tela, painel), var=x["var"],
                       visivel=x.get("visible", True))
                out.append(n)
            elif k == "tabs":
                out.append(No("abas", filhos=self._nos(x["tabs"], tela, painel), var=x["var"]))
            elif k == "tab":
                out.append(No("aba", x["title"], self._nos(x["children"], tela, painel)))
            elif k == "widget":
                t = x["type"]
                if t in self.paineis:          # sub-painel (ex.: MbPanModIsdbt, PanTrap)
                    sub = self._nos(self.paineis[t]["tree"], tela, t)
                    titulo = dict(x["calls"]).get("groupTitle", "") or SUBPAINEIS.get(t, "")
                    out.append(No("grupo", titulo, sub, var=x["var"]))
                    continue
                campo = C.criar(t, x["var"], x["calls"])
                if campo is None:
                    continue
                campo.painel = painel
                campo.dispositivo = self
                chave = painel + "." + x["var"]
                tela.campos[chave] = campo
                tela.campos.setdefault(x["var"], campo)
                if campo.name and campo.name not in self.por_nome:
                    self.por_nome[campo.name] = campo
                self.todos.append(campo)
                out.append(No("campo", campo.title, campo=campo, var=x["var"]))
        return out

    def campo(self, painel, var):
        for t in self.telas:
            c = t.campos.get(painel + "." + var)
            if c is not None:
                return c
        return None

    def nome(self, nome):
        return self.por_nome.get(nome)

    # ------------------------------------------------------------ estado
    def modo_atual(self, st=None):
        """0 = Modo A, 1 = Modo B (StateHolder.getModeNumber)."""
        st = st or self.status
        c = self.nome("Actual Mode")
        idx = c.index if c else 744
        return st[idx] & 1

    def config_modo(self, n, st=None):
        st = st or self.status
        c = self.nome("Mode A" if n == 0 else "Mode B")
        idx = c.index if c else (521 if n == 0 else 537)
        return st[idx] & 7

    def config_em_uso(self, st=None):
        return self.config_modo(self.modo_atual(st), st)

    def nome_config(self, cfg):
        if cfg == 0 and self.defs.is_if:
            return "Up Conv."
        if 0 <= cfg < len(MODOS_NOMES):
            return MODOS_NOMES[cfg]
        return "Rep. digital" if cfg == 255 else str(cfg)

    # ------------------------------------------------------------ inicialização
    def aplicar_arquivos(self, arquivos, defs=None, canais=None, dpwr=None, apwr=None, gdly=None):
        """Initializer.initModes() + initialize()."""
        self.arquivos = list(arquivos or [])
        if defs is not None:
            self.defs = defs
        self.canais = canais
        self.passos_dpwr = dpwr
        self.passos_apwr = apwr
        self.curvas_gdly = gdly
        d = self.defs
        tem = lambda ext: any(ext in a for a in self.arquivos)  # noqa: E731

        if gdly:
            c = self.nome("Group Delay Curve Selector")
            if c:
                c.items = list(gdly)

        if d.carregado:
            bol = d.mode_dis
            nomes = ["Up Conv." if d.is_if else "Rep. analógico", "inválido", "Tx DVB-T",
                     "Tx analógico (%s)" % (STD_ANA[d.std_ana] if 0 <= d.std_ana < 5 else "?"), "ISDB-T"]
            itens, vals, cmd_a, cmd_b = [], [], [], []
            for i, nm in enumerate(nomes):
                if i < len(bol) and bol[i]:
                    itens.append(nm)
                    vals.append(format(i, "08b"))
                    cmd_a.append("w200%02x\n\r" % i)
                    cmd_b.append("w210%02x\n\r" % i)
            for nome_, cmds in (("Mode A", cmd_a), ("Mode B", cmd_b)):
                c = self.nome(nome_)
                if c is not None:
                    c.items, c.values_on, c.command_items = itens, vals, cmds
            self._bol_mode(bol)
            self._standalone(d.standalone)
            self._controlador(d.standalone, not d.mediaset, bol)
            self._hw_type(d.hw_type, d.opto3_mode)
            if bol[3]:
                self._analogico(d)

        tem_cdef = tem(".cdef")
        for nome_ in ("Mode A", "Mode B"):
            c = self.nome(nome_)
            if c is not None and tem_cdef and tem(".dpwr") and tem(".apwr"):
                c.enabled = True

        if tem_cdef and canais is not None:
            rot = [s[3] for s in canais.saida]
            num = [int(s[0]) for s in canais.saida]
            for nome_ in ("cho_channel_a_out", "cho_channel_b_out"):
                c = self.nome(nome_)
                if c is not None:
                    c.enabled = True
                    c.do_set_state = True
                    c.items = rot
                    c.command_items = ["%02x" % n for n in num]
                    c.values_on = [format(n & 0xFF, "08b") for n in num]
            if d.mode_dis[0] and not d.is_if:
                rot_in = [s[3] for s in canais.entrada]
                num_in = [int(s[0]) for s in canais.entrada]
                for nome_ in ("channel_a_in", "channel_b_in"):
                    c = self.nome(nome_)
                    if c is not None:
                        c.enabled = True
                        c.do_set_state = True
                        c.items = rot_in
                        c.command_items = ["%02x" % n for n in num_in]
                        c.values_on = [format(n & 0xFF, "08b") for n in num_in]

        # entradas ITU470 (DOWNCV_TYPE)
        cvbs = d.downcv_type == 1
        for nome_ in ("Input ITU470a", "Input ITU470b"):
            c = self.nome(nome_)
            if c is not None:
                c.items = ["SDI 1", "SDI 2", "CVBS"] if cvbs else ["SDI 1", "SDI 2"]
                c.set_mask("00000011" if cvbs else "00000001")
        for t in self.telas:
            self._visibilidade_grupo(t.raiz, "panCvbsInput", cvbs)

    def _visibilidade_grupo(self, nos, var, vis):
        for n in nos:
            if n.var == var:
                n.visivel = vis
            self._visibilidade_grupo(n.filhos, var, vis)

    def _en(self, painel, var, valor):
        c = self.campo(painel, var)
        if c is not None:
            c.enabled = bool(valor)
            for s in c.subcampos:
                s.enabled = bool(valor)

    # ------------------------------------------------------------ grupos (Utility.enablePanel)
    def _nos_var(self, painel, var):
        """Nós com esse var dentro da tela cujo painel Java é `painel`."""
        achados = []

        def busca(nos):
            for n in nos:
                if n.var == var:
                    achados.append(n)
                busca(n.filhos)
        for t in self.telas:
            if t.painel == painel:
                busca(t.raiz)
        return achados

    @staticmethod
    def _campos_sob(no):
        out = []

        def junta(n):
            if n.campo is not None:
                out.append(n.campo)
                out.extend(n.campo.subcampos)
            for f in n.filhos:
                junta(f)
        junta(no)
        return out

    def _alvos(self, painel, var):
        c = self.campo(painel, var)
        if c is not None:
            return [c] + list(c.subcampos)
        out = []
        for n in self._nos_var(painel, var):
            out.extend(self._campos_sob(n))
        return out

    def _habilitar(self, painel, vars_, valor):
        for v in vars_:
            for c in self._alvos(painel, v):
                c.enabled = bool(valor)

    def _espera(self, painel, vars_, valor):
        for v in vars_:
            for c in self._alvos(painel, v):
                if c.enabled:
                    c.standby = bool(valor)

    def _remover_abas(self, tela_id, titulos):
        for t in self.telas:
            if t.id != tela_id:
                continue
            for n in t.raiz:
                if n.tipo == "abas":
                    n.filhos = [a for a in n.filhos if a.titulo not in titulos]

    # ------------------------------------------------------------ setBolMode
    def _bol_mode(self, bol):
        if self.familia != "isdbt":
            self._bol_mode_dvbt(bol)
            self.alarmes.ajustar(bol, self.defs)
            return
        P = "MbPanInputIsdbt"
        for v in ("mbStatAsi1", "mbStatAsi2", "mbStatAsi3", "mbStatAsi4", "mbStatGbeInput",
                  "mbCheAsi1EqBypass", "mbCheAsi2EqBypass"):
            self._en(P, v, bol[4])
        for v in ("mbStatSDI1", "mbStatSDI2"):
            self._en(P, v, bol[3])
        P = "MbPanSwitchIsdbtItu"
        for v in ("mbCheIIPerrorA", "mbCheIIPerrorB", "choInputHpA", "choInputHpB"):
            self._en(P, v, bol[4])
        for v in ("choAudioITUA", "choAudioITUB", "choInputITUA", "choInputITUB"):
            self._en(P, v, bol[3])
        for v in ("mbCheNoInputA", "mbCheNoInputB"):
            self._en(P, v, bol[4] or bol[3])
        # Modulação: sem modo analógico, a aba ITU some
        if not bol[3]:
            for t in self.telas:
                if t.id == "modulacao":
                    for n in t.raiz:
                        if n.tipo == "abas":
                            n.filhos = [a for a in n.filhos if a.titulo != "ITU"]
        P = "MbPanOutputIsdbt"
        for v in ("txtInputStatusGb1", "choInputGb1", "mbSend1", "outHpb"):
            self._en(P, v, bol[4])
        P = "MbPanNetworkIsdbt"
        for v in ("cheSendFramGb1", "txtTxStatus1", "mbIpGbTx", "mbPortTx", "mbMacDestination", "choTsPackFrame",
                  "mbNumSSRCGb1", "choRTPClock1", "choFrameType1", "choTsFormat1", "mbIGMP", "mbNumTxSourcePort",
                  "mbIpGb1", "mbNumPortGb1", "mbStatGbe4", "choTsPacket3"):
            self._en(P, v, bol[4])
        self.alarmes.ajustar(bol, self.defs)

    def _bol_mode_dvbt(self, bol):
        """setBolMode() dos painéis DVB-T (Initializer.initModes)."""
        dvb, ana = bol[2], bol[3]
        lp = self.campo("MbPanModDvbtItu", "mbTextMipLp")
        if lp is not None:
            lp.title = "Time Slicing LP"      # o original repete "HP" por engano
        self._habilitar("MbPanInputDvbt", ("mbStatAsi1", "mbStatAsi2", "mbStatAsi3", "mbStatAsi4", "mbStatGbe1",
                                           "mbStatGbe2", "mbCheASI1EqBypass", "mbCheASI2EqBypass"), dvb)
        self._habilitar("MbPanInputDvbt", ("mbStatSDI1", "mbStatSDI2"), ana)
        P = "MbPanSwitchDvbtItu"
        self._habilitar(P, ("panLedInput1HP", "panLedInput2HP", "panLedInput1LP", "panLedInput2LP",
                            "mbPanInput1Hp", "mbPanInput2Hp", "mbPanInput1Lp", "mbPanInput2lp",
                            "mbChoHPForceInput", "mbChoHPPriorityInput", "mbTextHPSelectedInput", "mbTextHPSwitchState",
                            "mbChoLPForceInput", "mbChoLPPriorityInput", "mbTextLPSelectedInput", "mbTextLPSwitchState",
                            "mbNumericAlarmDelay1", "choInput1HpA", "choInput1LpA", "choInput2HpA", "choInput2LpA"), dvb)
        self._habilitar(P, ("choInputITUA", "choAudioItuA"), ana)
        P = "MbPanModDvbtItu"
        self._habilitar(P, ("mbMFMip1", "mbModMip1", "mbModActual1", "mbModLocal1", "mbDvbMip1", "mbDvbLocal1",
                            "mbDvbActual1", "mbChoiceMfnSfn1", "mbCheckDeleteNullPck", "mbLPdetec", "mbMipHPDetect",
                            "mbTextMipHp", "mbTextMipLp", "mbMFLocal21", "mbMFActual1", "mbNumericAlarmDelay1",
                            "mbCheForceNullPk", "mbCheTestHole"), dvb)
        self._habilitar(P, ("mbPanModItu1",), ana)
        if dvb:   # MbMFMip.setBolMode(): funções que o ARK-T DVB-T não tem
            for n in self._nos_var(P, "mbMFMip1"):
                for c in self._campos_sob(n):
                    if c.var in ("chkTxPower", "chkFuncBw", "mbTxPower", "mbFuncBW", "mbLedFuncBw",
                                 "mbLedFunTag", "mbLedWait"):
                        c.enabled = False
        if not ana:
            self._remover_abas("modulacao", ("ITU",))
        if not dvb:
            self._remover_abas("modulacao", ("Modulation Parameters", "DVB-H Parameters", "MIP Functions"))
        self._habilitar("MbPanOutputDvbt", ("choInputHPA", "choInputHPB", "mbSend1", "mbSend2", "choInputGb1",
                                            "choInputGb2", "txtInpStatusGb2", "txtInpStatusGb1"), dvb)
        P = "MbPanNetworkDvbt"
        self._habilitar(P, ("enableA", "txtTxStatus1", "mbIpGb1", "mbPort1", "mbMacDestinationGb1", "choTsPacket1",
                            "mbNumSSRCGb1", "choTsClockGb1", "choFrameType1", "choTsFormat1", "enableB",
                            "txtTxStatus2", "mbIpGb2", "mbPort2", "mbMacDestinationGb2", "choTsPacket2",
                            "mbNumSSRCGb2", "choTsClockGb2", "choFrameType2", "choTsFormat2", "mbIpInputGb1",
                            "mbNumInputPortGb1", "mbStatInputGb1", "mbStatInputGbe1", "choTsInputClockGb1",
                            "mbIpInputGb2", "mbNumInputPortGb2", "mbStatInputGbe2", "choTsInputClockGb2"), dvb)
        self._habilitar(P, ("mbIGMP", "mbNumTxSourcePort"), dvb or bol[4])

    def _controlador(self, sa, nao_mediaset, bol):
        """setControllerMediaset() / setModMediaset(): o canal B e a
        comutação só são do ARK-T em modo standalone; no sistema MEDIASET o
        controlador externo manda também no canal A e no RF."""
        if self.familia == "isdbt":
            P = "MbPanOutputIsdbt"
            self._habilitar(P, ("mbButtonRf1", "choChannelOutputA", "numPowerADbm", "numPowerAW", "numFreqOffsetA"),
                            nao_mediaset)
            if not nao_mediaset:
                self._habilitar(P, ("panModeB",), False)
            return
        b = sa and nao_mediaset
        P = "MbPanSwitchDvbtItu"
        self._habilitar(P, ("mbNumTimeSetting", "mbTextAutoSwitch", "spnSwitchingTime"), sa)
        self._espera(P, ("mbNumTimeSetting",), not sa)
        self._habilitar(P, ("choModeA",), nao_mediaset)
        self._habilitar(P, ("choSwitchMode", "choManual", "choModeB"), b)
        self._habilitar(P, ("choInput1HpB", "choInput1LpB", "choInput2HpB", "choInput2LpB", "mbCheNoMipB",
                            "mbCheNoMipA"), bol[2] and sa)
        self._habilitar(P, ("mbCheNoInputB",), (bol[2] or bol[3]) and sa)
        self._habilitar(P, ("choInputITUB", "choAudioITUB"), bol[3] and sa)
        P = "MbPanModDvbtItu"
        off = nao_mediaset and bol[2]
        for grupo, vs in (("mbMFMip1", ("chkFreqOffset", "chkTimeOffset")),
                          ("mbMFLocal21", ("mbNumFrequencyOffset", "mbNumTimeOffset"))):
            for n in self._nos_var(P, grupo):
                for c in self._campos_sob(n):
                    if c.var in vs:
                        c.enabled = off
        P = "MbPanOutputDvbt"
        self._habilitar(P, ("choChannelOutputB", "numPowerBDbm", "numPowerBW", "numFreqOffsetB"), b)
        self._habilitar(P, ("mbButtonRf1", "choChannelOutputA", "numPowerADbm", "numPowerAW", "numFreqOffsetA"),
                        nao_mediaset)
        self._espera(P, ("numFreqOffsetB", "numPowerBW", "numPowerBDbm"), not sa)
        led = self.campo(P, "mbLed4")
        if led is not None and not sa:
            led.title = "N.A."

    def _analogico(self, d):
        """Initializer: tipo de áudio e sistema de som conforme STD_ANA."""
        at, ss = self.nome("Audio_Type"), self.nome("Sound_System")
        itens = ["Mono Dual Carrier", "Dual Sound", "Stereo", "Mono Single Carrier"]
        vals = ["00000000", "00000001", "00000010", "00000011"]
        n = d.std_ana
        if n in (2, 3, 4):
            if d.btsc:
                itens, vals = ["Mono Single Carrier", "BTSC"], ["00000011", "00000111"]
            else:
                itens, vals = ["Mono Single Carrier"], ["00000011"]
        if n in (2, 3, 4):
            som = ["FM 4.5"]
        elif n == 1:
            som = ["FM 6.5 / FM 6.742", "FM 6.5 / FM 6.258"]
        else:
            som = ["FM 5.5 / FM 5.742"]
        if at is not None:
            at.items, at.values_on = itens, vals
        if ss is not None:
            ss.items = som
            if n != 1:
                ss.do_set_state = False
                ss.sel = 0

    def _estado_dvbt(self, st, cfg):
        """setState() dos painéis DVB-T a cada leitura."""
        dvb, ana = cfg == 2, cfg == 3
        self._espera("MbPanInputDvbt", ("mbStatAsi1", "mbStatAsi2", "mbStatAsi3", "mbStatAsi4", "mbStatGbe1",
                                        "mbStatGbe2"), not dvb)
        self._espera("MbPanInputDvbt", ("mbStatSDI1", "mbStatSDI2"), not ana)
        # rede
        P = "MbPanNetworkDvbt"
        if self.defs.mode_dis[2]:
            self._habilitar(P, ("enableA", "enableB"), dvb)
            self._habilitar(P, ("mbIGMP",), cfg in (2, 4))
        for fmt_v, pk_v in (("choTsFormat1", "choTsPacket1"), ("choTsFormat2", "choTsPacket2")):
            fmt, pk = self.campo(P, fmt_v), self.campo(P, pk_v)
            if fmt is not None and pk is not None:
                n = 6 if st[fmt.index] == 0 else 7
                if len(pk.items) != n:
                    pk.items = ["%d packet%s" % (k, "" if k == 1 else "s") for k in range(1, n + 1)]
                    pk.values_on = [format(k, "016b") if len(pk.values_on[0] if pk.values_on else "") == 16
                                    else format(k, "08b") for k in range(1, n + 1)]
        self._espera(P, ("mbStatInputGbe1", "mbStatInputGbe2"), not dvb)
        # saída
        if self.defs.mode_dis[2]:
            self._habilitar("MbPanOutputDvbt", ("mbSend1", "mbSend2"), dvb)
        # comutação
        P = "MbPanSwitchDvbtItu"
        mfn = self.nome("MFN-SFN")
        sfn = False
        if mfn is not None:
            mfn.ler(st)
            sfn = mfn.sel in (2, 3)
        self._habilitar(P, ("panInputAutoswitch",), not sfn)
        for g in ("mbPanInput1Hp", "mbPanInput2Hp", "mbPanInput1Lp", "mbPanInput2lp"):
            for n in self._nos_var(P, g):
                for c in self._campos_sob(n):
                    if c.var == "mbCheckPMTCRC":
                        c.enabled = False
        self._espera(P, ("mbPanInput1Hp", "mbPanInput2Hp", "mbPanInput1Lp", "mbPanInput2lp", "panLedInput1HP",
                         "panLedInput1LP", "panLedInput2HP", "panLedInput2LP", "mbTextHPSelectedInput",
                         "mbTextLPSelectedInput", "mbTextHPSwitchState", "mbTextLPSwitchState"), not dvb)
        # modulação
        P = "MbPanModDvbtItu"
        self._espera(P, ("panMipDection", "mbModActual1", "mbModMip1", "mbDvbActual1", "mbDvbMip1", "mbMFActual1",
                         "mbMFMip1"), not dvb)
        lp = ((st[285] << 8) | st[286]) != 0
        if self.defs.mode_dis[2]:
            self._habilitar(P, ("mbLPdetec",), lp)
            self._espera(P, ("mbTextMipLp",), not lp)
            self._habilitar(P, ("mbCheckDeleteNullPck",), not sfn)

    def _standalone(self, sa):
        """setModeStanAlone(): em modo Driver a comutação é do controlador."""
        for P in ("MbPanSwitchIsdbtItu", "MbPanSwitchDvbtItu", "MbPanSwitchRepAna"):
            for v in ("choSwitchMode", "choManual", "choModeB"):
                c = self.campo(P, v)
                if c is not None:
                    c.enabled = sa
            c = self.campo(P, "choModeA")
            if c is not None and any(".cdef" in a for a in self.arquivos):
                c.enabled = sa

    def _hw_type(self, hw, opto3):
        P = "MbPanOutputIsdbt" if self.familia == "isdbt" else "MbPanOutputDvbt"
        g = lambda v: self.campo(P, v)  # noqa: E731
        led = g("mbLed11")
        if led is not None:
            if opto3 == 1:
                led.title, led.cor_off = "Interlock", "#ff0000"
            else:
                led.title, led.cor_off = "Stand-by", "#c0c0c0"
        cfg = {
            0: dict(off=["txtFan3", "txtFan4", "txtTemp200w", "txtVoltage3", "txtCurrent3", "txtVoltage24b", "txtVoltage24"],
                    on=[], fan2=175, fan3=177, v="PS1 28 V", i="PS1 Current 28 V [A]", opto2="N.A."),
            1: dict(off=["txtCurrent3", "txtVoltage3", "txtVoltage24b"], on=["txtFan3", "txtFan4", "txtTemp200w", "txtVoltage24"],
                    fan2=177, fan3=175, v="PS1 42 V", i="PS1 Current 42 V [A]", opto2="Retry"),
            2: dict(off=["txtFan1"], on=["txtFan3", "txtFan4", "txtCurrent3", "txtTemp200w", "txtVoltage3", "txtVoltage24", "txtVoltage24b"],
                    fan2=175, fan3=177, v="PS1 42 V", i="PS1 Current PSU 42 V [A]", opto2="N.A."),
        }.get(hw)
        if not cfg:
            return
        for v in cfg["off"]:
            self._en(P, v, False)
        for v in cfg["on"]:
            self._en(P, v, True)
        for v, idx in (("txtFan2", cfg["fan2"]), ("txtFan3", cfg["fan3"])):
            c = g(v)
            if c is not None:
                c.index = idx
        for v, t in (("txtVoltage", cfg["v"]), ("txtCurrent", cfg["i"]), ("ledOpto2", cfg["opto2"])):
            c = g(v)
            if c is not None:
                c.title = t

    # ------------------------------------------------------------ a cada leitura
    def atualizar(self, st: bytes):
        """Reproduz os setState() dos painéis antes de redesenhar."""
        self.status = st
        cfg = self.config_em_uso(st)
        if self.familia == "isdbt":
            P = "MbPanInputIsdbt"
            for v in ("mbStatAsi1", "mbStatAsi2", "mbStatAsi3", "mbStatAsi4", "mbStatGbeInput"):
                c = self.campo(P, v)
                if c is not None and c.enabled:
                    c.standby = cfg != 4
            for v in ("mbStatSDI1", "mbStatSDI2"):
                c = self.campo(P, v)
                if c is not None and c.enabled:
                    c.standby = cfg != 3
            P = "MbPanNetworkIsdbt"
            c = self.campo(P, "cheSendFramGb1")
            if c is not None and self.defs.mode_dis[4]:
                c.enabled = cfg == 4
            fmt = self.campo(P, "choTsFormat1")
            pk = self.campo(P, "choTsPackFrame")
            if fmt is not None and pk is not None:
                n = 6 if st[fmt.index] == 0 else 7
                if len(pk.items) != n:
                    pk.items = ["%d pacote%s" % (k, "" if k == 1 else "s") for k in range(1, n + 1)]
                    pk.values_on = [format(k, "08b") for k in range(1, n + 1)]
            c = self.campo(P, "mbStatGbe4")
            if c is not None and c.enabled:
                c.standby = cfg != 4
            c = self.campo("MbPanOutputIsdbt", "mbSend1")
            if c is not None and self.defs.mode_dis[4]:
                c.enabled = cfg == 4
            # MbPanModIsdbt
            P = "MbPanModIsdbt"
            pres = self.campo(P, "mbIIPpresent")
            val = self.campo(P, "mbIIPvalid")
            if pres is not None and val is not None:
                val.standby = (1 & st[pres.index]) != 1
            sync = self.campo(P, "mbTxtChoiceSyncId")
            if sync is not None:
                sync.extras["forcar_texto"] = sync.items[0] if st[sync.index] == 0 else sync.items[1]
            led = self.campo(P, "ledDefinedInIip")
            flag = self.campo(P, "txtStaticDelayFlag")
            off = self.campo(P, "txtTimeOffset")
            if led is not None and flag is not None and off is not None:
                definido = led.ler(st).ligado
                if not definido:
                    flag.extras["forcar_texto"] = "— (Time Reference Used)"
                    off.extras["forcar_texto"] = "— (0)"
                else:
                    flag.extras.pop("forcar_texto", None)
                    off.extras.pop("forcar_texto", None)
        else:
            self._estado_dvbt(st, cfg)
        # MbPanModItu (aba ITU / analógico)
        P = "MbPanModItu"
        a1, a2, wl = self.campo(P, "mbTextFieldAudio1"), self.campo(P, "mbTextFieldAudio2"), self.campo(P, "mbTextFieldWhiteAudio")
        at = self.campo(P, "choAudioType")
        if a1 is not None:
            b3 = (1 & st[195]) == 0
            b4 = at is not None and (3 & st[at.index]) == 3
            a1.standby = b3
            if a2 is not None:
                a2.standby = b3 or b4
            if wl is not None:
                wl.standby = b3
        for v in ("txtTxtEmphasis", "checkEmphasisDisable"):
            c = self.campo(P, v)
            if c is not None:
                c.enabled = cfg != 4
        # faixas de offset conforme a banda do canal (MbChoiceChannelOut)
        if self.canais is not None:
            for ch, off in (("cho_channel_a_out", "offset_a"), ("cho_channel_b_out", "offset_b")):
                c, o = self.nome(ch), self.nome(off)
                if c is None or o is None or not c.items:
                    continue
                _, sel = c.valor_status(st)
                if 0 <= sel < len(self.canais.saida):
                    try:
                        banda = int(self.canais.saida[sel][2])
                        o.minimo, o.maximo = -(banda * 1000000) // 2, banda * 1000000 // 2
                    except ValueError:
                        pass
        self._potencias(st)

    def _potencias(self, st):
        """Initializer.setPowerRanges(): faixa de potência pelo .dpwr/.apwr."""
        for n, sufixo in ((0, "a"), (1, "b")):
            cfg = self.config_modo(n, st)
            digital = cfg in (2, 4)
            passos = self.passos_dpwr if digital else self.passos_apwr
            if not passos:
                continue
            lo, hi = int(passos[0] / 10), int(passos[-1] / 10)
            c = self.nome("power_%s_dbm" % sufixo)
            if c is not None:
                c.dmin, c.dmax = float(lo), float(hi)
            c = self.nome("power_%s_w" % sufixo)
            if c is not None:
                c.dmin, c.dmax = 10 ** (lo / 10.0) / 1000.0, 10 ** (hi / 10.0) / 1000.0

    # ------------------------------------------------------------ utilidades
    def numero_status(self, n, tam, invertido):
        """Utility.getNumberOfStatus (usado no Info)."""
        st = self.status
        if tam == 1:
            return st[n]
        v = 0
        for i in range(0, tam, 2):
            a, b = st[n + i], st[n + i + 1]
            if invertido:
                v += (b << 8 * (tam - 1 - i)) + (a << 8 * (tam - 2 - i))
            else:
                v += (a << 8 * (tam - 1 - i)) + (b << 8 * (tam - 2 - i))
        return v

    def numeros_de_serie(self):
        g = self.numero_status
        nr = "não gravado"

        def data(a, b, c):
            x = g(a, 2, False)
            return "%d - %d/%02d" % (x, g(b, 1, False), g(c, 1, False)) if x else nr

        l1, l2 = g(1017, 4, False), g(1021, 4, False)
        ark = g(343, 8, True)
        psu = g(335, 8, True)
        up = g(733, 6, False)
        return [
            ("Número de série do equipamento", "%d-%d" % (l1, l2) if l1 else nr),
            ("ARK-T — ID único", str((ark & 0xFFFFFFFFFFFF) >> 8) if ark else ""),
            ("ARK-T — ID da família", str(g(349, 1, True)) if g(349, 1, True) else ""),
            ("ARK-T — número de série", data(1025, 1027, 1028)),
            ("Down-converter — número de série", data(1029, 1031, 1032)),
            ("Up-converter — ID único", str(up) if up else ""),
            ("Up-converter — ID da família", str(g(732, 1, False)) if g(732, 1, False) else ""),
            ("Up-converter — número de série", data(1033, 1035, 1036)),
            ("Fonte (PSU) — ID único", str((psu & 0xFFFFFFFFFFFF) >> 8) if psu else ""),
            ("Fonte (PSU) — ID da família", str(g(341, 1, False)) if g(341, 1, False) else ""),
            ("Fonte (PSU) — número de série", data(1037, 1039, 1040)),
            ("Amplificador — número de série", data(1041, 1043, 1044)),
        ]

    def versao_upconverter(self):
        a, b = self.status[739], self.status[740]
        return "%d.%d" % (a, b) if a else ""


# ==================================================================== alarmes
COLUNAS = ["GUI", "LCD", "Evento", "R0", "R1", "R2", "R3", "T0", "T1", "T2", "T3", "T4", "T5", "T6", "T7", "RF"]
# coluna -> índice-base no status (bit = linha % 8, byte = base - linha // 8)
BASE_LEITURA = {1: 672, 2: 668, 3: 676, 4: 652, 5: 656, 6: 660, 7: 664,
                8: 620, 9: 624, 10: 628, 11: 632, 12: 636, 13: 640, 14: 644, 15: 648, 16: 680}
# coluna -> registro base do comando w2XX
BASE_ESCRITA = {1: 151, 2: 147, 3: 155, 4: 131, 5: 135, 6: 139, 7: 143, 8: 99, 9: 103, 10: 107,
                11: 111, 12: 115, 13: 119, 14: 123, 15: 127, 16: 159}
DESCRICAO_COLUNAS = {
    "GUI": "Mostrar no programa", "LCD": "Mostrar no display", "Evento": "Gravar no histórico",
    "R0": "Relé 0", "R1": "Relé 1", "R2": "Relé 2", "R3": "Relé 3",
    "T0": "Trap SNMP para o destino 0", "T1": "Trap destino 1", "T2": "Trap destino 2", "T3": "Trap destino 3",
    "T4": "Trap destino 4", "T5": "Trap destino 5", "T6": "Trap destino 6", "T7": "Trap destino 7",
    "RF": "Desliga o RF",
}


class Alarmes:
    """Tabela de alarmes (MbPanAlarmsIsdbt / MbPanAlarmsDvbt)."""

    def __init__(self, modelo: Modelo):
        self.m = modelo
        chave = "TITLE_ROW_ISDBT" if modelo.familia == "isdbt" else "TITLE_ROW_DVBT"
        self.linhas = modelo.bundle.get(chave, "").split(",")
        self.nao_usadas = [13, 19, 20, 21, 22] if modelo.familia == "isdbt" else [22]
        self.rf_editaveis = [int(x) for x in modelo.bundle.get("ROWS_EDITABLE_IN_RF_COLUMN_NO_AN_REP", "").split(",") if x]

    def ajustar(self, bol, defs):
        if self.m.familia != "isdbt":
            if defs.hw_type == 2:
                self.linhas = self.m.bundle.get("TITLE_ROW_DVBT_HW_TYPE_2", "").split(",")
            return
        if bol[0]:
            self.linhas[19] = "Down Converter Osc. Unlock"
            self.linhas[20] = "No IF Input" if defs.is_if else "No RF Input"
            self.linhas[21] = "IF Input Squelch" if defs.is_if else "RF Input Squelch"
            for k in (1, 2, 3):
                self.nao_usadas[k] = -1
            self.rf_editaveis = [int(x) for x in self.m.bundle.get("ROWS_EDITABLE_IN_RF_COLUMN_YES_AN_REP", "").split(",") if x]
        if defs.opto3_mode == 1:
            self.nao_usadas[4] = -1
            self.linhas[22] = "Interlock alarm"
        if defs.hw_type == 2:
            self.linhas[1] = "PS1/PS2 Voltage Alarm"
            self.linhas[2] = "PS1/PS2 Current Alarm"

    def ler(self, st=None):
        st = st or self.m.status
        out = []
        for r, nome in enumerate(self.linhas):
            b = r % 8
            ativo = (st[764 - r // 8] & (1 << b)) != 0
            nao_usada = r in self.nao_usadas or nome == "Not Used"
            texto = nome
            if nome == "Fan speed" and ativo:
                n5 = st[753] & 0xF
                dual = self.m.defs.hw_type == 1
                fans = []
                if n5 & 1:
                    fans.append("Fan 1")
                if n5 & 2:
                    fans.append("Fan 3" if dual else "Fan 2")
                if n5 & 4:
                    fans.append("Fan 2" if dual else "Fan 3")
                if n5 & 8:
                    fans.append("Fan 4")
                texto = "Fan speed (%s)" % ", ".join(fans) if fans else nome
            cols = [(st[BASE_LEITURA[c] - r // 8] & (1 << b)) != 0 for c in range(1, 17)]
            out.append(dict(linha=r, nome=texto, ativo=ativo and not nao_usada, nao_usada=nao_usada, colunas=cols))
        return out

    def editavel(self, linha, coluna):
        if linha in self.nao_usadas:
            return False
        if coluna == 16 and linha not in self.rf_editaveis:
            return False
        return 1 <= coluna <= 16

    def comando(self, linha, coluna, valor, st=None):
        st = st or self.m.status
        if not self.editavel(linha, coluna):
            raise C.Recusado("Esta célula não pode ser alterada")
        reg = BASE_ESCRITA[coluna] - linha // 8
        atual = st[reg + 521]
        b = linha % 8
        novo = (atual | (1 << b)) if valor else (atual & (255 - (1 << b)))
        return C.Cmd("w2" + format(reg, "x") + "%02x" % novo + "\n\r", 2)

    def total_ligado(self, st=None):
        """Estado do 'Total' (todos os alarmes habilitados)."""
        st = st or self.m.status
        nu = self.nao_usadas
        for col in range(16):
            ok = False
            for n3 in range(99 + col * 4, 96 + col * 4 - 1, -1):
                n2 = 0
                for x in nu:
                    if 3 - x // 8 == n3 - (96 + col * 4):
                        n2 += 2 ** (x % 8)
                if (st[521 + n3] & n2) != 0:
                    ok = True
                    break
            if ok:
                return False
        for n4 in range(159, 155, -1):
            n3 = 0
            for x in self.rf_editaveis:
                if 3 - x // 8 == n4 - 156:
                    n3 += 2 ** (x % 8)
            if (st[521 + n4] & n3) != n3:
                return False
        return True

    def comandos_total(self, ligar: bool, st=None):
        """chkTotal: habilita (ligar=True) ou desabilita todos os alarmes."""
        st = st or self.m.status
        esta_ligado = not ligar
        cmds = [C.Cmd("w2c0" + ("00" if esta_ligado else "ff") + "\n\r", 2)]
        for n3 in range(96, 156):
            n2 = 0
            for x in self.nao_usadas:
                if x == -1:
                    continue
                if (n3 - 96) % 4 == (32 - x) // 8:
                    n2 += int(2 ** (8 - (32 - x) % 8))
            n = 0 if esta_ligado else 255 - n2
            cmds.append(C.Cmd("w2%02x%02x\n\r" % (n3, n & 0xFF), 2))
        for n3 in range(159, 155, -1):
            n2 = st[n3 + 521]
            n = 0
            for x in self.rf_editaveis:
                if 3 - x // 8 == n3 - 156:
                    n += 2 ** (x % 8)
            n4 = (n2 & (255 - n)) if esta_ligado else (n2 | n)
            cmds.append(C.Cmd("w2%02x%02x\n\r" % (n3, n4 & 0xFF), 2))
        return cmds

