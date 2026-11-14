"""Simulador de um excitador ARK-T (ISDB-T) para testes e demonstração.

Abre a porta TCP de comandos (padrão 10001) e um servidor HTTP com os
arquivos de definição. As escritas alteram o bloco de status usando o mesmo
mapeamento de índices das telas, então o que se grava aparece na leitura.
"""
from __future__ import annotations

import http.server
import math
import random
import socketserver
import struct
import threading
import os
import time
from datetime import datetime, timezone

from . import campos as C
from .arquivos import DefinicaoSistema
from .modelo import Modelo

DEF = (
    "HW_TYPE=0\r\nSYS_CUST=SIMULADOR\r\nSYS_NAME=ARK-T ISDB-T\r\nCURVE_MODE=0\r\nAGC_MODE=1\r\n"
    "MODE_NAME=ISDBT\r\nTUNER_REV=0\r\nAGC_THRL=10\r\nAGC_THRH=20\r\nRFLEV_DIG=-90\r\nRFLEV_ANA=-80\r\n"
    "MODE_DIS=1,1,1,0,0\r\nSTD_ANA=2\r\nDEV_DELAY=0\r\nSYS_OPT=NONE\r\nOPTO3_MODE=0\r\nBTSC_EN=0\r\nDOWNCV_TYPE=0\r\n"
)
CFG = "ARKT\r\n1\r\n2\r\n3\r\nTransmissao - Simulador\r\n"


def _cdef():
    linhas = ["0;"]
    canais = list(range(14, 70))
    linhas.append("%d;0" % len(canais))
    for ch in canais:
        f = 473 + (ch - 14) * 6 + 1 / 7
        linhas.append("%d;%.6f;6;Canal %d (%.3f MHz)" % (ch, f, ch, f))
    return "\n".join(linhas) + "\n"


def _dpwr():
    passos = [300, 330, 360, 400, 430]
    n, n2, n3 = 1, 1, 0
    palavras = [len(passos), n, n2, n3] + [0] * (4 * len(passos) * n + n * 2 + n * n2) + passos
    return b"".join(struct.pack(">H", p) for p in palavras)


def _precorrecao():
    """.dpre e .dlin de exemplo gerados pelo próprio motor do programa."""
    from . import precorrecao as P
    pre = P.ArquivoPre(5, 56, nome="SIMULADOR.dpre")
    for c in range(56):
        for k in range(5):
            am = P.Curva(P.AM, [[0, 2559], [300, 2400 - 40 * k], [511, 1900 - 60 * k]])
            pm = P.Curva(P.PM, [[0, 32767], [600, 31000 - 300 * k], [1023, 29000 - 500 * k]])
            pre.am[c][k], pre.pm[c][k] = am, pm
            pre.definir_curva(c, k, True, P.am_para_equipamento(am.pontos()))
            pre.definir_curva(c, k, False, P.pm_para_equipamento(pm.pontos()))
    lin = P.ArquivoLinear(nome="SIMULADOR.dlin")
    lin.modulo = P.Curva(P.MODULO, [[0, 4300], [700, 4000], [1350, 4000], [2047, 4300]])
    lin.fase = P.Curva(P.FASE, [[0, 92000], [1024, 89999], [2047, 92000]])
    return pre.bytes_completo("SIMULADOR.dpre"), lin.bytes_completo("SIMULADOR.ldknb")


ARQUIVOS = {
    "ARKT_ISDBT.def": DEF.encode(),
    "canais.cdef": _cdef().encode(),
    "instalador.cfg": CFG.encode("latin-1"),
    "config.sav": b"[ARK-T]\r\n; configuracao simulada\r\n",
    "potencia.dpwr": _dpwr(),
    "potencia.apwr": _dpwr(),
    "gui.properties": b"# propriedades da GUI\n",
}
ARQUIVOS["SIMULADOR.dpre"], ARQUIVOS["SIMULADOR.dlin"] = _precorrecao()
USUARIO, SENHA = "admin", "admin"
PADRAO = "isdbt"


def publicar_jar(caminho):
    """Publica um .jar na lista de arquivos, como o equipamento real faz."""
    with open(caminho, "rb") as fh:
        ARQUIVOS[os.path.basename(caminho)] = fh.read()


def usar_dvbt():
    """Troca o simulador para um ARK-T DVB-T (modo A DVB-T, modo B analógico)."""
    global PADRAO
    PADRAO = "dvbt"
    ARQUIVOS.pop("ARKT_ISDBT.def", None)
    ARQUIVOS["ARKT_DVBT.def"] = (DEF.replace("ARK-T ISDB-T", "ARK-T DVB-T").replace("MODE_NAME=ISDBT", "MODE_NAME=DVBT")
                                 .replace("MODE_DIS=1,1,1,0,0", "MODE_DIS=1,1,0,0,1")).encode()


class Equipamento:
    def __init__(self):
        self.st = bytearray(1405)
        self.lock = threading.Lock()
        self.eventos: list[bytes] = []
        self.mapa16 = {}
        self.mapa_texto = {}
        self.sessoes5000 = 0
        self.coef_lineares = None
        self.curvas = {}
        self.arquivo_em_escrita = None
        self.inicio = time.time()
        self.reiniciando_ate = 0.0
        self._mapear()
        self._inicial()

    # ------------------------------------------------------------ mapeamento
    def _mapear(self):
        m = Modelo(DefinicaoSistema.ler(DEF))
        for c in m.todos:
            for s in [c] + c.subcampos:
                self._mapear_campo(s)

    def _mapear_campo(self, c):
        if isinstance(c, C.NumeroTexto) and c.commands:
            self.mapa_texto[c.commands[0]] = c.index
            return
        cmds = []
        if getattr(c, "command", None):
            cmds = [(c.command, c.index)]
        lista = getattr(c, "commands", None)
        if lista:
            n = len(lista)
            if isinstance(c, C.EnderecoIP):
                cmds = [(lista[k], c.index + 2 * k) for k in range(n)] if c.is16 else []
            elif c.is16:
                inv = getattr(c, "inverted", True)
                cmds = [(lista[j], c.index + 2 * ((n - 1 - j) if inv else j)) for j in range(n)]
        for cmd, idx in cmds:
            if cmd.lower().startswith("w0") and len(cmd) == 6:
                self.mapa16[cmd.lower()] = idx
        for lst in (getattr(c, "command_on", None), getattr(c, "command_off", None)):
            for full in lst or []:
                if full.lower().startswith("w0") and len(full) >= 10:
                    self.mapa16.setdefault(full[:6].lower(), c.index)

    def _w(self, idx, *vals):
        for k, v in enumerate(vals):
            self.st[idx + k] = v & 0xFF

    def _be(self, idx, v, n):
        for k in range(n):
            self.st[idx + k] = (v >> (8 * (n - 1 - k))) & 0xFF

    def _le16(self, idx, v):
        self.st[idx] = v & 0xFF
        self.st[idx + 1] = (v >> 8) & 0xFF

    def _texto16_8(self, idx, v):
        """Valor lido por MbTextField 16 bits / 8 dígitos."""
        self.st[idx + 1] = (v >> 24) & 0xFF
        self.st[idx] = (v >> 16) & 0xFF
        self.st[idx + 3] = (v >> 8) & 0xFF
        self.st[idx + 2] = v & 0xFF

    def _inicial(self):
        s = self._w
        s(521, 2 if PADRAO == "dvbt" else 4)   # Modo A = DVB-T / ISDB-T
        s(537, 3)            # Modo B = analógico
        s(744, 0)            # modo em uso: A
        s(523, 28)           # canal A
        s(539, 28)
        self._be(532, 400, 2)   # potência A 40,0 dBm
        self._be(548, 380, 2)
        s(559, 1)            # RF ligado
        s(489, 1)
        s(570, 0)
        s(571, 1)            # comutação automática
        s(579, 30)
        s(699, 0)            # amplificador ON
        s(701, 1)
        s(711, 1)
        self._be(747, 557142857, 4)
        self._be(717, 28010, 2)
        self._be(719, 4510, 2)
        self._be(756, 24020, 2)
        self._be(713, 38, 2)
        self._be(715, 41, 2)
        self._le16(173, 104)
        self._le16(175, 98)
        s(553, 60)
        s(554, 70)
        s(560, 30)
        s(561, 60)
        s(565, 1)
        s(566, 0)
        s(567, 1)
        # alarmes: GUI/LCD/Evento habilitados para tudo
        for base in (672, 668, 676):
            for k in range(4):
                s(base - k, 0xFF)
        for k in range(4):
            s(620 - k, 0xFF)     # trap destino 0
        s(765, 0x03, 0xF0)       # 1008 eventos no máximo
        # GPS
        s(857, 1)
        s(858, 11)
        s(859, 9)
        s(841, 20, 19, 0x9A, 0x00, 1)     # 20°19'154'' S
        s(846, 40, 17, 1, 0x2C, 0x01)     # 40°17'300'' O
        # rede
        s(781, 192, 168, 1, 50)
        s(785, 192, 168, 1, 1)
        s(799, 255, 255, 255, 0)
        s(793, 0x00, 0x20, 0x4A, 0x8B, 0x31, 0x07)
        for k, ch in enumerate(b"public"):
            s(985 + k, ch)
            s(1001 + k, ch)
        for k, ch in enumerate(b"private"):
            s(969 + k, ch)
        s(585, 192, 168, 1, 10)
        # entrada ASI 1 com sinal, 19,33 Mbit/s em 188 bytes
        for base, ok in ((351, True), (367, False), (383, False), (399, False)):
            if ok:
                self._texto16_8(base, 27000000)
                self._texto16_8(base + 4, 2416250)
                self._texto16_8(base + 8, 2400000)
                self.st[base + 13] = 0x40 | 0x10 | 0x08
        self._texto16_8(419, 0)
        s(9, 0)
        # ISDB-T (parâmetros atuais / IIP)
        self._le16(1309, 3)          # Mode 3
        self._le16(155, 2)           # GI 1/8
        self._le16(1241, 1)
        self._le16(1253, 0b001)
        self._le16(1347, 1)
        self._texto16_8(255, 10000)
        self._texto16_8(315, 10200)
        for base, (mod, cr, ti, seg) in ((1315, (1, 1, 2, 1)), (1323, (3, 2, 2, 12)), (1331, (7, 7, 7, 15))):
            self._le16(base, mod)
            self._le16(base + 2, cr)
            self._le16(base + 4, ti)
            self._le16(base + 6, seg)
        s(573, 26, 11, 13, 6, 0, 0)     # horário de comutação
        # parâmetros em uso (iguais ao IIP) e locais
        for idx, v in ((1147, 3), (1259, 2), (1261, 1), (1263, 1), (1265, 1), (1267, 2), (1269, 1),
                       (1271, 3), (1273, 2), (1275, 2), (1277, 12), (1279, 7), (1281, 7), (1283, 7), (1285, 15),
                       (107, 3), (109, 2), (111, 1), (113, 649), (121, 6291), (129, 8191)):
            self._le16(idx, v)
        self._texto16_8(247, 10000)
        self._le16(51, 1)              # SFN
        self._le16(83, 2)              # referência GPS
        self._le16(1295, 1)
        # histórico
        agora = datetime.now()
        self._evento(0, agora, bytes(14))
        for txt in ("w22600", "w22601", "w20b01", "w20c90"):
            self._evento(1, agora, bytes([2]) + txt.encode())
        self._evento(2, agora, b"GPS Lock")
        self._evento(3, agora, b"GPS Lock OK")

    # ------------------------------------------------------------ eventos
    def _evento(self, codigo, quando, corpo: bytes):
        b = bytearray(32)
        b[0], b[1], b[2] = quando.second, quando.minute, quando.hour
        b[3], b[4], b[5] = quando.day, quando.month, quando.year - 2000
        b[6] = codigo
        corpo = corpo[:25]
        b[7:7 + len(corpo)] = corpo
        self.eventos.append(bytes(b))
        n = len(self.eventos)
        self._be(790, n, 2)

    def pagina_eventos(self, pagina):
        out = []
        for k in range(pagina * 8, pagina * 8 + 8):
            out.append(self.eventos[k].hex() if k < len(self.eventos) else "00" * 32)
        return b"g4" + b"%02x" % pagina + "".join(out).encode()

    # ------------------------------------------------------------ vida
    def atualizar(self):
        t = time.time() - self.inicio
        rf = (self.st[559] & 1) == 1
        pot = (self.st[532] << 8) + self.st[533]
        fwd = pot + int(round(2 * math.sin(t / 7))) if rf else 0
        self._be(727, max(fwd, 0), 2)
        self._be(729, 150 + random.randint(-3, 3) if rf else 0, 2)
        self._be(713, 38 + int(2 * math.sin(t / 40)), 2)
        self._be(719, 4510 + random.randint(-40, 40) if rf else 300, 2)
        self.st[489] = 1 if rf else 0
        agora = datetime.now(timezone.utc)
        self.st[851], self.st[852] = agora.hour, agora.minute
        self.st[854], self.st[855], self.st[856] = agora.day, agora.month, agora.year - 2000
        self._texto16_8(355, 2416250 + random.randint(-200, 200))
        if self.reiniciando_ate and time.time() < self.reiniciando_ate:
            self.st[699] = 2
        elif self.reiniciando_ate:
            self.reiniciando_ate = 0
            self.st[699] = 0 if rf else 7

    # ------------------------------------------------------------ comandos
    def tratar(self, linha: bytes) -> bytes:
        global USUARIO, SENHA
        txt = linha.decode("latin-1").strip("\r\n")
        with self.lock:
            if txt == "t":
                self.atualizar()
                return bytes(self.st)
            if txt == "yh":
                nomes = list(ARQUIVOS)
                corpo = "".join("%-12s%s\t" % ("%08x" % len(ARQUIVOS[n]), n) for n in nomes)
                return ("yh" + " " * 8 + "%04x" % len(nomes) + " " * 4 + corpo + "\r\n").encode("latin-1")
            if txt == "\xa7":
                return "\xa701050203,ARK-T SIM,u-blox LEA-6T\r\n".encode("latin-1")
            if txt.startswith("xp0"):
                partes = linha[3:].split(b"\0")
                dec = lambda b: "".join(chr(c - 2) for c in b)  # noqa: E731
                ok = len(partes) >= 2 and dec(partes[0]) == USUARIO and dec(partes[1]) == SENHA
                return b"xp0" + (b"y" if ok else b"n")
            if txt.startswith("xp1"):
                partes = linha[3:].split(b"\0")
                dec = lambda b: "".join(chr(c - 2) for c in b)  # noqa: E731
                ok = len(partes) >= 4 and dec(partes[0]) == USUARIO and dec(partes[1]) == SENHA
                if ok:
                    USUARIO, SENHA = dec(partes[2]), dec(partes[3])
                return b"xp1" + (b"y" if ok else b"n")
            if txt.startswith("g4"):
                return self.pagina_eventos(int(txt[2:4], 16))
            if txt == "xq":
                self.eventos.clear()
                self._be(790, 0, 2)
                return linha
            if txt == "$":
                self.reiniciando_ate = time.time() + 8
                self._evento(0, datetime.now(), bytes(14))
                return linha
            if txt in ("s", "l"):
                return linha
            for pref, idx in self.mapa_texto.items():
                if txt.startswith(pref):
                    val = txt[len(pref):].encode("latin-1")[:16]
                    for k in range(16):
                        self.st[idx + k] = val[k] if k < len(val) else 0
                    self._registrar(txt)
                    return linha
            low = txt.lower()
            try:
                if low.startswith("w2") and len(low) >= 6:
                    reg = int(low[2:4], 16)
                    self.st[521 + reg] = int(low[4:6], 16)
                    if reg == 0x26:
                        self.st[699] = 0 if self.st[559] & 1 else 7
                    self._registrar(txt)
                elif low.startswith("w0") and len(low) >= 10:
                    if not self.mapa16:          # telas importadas depois de o simulador subir
                        self._mapear()
                    idx = self.mapa16.get(low[:6])
                    if idx is not None:
                        self._le16(idx, int(low[6:10], 16))
                    self._registrar(txt)
            except ValueError:
                pass
            return linha

    def _registrar(self, txt):
        self._evento(1, datetime.now(), bytes([2]) + txt.encode("latin-1"))


class _TCP(socketserver.BaseRequestHandler):
    def handle(self):
        eq: Equipamento = self.server.eq
        buf = b""
        self.request.settimeout(30)
        while True:
            try:
                d = self.request.recv(256)
            except OSError:
                return
            if not d:
                return
            buf += d
            while True:
                k = min([i for i in (buf.find(b"\n"), buf.find(b"\r")) if i >= 0], default=-1)
                if k < 0:
                    break
                linha = buf[:k]
                # consome o terminador (\n\r ou \r\n)
                j = k + 1
                if j < len(buf) and buf[j:j + 1] in (b"\r", b"\n") and buf[j:j + 1] != buf[k:k + 1]:
                    j += 1
                term = buf[k:j]
                buf = buf[j:]
                if not linha:
                    continue
                resp = eq.tratar(linha + term)
                try:
                    self.request.sendall(resp)
                except OSError:
                    return


class _TCP5000(socketserver.BaseRequestHandler):
    """Porta 5000: pré-correção e gravação de arquivos (protocolo binário)."""

    def handle(self):
        eq: Equipamento = self.server.eq
        self.request.settimeout(60)
        buf = b""
        with eq.lock:
            eq.sessoes5000 += 1
            eq.st[731] |= 1
        try:
            while True:
                try:
                    d = self.request.recv(4096)
                except OSError:
                    return
                if not d:
                    return
                buf += d
                while buf:
                    r = self._um(eq, buf)
                    if r is None:
                        break
                    usados, resp = r
                    buf = buf[usados:]
                    if resp:
                        self.request.sendall(resp)
        finally:
            with eq.lock:
                eq.sessoes5000 -= 1
                if eq.sessoes5000 <= 0:
                    eq.st[731] &= 0xFE

    @staticmethod
    def _linha(buf):
        k = buf.find(b"\n")
        if k < 0:
            return None
        j = k + 1
        if buf[j:j + 1] == b"\r":
            j += 1
        return j

    def _um(self, eq, buf):
        c2 = buf[:2]
        if c2 in (b"p0", b"p1", b"p2"):
            if len(buf) < 1026:
                return None
            eq.curvas[c2.decode()] = bytes(buf[2:1026])
            return 1026, c2 + b"y"
        if c2 == b"p3":
            if len(buf) < 772:
                return None
            eq.coef_lineares = buf[4:772]
            return 772, b"p3y"
        if c2 == b"g0":
            j = self._linha(buf)
            if j is None:
                return None
            atual = [n for n in ARQUIVOS if n.endswith(".dlin")]
            coef = eq.coef_lineares or (ARQUIVOS[atual[-1]][2:770] if atual else bytes(768))
            hx = coef.hex()
            parte = int(buf[3:4])
            texto = (hx[:1024] if parte == 0 else hx[1024:].ljust(1024, "0"))
            return j, b"g0c%d" % parte + texto.encode() + b"\r\n"
        if c2 == b"nl" or c2 == b"k\n" or c2 == b"oo" or c2 == b"op" or c2 == b"yc":
            j = self._linha(buf)
            if j is None:
                return None
            cmd = buf[:j].strip()
            if cmd.startswith(b"oo"):
                with eq.lock:
                    modo = eq.st[744] & 1
                    eq.st[523 if modo == 0 else 539] = int(cmd[2:4], 16)
                return j, b"y"
            if cmd.startswith(b"op"):
                with eq.lock:
                    modo = eq.st[744] & 1
                    v = int(cmd[2:5], 16)
                    i = 532 if modo == 0 else 548
                    eq.st[i], eq.st[i + 1] = v >> 8, v & 0xFF
                return j, b"y"
            if cmd == b"yc" and eq.arquivo_em_escrita:
                nome, dados = eq.arquivo_em_escrita
                ext = nome[nome.rfind("."):]
                if ext in (".dpre", ".apre", ".dlin", ".alin", ".sav"):
                    for velho in [n for n in ARQUIVOS if n.endswith(ext) and n != nome]:
                        del ARQUIVOS[velho]
                ARQUIVOS[nome] = bytes(dados)
                eq.arquivo_em_escrita = None
                eq._evento(3, datetime.now(), ("Arquivo %s gravado" % nome[:14]).encode())
                return j, b"ycy"
            if cmd == b"k":
                eq.coef_lineares = None
                return j, b"k  y"
            return j, b"nly"
        if buf[:1] == b"l":
            if len(buf) < 4:
                return None
            return 4, b"l y"
        if buf[:1] == b"b":
            return 1, b"by"
        if c2 == b"yo":
            if len(buf) < 12:
                return None
            n_nome = int(buf[10:12], 16)
            if len(buf) < 12 + n_nome:
                return None
            nome = buf[12:12 + n_nome].decode("latin-1")
            eq.arquivo_em_escrita = (nome, bytearray())
            eq.particao = "ys0030000"
            return 12 + n_nome, b"yoy"
        if c2 == b"ys":
            estado = "ys0030000" if eq.arquivo_em_escrita else "ys0000000"
            return 2, estado.encode()
        if c2 == b"yw":
            if len(buf) < 5:
                return None
            n = int(buf[2:5], 16)
            if len(buf) < 5 + n:
                return None
            if eq.arquivo_em_escrita:
                eq.arquivo_em_escrita[1].extend(buf[5:5 + n])
            return 5 + n, b"ywy"
        # desconhecido: descarta um byte
        return 1, b""


class _HTTP(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        nome = self.path.lstrip("/")
        dados = ARQUIVOS.get(nome)
        if dados is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def log_message(self, *a):
        pass


class _Servidor(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def rodar(porta=10001, porta_http=8080, host="127.0.0.1", em_thread=False, porta_prec=None):
    eq = Equipamento()
    tcp = _Servidor((host, porta), _TCP)
    tcp.eq = eq
    porta_prec = porta_prec or (5000 if porta == 10001 else porta + 1)
    try:
        p5 = _Servidor((host, porta_prec), _TCP5000)
        p5.eq = eq
        threading.Thread(target=p5.serve_forever, daemon=True).start()
        eq.porta_prec = porta_prec
    except OSError:
        eq.porta_prec = None
    web = _Servidor((host, porta_http), _HTTP)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    if em_thread:
        threading.Thread(target=tcp.serve_forever, daemon=True).start()
        return eq, tcp, web
    print("Simulador ARK-T em %s — comandos na porta %d, pré-correção na %s, arquivos em http://%s:%d/"
          % (host, porta, eq.porta_prec, host, porta_http))
    print("Login da pré-correção: %s / %s" % (USUARIO, SENHA))
    try:
        tcp.serve_forever()
    except KeyboardInterrupt:
        pass
