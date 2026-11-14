"""Histórico de eventos do excitador (comando g4XX, 8 eventos de 32 bytes por
página) — tradução de mb.toaster.Event.encodeEvent()."""
from __future__ import annotations

from dataclasses import dataclass

TIPO_COMANDO = "comando"
TIPO_ALARME = "alarme"
TIPO_EVENTO = "evento"
TIPO_INICIO = "inicio"
TIPO_DESCONHECIDO = "desconhecido"

ORIGENS = {0: "Serial (RS232)", 2: "Ethernet", 3: "display LCD", 5: "SNMP"}


@dataclass
class Evento:
    data: str
    hora: str
    tipo: str
    texto: str
    origem: str = ""

    def linha(self):
        return "%s %s  %s" % (self.data, self.hora, self.texto)


def _sel(v, mapa, padrao=None):
    if v == 0:
        return None
    return mapa.get(v, padrao)


def decodificar(hex64: str) -> Evento:
    b = [int(hex64[i * 2:i * 2 + 2], 16) for i in range(32)]
    hora = "%02d:%02d:%02d" % (b[2], b[1], b[0])
    data = "%02d/%02d/%04d" % (b[3], b[4], 2000 + b[5])
    cod = b[6]
    if cod == 0:
        partes = ["Inicialização do sistema"]
        if b[7]:
            partes.append("erro na partição do sistema de arquivos")
        if b[8]:
            partes.append("arquivo de configuração (*.cfg): " + ("não encontrado" if b[8] == 1 else "corrompido"))
        if b[9]:
            partes.append("arquivo de definição (*.def): " + ("não encontrado" if b[9] == 1 else "corrompido"))
        if b[10]:
            partes.append("display LCD não encontrado")
        if b[11]:
            partes.append("PLL destravado")
        x = _sel(b[12], {1: "erro ao apagar a configuração da FPGA",
                         2: "configuração inválida (carregada, mas a FPGA não inicia)",
                         16: "arquivo da FPGA não encontrado"}, "arquivo da FPGA inválido")
        if x:
            partes.append(x)
        x = _sel(b[13], {1: "erro ao abrir o arquivo .sav", 16: "arquivo .sav não encontrado"}, "arquivo .sav inválido")
        if x:
            partes.append(x)
        x = _sel(b[14], {1: "SNMP: arquivo não encontrado", 2: "SNMP: erro ao abrir arquivo",
                         3: "SNMP: erro ao iniciar o socket UDP", 4: "SNMP: não foi possível abrir a porta 161"})
        if x:
            partes.append(x)
        n2 = b[15]
        if n2 == 1:
            partes.append("calibração do modo atual não encontrada")
        elif n2 == 2:
            partes.append("erro ao abrir a calibração do modo atual")
        elif 3 <= n2 <= 18:
            partes.append("calibração do modo atual com erro de sintaxe")
        elif n2 == 32:
            partes.append("calibração do modo em desuso não encontrada")
        elif n2 == 33:
            partes.append("erro ao abrir a calibração do modo em desuso")
        elif 34 <= n2 <= 38:
            partes.append("calibração do modo em desuso com erro de sintaxe")
        x = _sel(b[16], {1: "pré-correção (*.apre *.dpre) não encontrada",
                         2: "erro ao abrir a pré-correção (*.apre *.dpre)"}, "pré-correção (*.apre *.dpre) inválida")
        if x:
            partes.append(x)
        x = _sel(b[17], {1: "pré-correção linear (*.alin *.dlin) não encontrada",
                         2: "erro ao abrir a pré-correção linear (*.alin *.dlin)"}, "pré-correção linear (*.alin *.dlin) inválida")
        if x:
            partes.append(x)
        x = _sel(b[18], {1: "PLL do down-converter destravado"}, "PLL do down-converter desabilitado")
        if x:
            partes.append(x)
        x = _sel(b[19], {1: "up-converter não encontrado", 2: "up-converter não responde corretamente",
                         16: "up-converter desabilitado"})
        if x:
            partes.append(x)
        x = _sel(b[20], {1: "filtro de canal (*.chf) não encontrado", 2: "erro ao abrir o filtro de canal (*.chf)"},
                 "filtro de canal (*.chf) inválido")
        if x:
            partes.append(x)
        return Evento(data, hora, TIPO_INICIO, " — ".join(partes))
    if cod == 1:
        cmd = []
        for i in range(8, 32):
            if b[i] == 0:
                break
            if b[i] in (10, 13):
                continue
            cmd.append(chr(b[i]))
        origem = ORIGENS.get(b[7], "origem desconhecida %d" % b[7])
        return Evento(data, hora, TIPO_COMANDO, 'Comando "%s" via %s' % ("".join(cmd), origem), origem)
    if cod in (2, 3):
        txt = []
        for i in range(7, 32):
            if b[i] == 0:
                break
            txt.append(chr(b[i]))
        return Evento(data, hora, TIPO_ALARME if cod == 2 else TIPO_EVENTO, "".join(txt))
    return Evento(data, hora, TIPO_DESCONHECIDO, "Evento não codificado (%d)" % cod)


def contagem(st: bytes, indice=790):
    """(número de eventos, tabela cheia, máximo) — MbPanEvents2.setState2."""
    n = (st[indice] << 8) + st[indice + 1]
    cheia = (st[indice + 2] & 1) == 1
    maximo = (st[765] << 8) + st[766]
    return n, cheia, maximo or 1008


def montar_historico(paginas_hex: str, n: int, cheia: bool, maximo: int):
    """Ordena do mais novo para o mais antigo, como showHistory()."""
    eventos = []
    total = len(paginas_hex) // 64
    for k in range(n - 1, -1, -1):
        if k < total:
            eventos.append(decodificar(paginas_hex[k * 64:k * 64 + 64]))
    if cheia:
        for k in range(maximo - 1, n - 1, -1):
            if k < total:
                eventos.append(decodificar(paginas_hex[k * 64:k * 64 + 64]))
    return eventos
