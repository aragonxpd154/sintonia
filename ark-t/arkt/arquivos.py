"""Arquivos que o excitador publica por HTTP (.def, .cdef, .cfg, .dpwr/.apwr)
e a lista de arquivos devolvida pelo comando `yh`."""
from __future__ import annotations

from dataclasses import dataclass, field


def lista_de_arquivos(resposta: str) -> list[str]:
    """Interpreta a resposta do comando 'yh' (ListFile.getListFile)."""
    nomes = []
    n2 = 18
    n3 = resposta.find("\t", n2)
    while n3 != -1:
        nomes.append(resposta[n2 + 12:n3])
        n2 = n3 + 1
        n3 = resposta.find("\t", n2)
    return nomes


def procurar(nomes, extensao):
    """ListFile.getFile(): o último nome que contém a extensão."""
    achado = None
    for n in nomes:
        if extensao in n:
            achado = n
    return achado


def _campo(texto, chave):
    i = texto.find(chave)
    if i < 0:
        return None
    ini = i + len(chave) + 1
    fim = texto.find("\r\n", ini)
    if fim < 0:
        fim = texto.find("\n", ini)
    if fim < 0:
        fim = len(texto)
    return texto[ini:fim]


def _int(texto, chave, padrao=0):
    v = _campo(texto, chave)
    try:
        return int(v.strip()) if v is not None else padrao
    except ValueError:
        return padrao


@dataclass
class DefinicaoSistema:
    """SystemDefFile (.def)."""
    nome_arquivo: str = ""
    hw_type: int = 0
    sys_cust: str = ""
    sys_name: str = ""
    curve_mode: int = 0
    agc_mode: int = 0
    mode_name: str = ""
    tuner_rev: int = 0
    rflev_dig: int = 0
    rflev_ana: int = 0
    mode_dis: list = field(default_factory=lambda: [True, True, True, True, False])
    std_ana: int = 0
    dev_delay: str = ""
    sys_opt: str = ""
    opto3_mode: int = 0
    btsc: bool = False
    downcv_type: int = 0
    carregado: bool = False

    @classmethod
    def ler(cls, texto: str, nome=""):
        d = cls(nome_arquivo=nome, carregado=True)
        d.sys_cust = (_campo(texto, "SYS_CUST") or "").strip()
        d.hw_type = _int(texto, "HW_TYPE")
        d.sys_name = (_campo(texto, "SYS_NAME") or "").strip()
        d.curve_mode = _int(texto, "CURVE_MODE")
        d.agc_mode = _int(texto, "AGC_MODE")
        d.mode_name = (_campo(texto, "MODE_NAME") or "").strip()
        d.tuner_rev = _int(texto, "TUNER_REV")
        d.rflev_dig = _int(texto, "RFLEV_DIG")
        d.rflev_ana = _int(texto, "RFLEV_ANA")
        md = _campo(texto, "MODE_DIS")
        if md is not None:
            d.mode_dis = ["1" not in x for x in md.split(",")]
            while len(d.mode_dis) < 5:
                d.mode_dis.append(False)
        d.std_ana = _int(texto, "STD_ANA")
        d.dev_delay = (_campo(texto, "DEV_DELAY") or "").strip()
        d.sys_opt = (_campo(texto, "SYS_OPT") or "").strip()
        d.opto3_mode = _int(texto, "OPTO3_MODE")
        d.btsc = _int(texto, "BTSC_EN") == 1
        d.downcv_type = _int(texto, "DOWNCV_TYPE")
        return d

    @property
    def standalone(self):
        return self.curve_mode == 0

    @property
    def is_if(self):
        return self.downcv_type == 2

    @property
    def familia(self):
        """'isdbt' ou 'dvbt' — escolhe o conjunto de telas (MbPanelsScroller)."""
        if (not self.mode_dis[4]) and (not self.mode_dis[0]):
            return "dvbt"
        return "isdbt"

    @property
    def mediaset(self):
        return self.sys_opt == "MEDIASET"


@dataclass
class TabelaCanais:
    """CdefFile (.cdef)."""
    entrada: list = field(default_factory=list)   # [(canal, freq, banda, rótulo)]
    saida: list = field(default_factory=list)
    modo_saida: int = 0
    indices: list = field(default_factory=list)   # índice na pré-correção (getOutChannelsIndex)

    @classmethod
    def ler(cls, texto: str):
        t = cls()
        linhas = texto.split("\n")
        n_in = int(linhas[0].split(";")[0].strip())
        for k in range(n_in):
            p = [x.strip() for x in linhas[k + 1].split(";")]
            t.entrada.append((p[0], p[1], p[2], p[3]))
        base = n_in + 1
        cab = linhas[base].split(";")
        n_out = int(cab[0].strip())
        t.modo_saida = int(cab[1].strip())
        m = t.modo_saida
        for k in range(n_out):
            p = [x.strip() for x in linhas[base + 1 + k].split(";")]
            t.saida.append((p[0 + m], p[1 + m], p[2 + m], p[3 + m]))
            t.indices.append(k if m == 0 else int(p[0]))
        return t


def passos_potencia(dados: bytes):
    """DpwrFile/ApwrFile: devolve os passos de potência (em 0,1 dBm)."""
    v = [((dados[i * 2] & 0xFF) << 8) + (dados[i * 2 + 1] & 0xFF) for i in range(len(dados) // 2)]
    n_passos = v[0]
    n, n2 = v[1], v[2]
    desloc = 4 * n_passos * n + n * 2 + n * n2
    return [v[i + 4 + desloc] for i in range(n_passos)]


def projeto_cfg(texto: str):
    """ConfigFileRead (.cfg): a 5ª linha é o nome do projeto/instalador."""
    linhas = texto.split("\r\n")
    return linhas[4].strip() if len(linhas) > 4 else ""
