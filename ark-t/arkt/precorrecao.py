"""Pré-correção do ARK-T: curvas AM/AM e AM/PM (não linear) e pré-correção
linear (módulo e atraso de grupo), arquivos .dpre/.apre/.dlin/.alin e a
sessão na porta TCP 5000.

A matemática reproduz o applet original (Interpolator, WriterPrec,
WriterLinear, FFT) para que as curvas enviadas sejam as mesmas.
"""
from __future__ import annotations

import math
import queue
import socket
import struct
import sys
import threading
import time

from . import javaser as J
from .fmt import hexn

# ---------------------------------------------------------------- classes Java
PKG = "precorrection_dvbh.interpolator"
C_PONTO = J.Classe(PKG + ".ControlPoint", -547808747905480883, J.SC_SERIALIZABLE,
                   [("Z", "isSelected", None), ("I", "x", None), ("I", "y", None)])
C_CURVA = J.Classe(PKG + ".precorrection.knb.CurvePrec", -7889746430518935285, J.SC_SERIALIZABLE,
                   [("I", "intType", None), ("L", "controlPoints", "Ljava/util/Vector;")])
C_CANAL = J.Classe(PKG + ".precorrection.knb.ChannelPrec", -7718322641818437196, J.SC_SERIALIZABLE,
                   [("L", "curvePrec", "Ljava/util/Vector;")])
C_INTERP = J.Classe(PKG + ".precorrection.knb.InterpPrec", 6897398848520854416, J.SC_SERIALIZABLE,
                    [("L", "channelPrec", "Ljava/util/Vector;")])
_KNB = [("L", "fileName", "Ljava/lang/String;"),
        ("L", "interpPrecAm", "L" + (PKG + ".precorrection.knb.InterpPrec").replace(".", "/") + ";"),
        ("L", "interpPrecPm", "L" + (PKG + ".precorrection.knb.InterpPrec").replace(".", "/") + ";")]
_LKNB = [("L", "curveModulo", "L" + (PKG + ".precorrection.knb.CurvePrec").replace(".", "/") + ";"),
         ("L", "curvePhase", "L" + (PKG + ".precorrection.knb.CurvePrec").replace(".", "/") + ";"),
         ("L", "fileName", "Ljava/lang/String;")]
C_DKNB = J.Classe("serializable.DknbFile", 6496543038168809925, J.SC_SERIALIZABLE, _KNB)
C_AKNB = J.Classe("serializable.AknbFile", -690537301291349640, J.SC_SERIALIZABLE, _KNB)
C_LDKNB = J.Classe("serializable.LdknbFile", -1360342051225797166, J.SC_SERIALIZABLE, _LKNB)
C_LAKNB = J.Classe("serializable.LaknbFile", -9180988044230356776, J.SC_SERIALIZABLE, _LKNB)

LINEAR, POLINOMIAL = 1, 0


# ---------------------------------------------------------------- float do Java
def f32(x):
    return struct.unpack("f", struct.pack("f", x))[0]


def _trunc(x):
    """(int) do Java: trunca em direção ao zero, com saturação."""
    if x != x:
        return 0
    if x >= 2147483647:
        return 2147483647
    if x <= -2147483648:
        return -2147483648
    return int(x)


# ---------------------------------------------------------------- curvas
class Eixo:
    """Configuração de um editor (InterpolatorB do original)."""

    def __init__(self, ident, resolucao, vmin, vmax):
        self.id = ident
        self.resolucao = resolucao
        self.vmin = vmin
        self.vmax = vmax

    @property
    def faixa(self):
        return self.vmax - self.vmin

    def padrao(self):
        """getDefaultControlPoints(): reta no meio da faixa."""
        return [[0, self.faixa // 2], [self.resolucao - 1, self.faixa // 2]]


AM = Eixo("AM", 512, 3072, 8191)
PM = Eixo("PM", 1024, -32768, 32767)
MODULO = Eixo("Module", 2048, -7168, 1023)
FASE = Eixo("Phase", 2048, -90000, 89999)


def pontos_da_curva(eixo: Eixo, controles, modo=LINEAR):
    """Interpolator.paint(): pontos de controle (x, y com y=0 no topo) ->
    vetor de `resolucao` amostras, com a mesma aritmética em float32."""
    res = eixo.resolucao
    pts = [0] * res
    n7 = len(controles)
    if n7 == 0:
        return pts
    xs = [f32(c[0]) for c in controles]
    ys = [f32(c[1]) for c in controles]
    if modo == POLINOMIAL:
        a = list(ys)
        for n5 in range(1, n7):
            for i in range(0, n7 - n5):
                a[i] = f32(f32(a[i + 1] - a[i]) / f32(xs[i + n5] - xs[i]))
        n8 = res - 1
        f4 = f32(f32(res - 1.0) / n8) if n8 else f32(0)
        teto = eixo.faixa
        for n9 in range(n8 + 1):
            f5 = f32(n9 * f4)
            f6 = a[0]
            for n4 in range(1, n7):
                f6 = f32(f32(f6 * f32(f5 - xs[n4])) + a[n4])
            if f6 > teto:
                f6 = f32(teto)
            elif f6 < 0.0:
                f6 = f32(0.0)
            pts[n9] = _trunc(f6)
        return pts
    n10 = 0
    f3 = ys[0]
    for n4 in range(1, n7):
        n3 = n10
        incl = f32(f32(ys[n4 - 1] - ys[n4]) / f32(xs[n4] - xs[n4 - 1])) if xs[n4] != xs[n4 - 1] else f32(0)
        while f32(n3) < xs[n4]:
            f8 = f32(f3 - incl)
            if n10 < res:
                pts[n10] = _trunc(f8)
            f3 = f8
            n10 += 1
            if n10 == res - 1:
                f8 = f32(f3 - incl)
                pts[n10] = _trunc(f8)
            n3 += 1
    return pts


def am_para_equipamento(pts):
    return [(8191 - p) & 0xFFFF for p in pts]


def pm_para_equipamento(pts):
    return [(32767 - p) & 0xFFFF for p in pts]


def equipamento_para_am(vals):
    """Valor gravado -> y do editor (para desenhar a curva gravada)."""
    return [8191 - v for v in vals]


def equipamento_para_pm(vals):
    return [32767 - (v - 65536 if v >= 32768 else v) for v in vals]


class Curva:
    """CurvePrec: tipo de interpolação + pontos de controle."""

    def __init__(self, eixo: Eixo, controles=None, modo=LINEAR):
        self.eixo = eixo
        self.controles = [list(c) for c in (controles or eixo.padrao())]
        self.modo = modo

    def pontos(self):
        return pontos_da_curva(self.eixo, self.controles, self.modo)

    def copia(self):
        return Curva(self.eixo, [list(c) for c in self.controles], self.modo)

    def plana(self):
        return len(self.controles) == 2 and self.controles == self.eixo.padrao()


# ---------------------------------------------------------------- .dpre / .apre
class ArquivoPre:
    """DpreFile/ApreFile + DknbFile/AknbFile: curvas AM/PM por canal e por
    degrau de potência, e os pontos de controle do editor."""

    def __init__(self, n_potencias, n_canais, n_am=512, n_pm=1024, nome=None, digital=True):
        self.n_pot = n_potencias
        self.n_can = n_canais
        self.n_am = n_am
        self.n_pm = n_pm
        self.nome = nome
        self.digital = digital
        bloco = n_am + n_pm
        self.valores = [n_potencias, n_canais, n_am, n_pm]
        for _ in range(n_canais * n_potencias):
            self.valores += [5632] * n_am + [0] * n_pm
        assert len(self.valores) == 4 + n_canais * n_potencias * bloco
        self.am = [[Curva(AM) for _ in range(n_potencias)] for _ in range(n_canais)]
        self.pm = [[Curva(PM) for _ in range(n_potencias)] for _ in range(n_canais)]
        self.knb_original = None

    @property
    def extensao(self):
        return ".dpre" if self.digital else ".apre"

    # posição de uma curva dentro do arquivo
    def _base(self, canal, pot, am):
        b = self.n_am + self.n_pm
        return 4 + pot * b + canal * self.n_pot * b + (0 if am else self.n_am)

    def curva_gravada(self, canal, pot, am=True):
        n = self.n_am if am else self.n_pm
        i = self._base(canal, pot, am)
        return self.valores[i:i + n]

    def definir_curva(self, canal, pot, am, vals):
        i = self._base(canal, pot, am)
        self.valores[i:i + len(vals)] = list(vals)

    @classmethod
    def ler(cls, dados: bytes, nome=None, digital=True):
        cab = [((dados[k * 2]) << 8) + dados[k * 2 + 1] for k in range(4)]
        n_pot, n_can, n_am, n_pm = cab
        tam = (n_am + n_pm) * n_can * n_pot * 2 + 8
        a = cls(n_pot, n_can, n_am, n_pm, nome, digital)
        a.valores = [(dados[k * 2] << 8) + dados[k * 2 + 1] for k in range(tam // 2)]
        knb = dados[tam:]
        if knb:
            try:
                obj = J.ler(knb)
                a._carregar_knb(obj)
                a.knb_original = knb
            except Exception:  # noqa: BLE001 - pontos de controle são opcionais
                pass
        return a

    def _carregar_knb(self, obj):
        for chave, destino, eixo in (("interpPrecAm", self.am, AM), ("interpPrecPm", self.pm, PM)):
            interp = obj.get(chave)
            if interp is None:
                continue
            for c, canal in enumerate(interp["channelPrec"] or []):
                if c >= self.n_can or canal is None:
                    continue
                for p, cur in enumerate(canal["curvePrec"] or []):
                    if p >= self.n_pot or cur is None:
                        continue
                    pts = [[cp["x"], cp["y"]] for cp in (cur["controlPoints"] or []) if cp is not None]
                    destino[c][p] = Curva(eixo, pts or None, cur["intType"])

    def bytes_curvas(self):
        return b"".join(struct.pack(">H", v & 0xFFFF) for v in self.valores)

    def objeto_knb(self, nome_arquivo=None):
        def interp(matriz):
            canais = J.Vetor()
            for linha in matriz:
                curvas = J.Vetor()
                for cur in linha:
                    pts = J.Vetor(J.NovoObjeto(C_PONTO, isSelected=False, x=int(x), y=int(y)) for x, y in cur.controles)
                    curvas.append(J.NovoObjeto(C_CURVA, intType=int(cur.modo), controlPoints=pts))
                canais.append(J.NovoObjeto(C_CANAL, curvePrec=curvas))
            return J.NovoObjeto(C_INTERP, channelPrec=canais)
        return J.NovoObjeto(C_DKNB if self.digital else C_AKNB, fileName=nome_arquivo or self.nome,
                            interpPrecAm=interp(self.am), interpPrecPm=interp(self.pm))

    def bytes_completo(self, nome_arquivo=None):
        """Arquivo como o original grava: curvas + objeto serializado."""
        return self.bytes_curvas() + J.escrever(self.objeto_knb(nome_arquivo))

    def ajustar_canais(self, n_canais):
        """WriterPrec.writeFile(): se a canalização mudou, canais novos
        recebem blocos 0x1000 (AM) e 0 (PM); canais a mais são cortados."""
        dif = n_canais - self.n_can
        if dif == 0:
            return
        bloco = (self.n_am + self.n_pm) * self.n_pot
        if dif > 0:
            for _ in range(dif * self.n_pot):
                self.valores += [0x1000] * self.n_am + [0] * self.n_pm
            for _ in range(dif):
                self.am.append([Curva(AM) for _ in range(self.n_pot)])
                self.pm.append([Curva(PM) for _ in range(self.n_pot)])
        else:
            self.valores = self.valores[:4 + n_canais * bloco]
            self.am = self.am[:n_canais]
            self.pm = self.pm[:n_canais]
        self.n_can = n_canais
        self.valores[1] = (self.valores[1] & 0xFF00) | (n_canais & 0xFF)


# ---------------------------------------------------------------- linear
TAM_COEF = 770
JANELA = [
    0.148148148148, 0.149972028352, 0.15543585883, 0.164516242619, 0.177174296124, 0.193355815615,
    0.212991509342, 0.23599729425, 0.262274656035, 0.291711071002, 0.3241804879, 0.359543867703,
    0.397649778989, 0.438335046396, 0.481425449363, 0.526736468168, 0.574074074074, 0.623235560184,
    0.674010409467, 0.726181196223, 0.779524517135, 0.833811947912, 0.888811021442, 0.944286223248,
    1.0, 1.055713776752, 1.111188978558, 1.166188052088, 1.220475482865, 1.273818803777,
    1.325989590533, 1.376764439816, 1.425925925926, 1.473263531832, 1.518574550637, 1.561664953604,
    1.602350221011, 1.640456132297, 1.6758195121, 1.708288928998, 1.737725343965, 1.76400270575,
    1.787008490658, 1.806644184385, 1.822825703876, 1.835483757381, 1.84456414117, 1.850027971648,
    1.851851851852, 1.850027971648, 1.84456414117, 1.835483757381, 1.822825703876, 1.806644184385,
    1.787008490658, 1.76400270575, 1.737725343965, 1.708288928998, 1.6758195121, 1.640456132297,
    1.602350221011, 1.561664953604, 1.518574550637, 1.473263531832, 1.425925925926, 1.376764439816,
    1.325989590533, 1.273818803777, 1.220475482865, 1.166188052088, 1.111188978558, 1.055713776752,
    1.0, 0.944286223248, 0.888811021442, 0.833811947912, 0.779524517135, 0.726181196223,
    0.674010409467, 0.623235560184, 0.574074074074, 0.526736468168, 0.481425449363, 0.438335046396,
    0.397649778989, 0.359543867703, 0.3241804879, 0.291711071002, 0.262274656035, 0.23599729425,
    0.212991509342, 0.193355815615, 0.177174296124, 0.164516242619, 0.15543585883, 0.149972028352,
]


def _fft(a):
    """FFT.fft() do original (radix-2 recursiva)."""
    n = len(a)
    if n == 1:
        return [a[0]]
    par = _fft(a[0::2])
    impar = _fft(a[1::2])
    out = [0j] * n
    for i in range(n // 2):
        d = (-2 * i) * math.pi / n
        w = complex(math.cos(d), math.sin(d))
        t = complex(w.real * impar[i].real - w.imag * impar[i].imag, w.real * impar[i].imag + w.imag * impar[i].real)
        out[i] = complex(par[i].real + t.real, par[i].imag + t.imag)
        out[i + n // 2] = complex(par[i].real - t.real, par[i].imag - t.imag)
    return out


def _ifft(a):
    n = len(a)
    b = _fft([x.conjugate() for x in a])
    return [complex(x.real * (1.0 / n), -x.imag * (1.0 / n)) for x in b]


def _rodar(lst, n):
    """UtilityPrec.rotateArray: n>0 leva os n últimos para o começo."""
    n = n % len(lst) if lst else 0
    return lst[-n:] + lst[:-n] if n else list(lst)


def _integracao(d, h):
    """WriterLinear.integrate(): soma de Simpson acumulada, na mesma ordem
    de operações do original (resultado idêntico), em O(n)."""
    n = len(d)
    out = [0.0] * n
    meio = 0.0
    for i in range(1, n):
        j = i - 1
        if j == 0:
            total = 4.0 * d[0] + d[1]
        else:
            total = meio + (d[j - 1] + 4.0 * d[j])
        total *= h / 6.0
        out[i] = total
        meio = (4.0 * d[0] + d[1]) if j == 0 else meio + (d[j - 1] + 4.0 * d[j] + d[j + 1])
    return out


def coeficientes_lineares(pontos_modulo, pontos_fase):
    """WriterLinear.calculateCoeffBytes(): 96 coeficientes complexos (768 bytes)."""
    n = len(pontos_modulo)
    mod = [pontos_modulo[n - 1 - i] for i in range(n)]
    fas = [pontos_fase[n - 1 - i] for i in range(n)]
    d = [(89999.0 - fas[k]) / 100000.0 for k in range(n)]
    m = [math.pow(10.0, ((1024.0 - mod[k]) / 1000.0) / 20.0) for k in range(n)]
    d = _integracao(d, -0.030679615757712823)
    d = _rodar(d, -1024)
    m = _rodar(m, -1024)
    c = [complex(m[k] * math.cos(d[k]), m[k] * math.sin(d[k])) for k in range(n)]
    c = _ifft(c)
    c = _rodar(c, 47)[:96]
    c[95] = 0j
    c = [complex(x.real * JANELA[i], x.imag * JANELA[i]) for i, x in enumerate(c)]
    soma = 0j
    for x in c:
        soma = complex(soma.real + x.real, soma.imag + x.imag)
    escala = math.hypot(soma.real, soma.imag) / 65536.0
    saida = bytearray()
    dd = escala * escala
    rre, rim = escala / dd, -0.0 / dd          # Complex.reciprocal()
    for x in c:
        re = x.real * rre - x.imag * rim       # Complex.times()
        im = x.real * rim + x.imag * rre
        r, i_ = _round(re), _round(im)
        saida += bytes([0, (r & 0xFF0000) >> 16, (r & 0xFF00) >> 8, r & 0xFF,
                        0, (i_ & 0xFF0000) >> 16, (i_ & 0xFF00) >> 8, i_ & 0xFF])
    return bytes(saida)


def _round(x):
    """Math.round do Java: floor(x + 0.5)."""
    return int(math.floor(x + 0.5))


def arquivo_linear(coef: bytes):
    """composePrecorrectionFile(): 0x00 0x60 + 768 bytes."""
    return bytes([0, 96]) + coef


def resposta_dos_coeficientes(hex_coef: str):
    """WriterLinear.readCoeff(): coeficientes lidos do equipamento ->
    curvas medidas (módulo, fase) nas unidades do editor."""
    cs = []
    for k in range(0, 1536, 16):
        a = int(hex_coef[k:k + 8], 16)
        b = int(hex_coef[k + 8:k + 16], 16)
        a = ((a << 14) & 0xFFFFFFFF)
        b = ((b << 14) & 0xFFFFFFFF)
        a = (a - (1 << 32) if a >= 1 << 31 else a) >> 14
        b = (b - (1 << 32) if b >= 1 << 31 else b) >> 14
        cs.append(complex(a, b))
    n = 2048
    v = cs + [0j] * (n - len(cs))
    pos, maior = -(2 ** 31), 5e-324
    for i, x in enumerate(v):
        if x.real > maior:
            maior, pos = x.real, i
    f = _fft(v)
    modulo = [math.sqrt(x.real ** 2 + x.imag ** 2) for x in f]
    d = [modulo[i] / n * (1 if i == 0 else math.sqrt(2.0)) for i in range(n)]
    d[0] = d[1]
    db = [200.0 * (math.log(x) / math.log(10.0)) if x > 0 else -1e9 for x in d]
    mx = 5e-324
    for x in db:
        if x > mx:
            mx = x
    db = [x - mx for x in db]
    db = _rodar(db, 1024)
    curva_mod = [_round(1024.0 - 100.0 * x) for x in db]
    v2 = _rodar(v, -pos) if pos > -(2 ** 31) else v
    f2 = _fft(v2)
    fase = [math.atan2(x.imag, x.real) for x in f2]
    fase = _desembrulhar(fase)
    der = _derivar(fase, -62.83185307179586)
    der[0] = der[1]
    der[-1] = der[-2]
    der = _rodar(der, 1024)
    curva_fase = [_round((89999.0 - 3.183098861837907e8 * x) / 1.5707963267948966) for x in der]
    return curva_mod[::-1], curva_fase[::-1]


# readCoeff() devolve o módulo normalizado (pico em y=1024) e a fase numa
# escala deslocada ((89999 - k·der) / (π/2)). Para sobrepor ao editor:
DESLOC_FASE = 89999 - 89999 / (math.pi / 2)


def resposta_no_editor(hex_coef: str, pontos_modulo=None):
    """Curvas lidas do equipamento nas mesmas coordenadas dos editores.
    O ganho absoluto é normalizado pelos coeficientes, então o módulo é
    alinhado pelo ponto de maior ganho da curva editada."""
    m, f = resposta_dos_coeficientes(hex_coef)
    ref = min(pontos_modulo) if pontos_modulo else 4095
    d = ref - min(m)
    return [v + d for v in m], [int(round(v + DESLOC_FASE)) for v in f]


def _desembrulhar(f):
    out = [0.0] * len(f)
    out[0] = f[0]
    n = 0
    for i in range(len(f) - 1):
        a, b = f[i], f[i + 1]
        if abs(a - b) > math.pi:
            n = n - 1 if b > a else n + 1
        out[i + 1] = b + math.pi * 2 * n
    return out


def _derivar(d, h):
    out = [0.0] * len(d)
    for i in range(len(d)):
        if i == 0:
            out[i] = d[i + 1] / 2.0 / h
        elif i == len(d) - 1:
            out[i] = (0.0 - d[i - 1]) / 2.0 / h
        else:
            out[i] = (d[i + 1] - d[i - 1]) / 2.0 / h
    return out


class ArquivoLinear:
    """DlinFile/AlinFile + LdknbFile/LaknbFile."""

    def __init__(self, nome=None, digital=True):
        self.nome = nome
        self.digital = digital
        self.modulo = Curva(MODULO, [[0, 4095], [2047, 4095]])
        self.fase = Curva(FASE, [[0, 89999], [2047, 89999]])
        self.coef = None

    @property
    def extensao(self):
        return ".dlin" if self.digital else ".alin"

    @classmethod
    def ler(cls, dados: bytes, nome=None, digital=True):
        a = cls(nome, digital)
        a.coef = dados[:TAM_COEF]
        try:
            obj = J.ler(dados[TAM_COEF:])
            for chave, eixo, attr in (("curveModulo", MODULO, "modulo"), ("curvePhase", FASE, "fase")):
                cur = obj.get(chave)
                if cur is not None and cur["controlPoints"]:
                    setattr(a, attr, Curva(eixo, [[p["x"], p["y"]] for p in cur["controlPoints"]], cur["intType"]))
        except Exception:  # noqa: BLE001
            pass
        return a

    def calcular(self):
        return coeficientes_lineares(self.modulo.pontos(), self.fase.pontos())

    def objeto_knb(self, nome_arquivo=None):
        def curva(c):
            pts = J.Vetor(J.NovoObjeto(C_PONTO, isSelected=False, x=int(x), y=int(y)) for x, y in c.controles)
            return J.NovoObjeto(C_CURVA, intType=int(c.modo), controlPoints=pts)
        ext = ".ldknb" if self.digital else ".laknb"
        nome = nome_arquivo or (self.nome.rsplit(".", 1)[0] + ext if self.nome else None)
        return J.NovoObjeto(C_LDKNB if self.digital else C_LAKNB, curveModulo=curva(self.modulo),
                            curvePhase=curva(self.fase), fileName=nome)

    def bytes_completo(self, nome_arquivo=None):
        return arquivo_linear(self.calcular()) + J.escrever(self.objeto_knb(nome_arquivo))


# ---------------------------------------------------------------- unidades
def y_para_db(y):
    """Módulo: y do editor -> dB relativos ao meio da faixa (0,001 dB/unidade)."""
    return (4095 - y) / 1000.0


def db_para_y(db):
    return int(round(4095 - db * 1000))


def y_para_ns(y):
    """Atraso de grupo: y do editor -> ns."""
    return (89999 - y) / 100.0


def ns_para_y(ns):
    return int(round(89999 - ns * 100))


def x_para_mhz(x, n=2048):
    """Eixo horizontal da linear: +4,57 MHz à esquerda, −4,57 à direita."""
    return 4.57 - 9.14 * x / (n - 1)


# ---------------------------------------------------------------- sessão porta 5000
class ErroPrecorrecao(Exception):
    pass


def cifrar(texto):
    """DlgLogin.encrypt(): cada caractere + 2."""
    return "".join(chr(ord(c) + 2) for c in texto)


def cmd_login(usuario, senha):
    if len(usuario) >= 16 or len(senha) >= 16:
        raise ErroPrecorrecao("Usuário e senha têm no máximo 15 caracteres")
    return "xp0" + cifrar(usuario) + "\0" + cifrar(senha) + "\0\n\r"


def cmd_trocar_senha(usuario, senha, novo_usuario, nova_senha):
    for s in (novo_usuario, nova_senha):
        if not 3 < len(s) < 16:
            raise ErroPrecorrecao("Novo usuário e nova senha: de 4 a 15 caracteres")
    return ("xp1" + cifrar(usuario) + "\0" + cifrar(senha) + "\0" + cifrar(novo_usuario) + "\0"
            + cifrar(nova_senha) + "\0\n\r")


def porta5000_ocupada(st):
    return (st[731] & 1) == 1


class Sessao5000:
    """Conexão persistente na porta 5000 (MbThreadPoolExecutor5000)."""

    def __init__(self, host, porta=5000, timeout=10.0):
        self.host = host
        self.porta = porta
        self.timeout = timeout
        self.sock = None
        self.ultimo_uso = 0.0

    @property
    def aberta(self):
        return self.sock is not None

    def abrir(self):
        if self.sock is not None:
            return
        s = socket.create_connection((self.host, self.porta), timeout=5.0)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                     struct.pack("HH" if sys.platform == "win32" else "ii", 1, 0))
        s.settimeout(self.timeout)
        self.sock = s
        self.trocar(b"nlinearprog\n\r", 3)

    def fechar(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    def _descartar(self):
        self.sock.setblocking(False)
        try:
            while self.sock.recv(4096):
                pass
        except (BlockingIOError, OSError):
            pass
        finally:
            self.sock.setblocking(True)
            self.sock.settimeout(self.timeout)

    def trocar(self, dados: bytes, n):
        """sendAndReceive(byte[], byte[n]): envia e lê exatamente n bytes."""
        if self.sock is None:
            raise ErroPrecorrecao("Sessão de pré-correção fechada")
        self._descartar()
        self.sock.sendall(dados)
        self.ultimo_uso = time.time()
        buf = bytearray()
        while len(buf) < n:
            try:
                d = self.sock.recv(n - len(buf))
            except socket.timeout:
                raise ErroPrecorrecao("O equipamento não respondeu na porta 5000")
            if not d:
                self.fechar()
                raise ErroPrecorrecao("O equipamento fechou a porta 5000")
            buf.extend(d)
        return bytes(buf)

    def linha(self, texto: str):
        self._descartar()
        self.sock.sendall(texto.encode("latin-1"))
        self.ultimo_uso = time.time()
        buf = bytearray()
        while True:
            try:
                d = self.sock.recv(1)
            except socket.timeout:
                raise ErroPrecorrecao("O equipamento não respondeu na porta 5000")
            if not d:
                self.fechar()
                raise ErroPrecorrecao("O equipamento fechou a porta 5000")
            if d == b"\n":
                return buf.decode("latin-1")
            buf.extend(d)

    def manter(self):
        """KeepAlive: 'b' a cada 8 s sem uso."""
        if self.sock is not None and time.time() - self.ultimo_uso > 8:
            self.trocar(b"b", 2)

    # -- curvas
    def enviar_am(self, pts_editor):
        vals = am_para_equipamento(pts_editor)
        dados = b"p0" + b"".join(struct.pack(">H", v) for v in vals[:512])
        self.trocar(dados, 3)
        return vals

    def enviar_pm(self, pts_editor):
        vals = pm_para_equipamento(pts_editor)
        for parte in (0, 1):
            pedaco = vals[parte * 512:(parte + 1) * 512]
            dados = b"p" + str(parte + 1).encode() + b"".join(struct.pack(">H", v) for v in pedaco)
            self.trocar(dados, 3)
        return vals

    def enviar_linear(self, coef: bytes):
        self.trocar(b"p360" + coef, 3)

    def ler_coeficientes(self):
        texto = ""
        for i in range(2):
            r = self.linha("g0c%d\n\r" % i)
            texto += r[4:1028]
        return texto

    def carregar_curva_gravada(self, canal_num, potencia):
        """'l' + canal + degrau: o equipamento recarrega a curva do arquivo."""
        self.trocar(("l" + hexn(canal_num, 2) + hexn(potencia, 1)).encode(), 3)

    def carregar_linear_gravada(self):
        self.trocar(b"k\n\r", 4)

    def canal(self, cmd_item):
        self.trocar(("oo" + cmd_item + "\n\r").encode(), 1)

    def potencia(self, passo):
        self.trocar(("op" + hexn(passo, 3) + "\n\r").encode(), 1)

    # -- arquivos
    def _status_particao(self, esperado):
        r = self.trocar(b"ys", 9).decode("latin-1")
        while esperado not in r:
            if len(r) > 6 and r[6] != "0":
                raise ErroPrecorrecao("O equipamento recusou a operação de arquivo (%s)" % r.strip())
            time.sleep(0.5)
            r = self.trocar(b"ys", 9).decode("latin-1")

    def enviar_arquivo(self, nome, dados: bytes, progresso=None):
        """RunLoadFiles: grava um arquivo no sistema de arquivos do ARK-T."""
        if not 1 <= len(nome) <= 255:
            raise ErroPrecorrecao("Nome de arquivo inválido")
        r = self.trocar(("yo" + hexn(len(dados), 8) + hexn(len(nome), 2) + nome).encode("latin-1"), 3)
        self._status_particao("ys00300")
        if len(r) > 2 and r[2] != 0x79:
            raise ErroPrecorrecao("O equipamento não abriu o arquivo para escrita")
        enviado = 0
        total = len(dados)
        while enviado < total:
            n = min(512, total - enviado)
            r = self.trocar(("yw" + hexn(n, 3)).encode() + dados[enviado:enviado + n], 3)
            if len(r) > 2 and r[2] != 0x79:
                raise ErroPrecorrecao("Falha na transferência do arquivo")
            enviado += n
            if progresso:
                progresso(enviado, total)
        self.trocar(b"yc\n\r", 3)
        self._status_particao("ys00000")


class Trabalhador5000:
    """Fila de tarefas sobre uma Sessao5000 (MbThreadPoolExecutor5000):
    uma tarefa por vez, KeepAlive quando ociosa e envio de curvas
    "coalescido" — durante um arraste só a última versão vai para o
    equipamento. Callbacks rodam nesta thread."""

    def __init__(self, host, porta=5000):
        self.sessao = Sessao5000(host, porta)
        self.fila: queue.Queue = queue.Queue()
        self._ultimas = {}
        self._trava = threading.Lock()
        self._parar = threading.Event()
        self.ao_queda = None            # fn(str): conexão perdida
        self._t = threading.Thread(target=self._loop, name="arkt-5000", daemon=True)
        self._t.start()

    def executar(self, fn, ao_fim=None, ao_erro=None):
        self.fila.put((fn, ao_fim, ao_erro))

    def coalescer(self, chave, fn, ao_fim=None, ao_erro=None):
        with self._trava:
            novo = chave not in self._ultimas
            self._ultimas[chave] = (fn, ao_fim, ao_erro)
        if novo:
            self.fila.put(chave)

    def fechar(self, ao_fim=None):
        def f(s):
            s.fechar()
        self.fila.put((f, ao_fim, None))
        self.fila.put(None)

    def _loop(self):
        while not self._parar.is_set():
            try:
                item = self.fila.get(timeout=1.0)
            except queue.Empty:
                try:
                    self.sessao.manter()
                except Exception as e:  # noqa: BLE001
                    self._caiu(str(e))
                continue
            if item is None:
                break
            if isinstance(item, str):
                with self._trava:
                    item = self._ultimas.pop(item, None)
                if item is None:
                    continue
            fn, ao_fim, ao_erro = item
            try:
                if not self.sessao.aberta:
                    self.sessao.abrir()
                r = fn(self.sessao)
            except (OSError, ErroPrecorrecao) as e:
                if ao_erro:
                    ao_erro(str(e))
                if not self.sessao.aberta or isinstance(e, OSError):
                    self._caiu(str(e))
                continue
            except Exception as e:  # noqa: BLE001
                if ao_erro:
                    ao_erro(str(e))
                continue
            if ao_fim:
                ao_fim(r)
        self.sessao.fechar()

    def _caiu(self, msg):
        self.sessao.fechar()
        with self._trava:
            self._ultimas.clear()
        while True:
            try:
                self.fila.get_nowait()
            except queue.Empty:
                break
        self._parar.set()
        if self.ao_queda:
            self.ao_queda(msg)


# ---------------------------------------------------------------- canal e potência
def itens_potencia(passos, standalone):
    """Initializer.setPowerRanges(): rótulos e comandos da escolha de potência.
    Devolve [(rótulo, comando, porta)]."""
    n = len(passos)
    out = []
    if standalone:
        for i in range(1, n):
            a = passos[i - 1] / 10.0 + (0.0 if i == 1 else 0.1)
            out.append(("%.1f a %.1f dBm" % (a, passos[i] / 10.0), "op" + hexn(passos[i], 3) + "\n\r", 5000))
    else:
        for i in range(n - 1):
            out.append(("Curva %d" % (i + 1), "w229" + hexn(i, 2) + "\n\r", 10001))
        out.append(("Curva plana", "w229ff\n\r", 10001))
    return out


def potencia_no_status(st, passos, standalone, modo_b=False):
    """StateHolder.getPowerLevel(): índice da curva em uso (n-1 = plana)."""
    n = len(passos)
    if standalone:
        i0 = 548 if modo_b else 532
        reg = (st[i0] << 8) + st[i0 + 1]
        for i in range(n - 1):
            if reg <= passos[i + 1]:
                return i
        return n - 2
    v = st[562]
    return n - 1 if v == 255 else v


def canal_no_status(st, numeros, modo_b=False):
    """MbChoice5000 'cho_channel_prec': posição do canal de saída em uso."""
    v = st[539 if modo_b else 523]
    for k, num in enumerate(numeros):
        if (num & 0xFF) == v:
            return k
    return None
