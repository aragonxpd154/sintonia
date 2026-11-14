"""Motor de campos: cada widget do applet original (MbLed, MbChoice3...) vira
um objeto que sabe ler seu valor do bloco de status de 1405 bytes e montar os
comandos de escrita, reproduzindo a lógica do código Java original.

Não depende de GTK: é testável isoladamente e usado também pelo simulador.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .fmt import fmt_num, fmt_sci, hexn


# ---------------------------------------------------------------- comandos
@dataclass
class Cmd:
    """Um comando para a porta 10001. `expect` é quantos bytes o original lia
    de resposta (o equipamento ecoa o comando) ou "linha" (lê até \\n)."""
    texto: str
    expect: object = None
    porta: int = 10001

    def bytes(self) -> bytes:
        return self.texto.encode("latin-1")

    def esperado(self):
        return len(self.texto) if self.expect is None else self.expect


class Recusado(Exception):
    """Escrita recusada pela validação (fora da faixa etc.)."""


# ---------------------------------------------------------------- estado lido
@dataclass
class Valor:
    texto: str = ""             # texto para exibição
    bruto: object = None        # valor numérico / índice
    estado: str = "normal"      # normal | standby | desligado | erro
    ligado: bool | None = None  # LEDs, chaves
    cor: str | None = None      # cor do LED (hex) quando aplicável
    extra: dict = field(default_factory=dict)


def u8(st, i):
    return st[i] & 0xFF


def mask_bits(s: str):
    """(bitNumber, nbits) de uma máscara binária como "00110000"."""
    last = s.rfind("1")
    first = s.find("1")
    if last < 0:
        return 0, 0
    return len(s) - 1 - last, last - first + 1


# ---------------------------------------------------------------- base
class Campo:
    tipo = "Campo"
    escrevivel = False
    composto = False

    def __init__(self, tipo, var, calls):
        self.tipo = tipo
        self.var = var
        self.index = 1
        self.is16 = False
        self.is32 = False
        self.title = ""
        self.name = None
        self.enabled = True
        self.do_set_state = True
        self.standby = False
        self.visible = True
        self.read_only = False
        self.text_inicial = None
        self.subcampos: list[Campo] = []
        self.extras = {}
        self.dispositivo = None   # preenchido pelo modelo
        for k, v in calls:
            self.aplicar(k, v)

    # -- chamadas setXxx do Java
    def aplicar(self, k, v):
        f = getattr(self, "set_" + k, None)
        if f is not None:
            f(v)
        else:
            self.extras[k] = v

    def set_index(self, v):
        self.index = int(v)

    def set_16bitRegister(self, v):
        self.is16 = bool(v)

    def set_32bitRegister(self, v):
        self.is32 = bool(v)

    def set_title(self, v):
        self.title = str(v)
        if self.name is None:
            self.name = str(v)

    def set_name(self, v):
        self.name = str(v)

    def set_enabled(self, v):
        self.enabled = bool(v)

    def set_doSetState(self, v):
        self.do_set_state = bool(v)

    def set_standBy(self, v):
        if isinstance(v, bool):
            self.standby = v

    def set_visible(self, v):
        if isinstance(v, bool):
            self.visible = v

    def set_readOnly(self, v):
        self.read_only = bool(v)

    def set_text(self, v):
        self.text_inicial = v

    # -- largura de registro
    @property
    def largura(self):
        return 16 if self.is16 else (32 if self.is32 else 8)

    @property
    def nchars(self):
        return 4 if self.is16 else (8 if self.is32 else 2)

    def reg(self, st):
        r = u8(st, self.index)
        if self.is16:
            r += u8(st, self.index + 1) << 8
        elif self.is32:
            r = u8(st, self.index) + (u8(st, self.index + 1) << 8) + \
                (u8(st, self.index + 2) << 16) + (u8(st, self.index + 3) << 24)
        return r

    def ler(self, st) -> Valor:
        return Valor()

    def comandos(self, novo):
        raise Recusado("Campo somente leitura")

    def faixa(self):
        return None

    def __repr__(self):
        return "<%s %s idx=%s %r>" % (self.tipo, self.var, self.index, self.title)


# ---------------------------------------------------------------- LED
class Led(Campo):
    def __init__(self, tipo, var, calls):
        self.mask = 1
        self.value_on = 1
        self.cor_on = "#00ff00"
        self.cor_off = "#c0c0c0"
        super().__init__(tipo, var, calls)

    def _bin(self, s):
        n = self.largura if self.largura != 32 else 8
        if len(s) < n:
            return None
        return int(s[:n], 2)

    def set_mask(self, s):
        v = self._bin(s)
        if v is not None:
            self.mask = v

    def set_valueOn(self, s):
        v = self._bin(s)
        if v is not None:
            self.value_on = v

    def set_bitNumber(self, n):
        w = 16 if self.is16 else 8
        s = ("1" + "0" * int(n)).rjust(w, "0")
        self.set_mask(s)
        self.set_valueOn(s)

    def set_colorOn(self, c):
        self.cor_on = c

    def set_colorOff(self, c):
        self.cor_off = c

    def ler(self, st):
        if not self.enabled:
            return Valor(estado="desligado")
        if self.standby:
            return Valor(estado="standby")
        n = u8(st, self.index)
        if self.is16:
            n += u8(st, self.index + 1) << 8
        on = (n & self.mask) == self.value_on
        return Valor(ligado=on, cor=self.cor_on if on else self.cor_off, bruto=on)


# ---------------------------------------------------------------- textos
class Texto(Campo):
    """MbTextField: número lido do status, exibido com fator de escala."""

    def __init__(self, tipo, var, calls):
        self.n_chars = 2
        self.inverted = True
        self.mask_hex = None
        self.negative = False
        self.x_factor = 1.0
        self.hex = False
        self.max_digits = -1
        self.frac = 3
        super().__init__(tipo, var, calls)

    def set_numbeOfChars(self, v):
        self.n_chars = int(v)

    def set_inverted(self, v):
        self.inverted = bool(v)

    def set_mask(self, v):
        self.mask_hex = v

    def set_negative(self, v):
        self.negative = bool(v)

    def set_xFactor(self, v):
        self.x_factor = float(v)

    def set_hex(self, v):
        self.hex = bool(v)

    def set_maxDigits(self, v):
        self.max_digits = int(v)

    def numero(self, st):
        nb = self.n_chars // 2
        idx = self.index
        val = 0
        if self.is16:
            for n in range(nb):
                j = (n - 1 if n % 2 == 1 else n + 1) + idx
                val += u8(st, j) << ((nb - n - 1) * 8)
        elif self.inverted:
            for n in range(nb):
                val += u8(st, n + idx) << (n * 8)
        else:
            for n in range(nb):
                val += u8(st, n + idx) << ((nb - n - 1) * 8)
        if self.mask_hex:
            val &= int(self.mask_hex, 16)
        if self.is16:
            if self.negative and self.mask_hex and val > int(self.mask_hex, 16) // 2:
                val = val - int(self.mask_hex, 16) - 1
        elif self.negative and val > 2 ** (4 * self.n_chars) / 2 - 1:
            val -= 2 ** (4 * self.n_chars)
        return val

    def formatar(self, val):
        x = val * self.x_factor
        if self.hex:
            s = format(int(round(x)), "x")
            return s[: self.max_digits] if self.max_digits != -1 else "0x" + s
        s = fmt_num(x, self.frac)
        return s[: self.max_digits] if self.max_digits != -1 else s

    def ler(self, st):
        if not self.enabled:
            return Valor(estado="desligado")
        if self.standby:
            return Valor("—", estado="standby")
        v = self.numero(st)
        return Valor(self.formatar(v), bruto=v * self.x_factor)


class TextoPotencia(Texto):
    """MbTextFieldPower: zero = sem leitura."""

    def ler(self, st):
        if not self.enabled:
            return Valor(estado="desligado")
        n = u8(st, self.index + 1) | (u8(st, self.index) << 8)
        if n == 0:
            return Valor("—", estado="standby")
        return super().ler(st)


class TextoNivelRx(Texto):
    def __init__(self, tipo, var, calls):
        super().__init__(tipo, var, calls)
        if not any(k == "index" for k, _ in calls):
            self.index = 743

    def ler(self, st):
        n = u8(st, self.index)
        if n == 0:
            return Valor("Sobrecarga na entrada", bruto=0, estado="erro")
        if n == 255:
            return Valor("Potência baixa", bruto=-255, estado="erro")
        return Valor(fmt_num(-n) + " dBm", bruto=-n)


class TextoEscolha(Texto):
    """MbTextFieldChoice / MbTextField2: índice -> texto de uma lista."""

    def __init__(self, tipo, var, calls):
        self.items = []
        self.values_on = None
        self.bit = 8 if tipo == "MbTextFieldChoice" else 8
        self.nbits = 8
        self.sel = 0
        super().__init__(tipo, var, calls)

    def set_items(self, v):
        self.items = list(v)

    def set_valuesOn(self, v):
        self.values_on = list(v)

    def set_mask(self, s):
        w = 8 if self.tipo != "MbTextField2" else (16 if self.is16 else 8)
        if len(s) < w:
            return
        s = s[:w]
        self.bit, self.nbits = mask_bits(s)

    def ler(self, st):
        if not self.enabled:
            return Valor(estado="desligado")
        if self.standby:
            return Valor("—", estado="standby")
        n = (u8(st, self.index) >> self.bit) & ((1 << self.nbits) - 1)
        sel = n
        if self.values_on:
            for i, v in enumerate(self.values_on):
                if int(v, 2) >> self.bit == n:
                    sel = i
        self.sel = sel
        if 0 <= sel < len(self.items):
            return Valor(self.items[sel], bruto=sel)
        return Valor("Erro (%d)" % n, bruto=sel, estado="erro")


GRAU = "°"


class TextoEspecial(Texto):
    """MbTextFieldCustom: GPS (latitude, longitude, data/hora), satélites e
    Time Offset — decodificação escolhida pelo título, como no original."""

    def ler(self, st):
        t = self.title
        i = self.index
        if not self.enabled:
            return Valor(estado="desligado")
        if "Latitude" in t:
            norte = (u8(st, i + 4) & 1) != 1
            s = "%d%s %d' %d'' %s" % (u8(st, i), GRAU, u8(st, i + 1), u8(st, i + 2) + (u8(st, i + 3) << 8),
                                     "N" if norte else "S")
            graus = u8(st, i) + u8(st, i + 1) / 60 + (u8(st, i + 2) + (u8(st, i + 3) << 8)) / 3600
            return Valor(s, bruto=graus if norte else -graus)
        if "Longitude" in t:
            leste = (u8(st, i + 2) & 1) != 1
            s = "%d%s %d' %d'' %s" % (u8(st, i), GRAU, u8(st, i + 1), u8(st, i + 3) + (u8(st, i + 4) << 8),
                                     "L" if leste else "O")
            graus = u8(st, i) + u8(st, i + 1) / 60 + (u8(st, i + 3) + (u8(st, i + 4) << 8)) / 3600
            return Valor(s, bruto=graus if leste else -graus)
        if "UTC Date" in t:
            return Valor("%02d/%02d/%d" % (st[i] if st[i] < 128 else st[i] - 256, u8(st, i + 1), 2000 + u8(st, i + 2)))
        if "UTC Time" in t:
            if i > 30:
                return Valor("%d:%02d" % (u8(st, i), u8(st, i + 1)))
            return Valor("%d:%02d" % (u8(st, i + 2), u8(st, i + 1)))
        if "Visible Sat" in t or "Tracked Sat" in t:
            s = "".join(str(u8(st, i + k)) for k in range(self.n_chars // 2))
            try:
                v = int(s)
            except ValueError:
                v = 0
            return Valor(str(v), bruto=v)
        if "Time Offset" in t:
            n = (u8(st, i) << 16) + (u8(st, i + 1) << 24) + u8(st, i + 2) + (u8(st, i + 3) << 8)
            if n >= 2 ** 31:
                n -= 2 ** 32
            neg = u8(st, 307) != 0
            return Valor(("- " if neg else "") + str(n), bruto=-n if neg else n)
        return super().ler(st)


# ---------------------------------------------------------------- escolhas
class Escolha(Campo):
    """MbChoice3_borderlayout e derivados."""
    escrevivel = True

    def __init__(self, tipo, var, calls):
        self.items = []
        self.values_on = None
        self.command = None
        self.command_items = None
        self.bit = 0
        self.nbits = 8
        self.registro = 0
        self.sel = -1
        self.mask_str = None
        super().__init__(tipo, var, calls)

    def set_items(self, v):
        if isinstance(v, list):
            self.items = [str(x) for x in v]

    def set_valuesOn(self, v):
        self.values_on = list(v) if v is not None else None

    def set_command(self, v):
        self.command = v

    def set_commandItems(self, v):
        self.command_items = list(v)

    def set_mask(self, s):
        w = self.largura
        if len(s) < w:
            return
        s = s[:w]
        self.mask_str = s
        self.bit, self.nbits = mask_bits(s)

    def set_16bitRegister(self, v):
        super().set_16bitRegister(v)
        if self.mask_str is None:
            self.nbits = 8

    def valor_status(self, st):
        r = self.reg(st)
        self.registro = r
        n = (r >> self.bit) & ((1 << self.nbits) - 1)
        sel = n
        if self.values_on:
            for i, v in enumerate(self.values_on):
                if int(v, 2) >> self.bit == n:
                    sel = i
                    break
        return n, sel

    def ler(self, st):
        n, sel = self.valor_status(st)
        self.sel = sel
        estado = "normal" if self.enabled else "desligado"
        if self.standby:
            estado = "standby"
        if 0 <= sel < len(self.items):
            return Valor(self.items[sel], bruto=sel, estado=estado)
        return Valor("Desconhecido (%d)" % n, bruto=-1, estado="erro")

    def _cheio(self):
        return (1 << self.largura) - 1

    def comandos(self, novo):
        i = int(novo)
        if self.command_items is not None:
            c = self.command_items[i]
            return [Cmd(c)]
        fm = (1 << self.nbits) - 1
        if self.values_on is not None:
            r = (self.registro & (self._cheio() - (fm << self.bit))) + int(self.values_on[i], 2)
        elif self.command is not None:
            r = (self.registro & (self._cheio() - (fm << self.bit))) + (i << self.bit)
        else:
            raise Recusado("Sem comando de escrita")
        return [Cmd(self.command + hexn(r, self.nchars) + "\n\r")]


class EscolhaCanal(Escolha):
    """MbChoiceChannelOut: lista de canais vem do arquivo .cdef."""

    def set_modeNumber(self, v):
        self.extras["modeNumber"] = v

    def comandos(self, novo):
        i = int(novo)
        if not self.command_items:
            raise Recusado("Lista de canais (.cdef) não carregada")
        return [Cmd(self.command + self.command_items[i] + "\n\r", 3)]


class EscolhaFra1(Escolha):
    def ler(self, st):
        r = self.reg(st)
        self.ultimo = u8(st, self.index)
        if self.mask_str:
            r &= int(self.mask_str, 2)
        self.registro = r
        n = (r >> self.bit) & ((1 << self.nbits) - 1)
        sel = n
        if self.values_on:
            for i, v in enumerate(self.values_on):
                if int(v, 2) == n:
                    sel = i
                    break
        self.sel = sel
        if 0 <= sel < len(self.items):
            return Valor(self.items[sel], bruto=sel)
        return Valor("Desconhecido (%d)" % n, bruto=-1, estado="erro")

    def comandos(self, novo):
        i = int(novo)
        inv = int("".join("1" if c == "0" else "0" for c in (self.mask_str or "1" * 8)), 2)
        ultimo = getattr(self, "ultimo", 0) & inv
        fm = (1 << self.nbits) - 1
        if self.command_items is not None:
            return [Cmd(self.command_items[i])]
        if self.values_on is not None:
            r = (self.registro & (self._cheio() - (fm << self.bit))) + (int(self.values_on[i], 2) << self.bit)
        else:
            r = (self.registro & (self._cheio() - (fm << self.bit))) + (i << self.bit)
        r += ultimo
        return [Cmd(self.command + hexn(r, self.nchars) + "\n\r")]


class EscolhaBarras(Escolha):
    """MbChoiceTestBars."""

    def ler(self, st):
        n, _ = self.valor_status(st)
        if n in (0, 256):
            self.sel = 1
        elif n == 1:
            self.sel = 0
        else:
            return Valor("Desconhecido (%d)" % n, bruto=-1, estado="erro")
        return Valor(self.items[self.sel], bruto=self.sel)


class EscolhaMfnSfnDvbt(Escolha):
    def __init__(self, tipo, var, calls):
        super().__init__(tipo, var, calls)
        self.title = self.title or "MFN-SFN"
        self.name = "MFN-SFN"
        if not any(k == "index" for k, _ in calls):
            self.index = 51

    def ler(self, st):
        a = (st[self.index] & 1) == 1
        b = (st[self.index + 2] & 1) == 1
        sel = 0 if (not a and not b) else 1 if (not a and b) else 2 if (a and b) else 3
        self.sel = sel
        if sel < len(self.items):
            return Valor(self.items[sel], bruto=sel)
        return Valor(str(sel), bruto=sel)

    def comandos(self, novo):
        n = int(novo)
        cmds = [
            Cmd("w00015000%s\n\r" % ("1" if n > 1 else "0"), 10),
            Cmd("w00016000%s\n\r" % ("0" if n in (0, 3) else "1"), 10),
            Cmd("w00027000%s\n\r" % ("0" if n > 1 else "1"), 10),
        ]
        if n > 1:
            cmds += [Cmd("w000250000\n\r", 10), Cmd("w000e40001\n\r", 10), Cmd("w000ec0001\n\r", 10)]
        else:
            cmds += [Cmd("w000250001\n\r", 10), Cmd("w000e40000\n\r", 10), Cmd("w000ec0000\n\r", 10)]
        return cmds


# ---------------------------------------------------------------- caixa de seleção
class Chave(Campo):
    """MbCheckBox3 / MbRadioButton."""
    escrevivel = True

    def __init__(self, tipo, var, calls):
        self.bit = 0
        self.inverted = False
        self.command = None
        self.command_on = None
        self.command_off = None
        self.registro = 0
        self.on = False
        self.titulos_radio = None
        super().__init__(tipo, var, calls)

    def set_bitNumber(self, v):
        self.bit = int(v)

    def set_inverted(self, v):
        self.inverted = bool(v)

    def set_command(self, v):
        self.command = v

    def set_commandOn(self, v):
        self.command_on = list(v)

    def set_commandOff(self, v):
        self.command_off = list(v)

    def set_titleRadio1(self, v):
        self.titulos_radio = [v, (self.titulos_radio or ["", ""])[1]]

    def set_titleRadio2(self, v):
        self.titulos_radio = [(self.titulos_radio or ["", ""])[0], v]

    def ler(self, st):
        if self.standby:
            self.on = False
            return Valor("—", estado="standby", ligado=False)
        r = u8(st, self.index)
        if self.is16 and self.tipo != "MbRadioButton":
            r += u8(st, self.index + 1) << 8
        self.registro = r
        b = (r & (1 << self.bit)) == (1 << self.bit)
        self.on = (not b) if self.inverted else b
        return Valor("Sim" if self.on else "Não", bruto=self.on, ligado=self.on,
                     estado="normal" if self.enabled else "desligado")

    def comandos(self, novo):
        quer = bool(novo)
        if quer == self.on:
            return []
        if self.command_off is None:
            if self.command is None:
                raise Recusado("Sem comando de escrita")
            r = self.registro ^ (1 << self.bit)
            w = 4 if (self.is16 and self.tipo != "MbRadioButton") else 2
            return [Cmd(self.command + hexn(r, w) + "\n\r")]
        lista = self.command_off if self.on else self.command_on
        return [Cmd(c + "\n\r") for c in lista]


class ChaveMuteAudio(Chave):
    def ler(self, st):
        i = self.index
        self.registro = (u8(st, i + 1) << 8) + u8(st, i)
        self.num_emph = self.registro & 0xFFF9
        self.on = (self.registro & 6) == 0
        return Valor("Sim" if self.on else "Não", bruto=self.on, ligado=self.on)

    def comandos(self, novo):
        if bool(novo) == self.on:
            return []
        bl = (self.registro & 6) == 0
        r = (self.num_emph & 0xFFF9) | (6 if bl else 0)
        return [Cmd(self.command + hexn(r, 4 if self.is16 else 2) + "\n\r")]


# ---------------------------------------------------------------- botões
class Botao(Campo):
    """MbButton3 / MbButtonRf (liga/desliga um bit) e MbButtonEmpty3 (ação)."""
    escrevivel = True

    def __init__(self, tipo, var, calls):
        self.command = None
        self.command_on = None
        self.command_off = None
        self.bit = 0
        self.registro = 0
        self.on = False
        self.titulo_on = ""
        self.titulo_off = ""
        super().__init__(tipo, var, calls)
        if tipo == "MbButtonRf":
            self.titulo_on, self.titulo_off = "ON", "OFF"

    def set_command(self, v):
        self.command = v

    def set_commandOn(self, v):
        self.command_on = list(v)

    def set_commandOff(self, v):
        self.command_off = list(v)

    def set_bitNumber(self, v):
        self.bit = int(v)

    def set_titleOn(self, v):
        self.titulo_on = v

    def set_titleOff(self, v):
        self.titulo_off = v

    @property
    def acao(self):
        return self.tipo == "MbButtonEmpty3"

    def ler(self, st):
        if self.acao:
            return Valor(self.title)
        r = u8(st, self.index)
        if self.is16:
            r += u8(st, self.index + 1) << 8
        self.registro = r
        self.on = (r & 1) == 1
        txt = (self.titulo_on or "Ligado") if self.on else (self.titulo_off or "Desligado")
        extra = {}
        if self.tipo == "MbButtonRf" and (u8(st, 489) & 1) != 1:
            txt = "RF OFF"
            extra["rf_global_off"] = True
        return Valor(txt, bruto=self.on, ligado=self.on, extra=extra)

    def comandos(self, novo=None):
        if self.command_off is None:
            if self.command is None:
                raise Recusado("Botão sem comando")
            on = (self.registro & (1 << self.bit)) == (1 << self.bit)
            if novo is not None and bool(novo) == on:
                return []
            r = (self.registro & (255 - (1 << self.bit))) if on else (self.registro | (1 << self.bit))
            return [Cmd(self.command + hexn(r, 4 if self.is16 else 2) + "\n\r")]
        lista = self.command_off if self.on else self.command_on
        return [Cmd(c + "\r\n") for c in lista][-1:]


# ---------------------------------------------------------------- numéricos
def _log2(x):
    return math.log(x) / math.log(2.0)


class Numero(Campo):
    """MbNumeric: inteiro distribuído em um ou mais registros."""
    escrevivel = True

    def __init__(self, tipo, var, calls):
        self.commands = None
        self.minimo = 0
        self.maximo = 0
        self.inverted = True
        self.write_order = True
        self.less_bits = -1
        self.tot_num_bit = -1
        self.write_only = False
        self.valor_atual = None
        super().__init__(tipo, var, calls)

    @property
    def num_bits(self):
        return 16 if self.is16 else (32 if self.is32 else 8)

    def _calc_less_bits(self):
        self.less_bits = int(self.num_bits * len(self.commands) - _log2(abs(self.minimo) + self.maximo + 1))

    def set_commands(self, v):
        self.commands = list(v)
        if self.minimo != 0 and self.maximo != 0 and self.less_bits == -1:
            self._calc_less_bits()

    def set_minValue(self, v):
        self.minimo = int(v)
        if self.commands is not None and self.less_bits == -1:
            self._calc_less_bits()

    def set_maxValue(self, v):
        self.maximo = int(v)

    def set_lessBits(self, v):
        self.less_bits = int(v)

    def set_totNumBit(self, v):
        self.tot_num_bit = int(v)

    def set_inverted(self, v):
        self.inverted = bool(v)

    def set_writeOrder(self, v):
        self.write_order = bool(v)

    def set_writeOnly(self, v):
        self.write_only = bool(v)

    def faixa(self):
        return (self.minimo, self.maximo)

    def valor(self, st):
        n2 = len(self.commands)
        if self.is32:
            n2 *= 4
        idx = self.index
        val = 0
        if self.is16:
            for n in range(n2):
                val += u8(st, n * 2 + idx + 1) << (8 * (n2 * 2 - n * 2 - 1))
                val += u8(st, n * 2 + idx) << (8 * (n2 * 2 - n * 2 - 2))
        elif self.inverted:
            for n in range(n2):
                val += u8(st, n + idx) << (8 * n)
        else:
            for n in range(n2):
                val += u8(st, n + idx) << ((n2 - n - 1) * 8)
        bits = (self.num_bits * n2 - self.less_bits) if self.tot_num_bit == -1 else (self.tot_num_bit - self.less_bits)
        val &= (1 << bits) - 1
        if self.minimo < 0 and val > (2 ** bits) / 2 - 1:
            val -= 2 ** bits
        return val

    def ler(self, st):
        if self.standby:
            return Valor("", estado="standby")
        if self.commands is None:
            return Valor("")
        if self.write_only:
            return Valor("")
        v = self.valor(st)
        self.valor_atual = v
        return Valor(fmt_num(v, 0), bruto=v, estado="normal" if self.enabled else "desligado")

    def validar(self, v):
        try:
            v = int(v)
        except (TypeError, ValueError):
            raise Recusado("Valor inválido")
        if v < self.minimo or v > self.maximo:
            raise Recusado("Fora da faixa (%s a %s)" % (fmt_num(self.minimo, 0), fmt_num(self.maximo, 0)))
        return v

    def comandos(self, novo):
        v = self.validar(novo)
        if self.valor_atual is not None and v == self.valor_atual:
            return []
        n = len(self.commands)
        nc = self.nchars
        if self.minimo < 0 and v < 0:
            largura = self.num_bits * n - self.less_bits
            s = format(v & ((1 << largura) - 1), "x").rjust(nc * n, "0")
            lst = [Cmd(self.commands[n - 1 - i if self.inverted else i] + s[nc * i: nc * i + nc] + "\n\r",
                       len(self.commands[0]) + 2) for i in range(n)]
            return list(reversed(lst)) if self.write_order else lst
        lst = [Cmd(self.commands[i if self.inverted else n - 1 - i] + hexn(v >> (i * self.num_bits), nc) + "\r\n",
                   len(self.commands[0]) + 2) for i in range(n)]
        return lst if self.write_order else list(reversed(lst))


class NumeroTexto(Numero):
    """MbNumericText: texto (communities SNMP)."""

    def ler(self, st):
        s = []
        for i in range(16):
            c = u8(st, self.index + i)
            if c == 0:
                break
            s.append(chr(c))
        self.valor_atual = "".join(s)
        return Valor(self.valor_atual, bruto=self.valor_atual)

    def faixa(self):
        return None

    def comandos(self, novo):
        t = str(novo)
        if not 1 <= len(t) <= 16:
            raise Recusado("Use de 1 a 16 caracteres")
        if t == self.valor_atual:
            return []
        return [Cmd(self.commands[0] + t + "\n\r", 2)]


class NumeroSquelch(Numero):
    def __init__(self, tipo, var, calls):
        super().__init__(tipo, var, calls)
        if not self.title:
            self.title = "Squelch [dBm]"
        self.minimo, self.maximo = -80, -20

    def valor(self, st):
        return -u8(st, self.index)

    def comandos(self, novo):
        v = self.validar(novo)
        return [Cmd(self.commands[0] + hexn(-v & 0xFF, 2) + "\r\n", 5)]


class Decimal(Numero):
    """MbNumericDouble e derivados (valores com casas decimais)."""

    def __init__(self, tipo, var, calls):
        self.dmin = 0.0
        self.dmax = 0.0
        self.x_factor = 1.0
        self.subtract = 0.0
        self.step = 0.1
        self.watt = False
        self.threshold = False
        super().__init__(tipo, var, calls)

    def set_minValueDouble(self, v):
        self.dmin = float(v)

    def set_maxValueDouble(self, v):
        self.dmax = float(v)

    def set_xFactor(self, v):
        self.x_factor = float(v)

    def set_subtract(self, v):
        self.subtract = float(v)

    def set_step(self, v):
        self.step = float(v)

    def set_wattMisure(self, v):
        self.watt = bool(v)

    def set_threshold(self, v):
        self.threshold = bool(v)

    def set_modeNumber(self, v):
        self.extras["modeNumber"] = v

    def faixa(self):
        return (self.dmin, self.dmax)

    def valor_d(self, st):
        b = u8(st, self.index)
        t = self.tipo
        if t == "MbNumericPower":
            if self.threshold:
                return -b / 10.0
            d = ((b << 8) + u8(st, self.index + 1)) / 10.0
            return 10 ** (d / 10.0) / 1000.0 if self.watt else d
        if t == "MbNumericAlarmDelay":
            return b / 10.0
        if t == "MbNumericDoubleImp":
            return b / self.x_factor
        if t == "MbNumericDoubleWhiteSync":
            return b / self.x_factor + self.subtract
        if t == "MbNumericBerThreshold":
            return ((b << 8) + u8(st, self.index + 1)) / 1e6
        return float(b)

    def formatar(self, d):
        if self.tipo == "MbNumericBerThreshold":
            return fmt_sci(d)
        return fmt_num(d, 3)

    def ler(self, st):
        if self.standby:
            return Valor("", estado="standby")
        if self.commands is None or self.write_only:
            return Valor("")
        d = self.valor_d(st)
        self.valor_atual = d
        return Valor(self.formatar(d), bruto=d, estado="normal" if self.enabled else "desligado")

    def validar(self, v):
        try:
            d = float(v)
        except (TypeError, ValueError):
            raise Recusado("Valor inválido")
        if self.dmin == 0.0 and self.dmax == 0.0:
            raise Recusado("Faixa não definida (arquivo de calibração ausente)")
        if d < self.dmin - 1e-9 or d > self.dmax + 1e-9:
            raise Recusado("Fora da faixa (%s a %s)" % (self.formatar(self.dmin), self.formatar(self.dmax)))
        return d

    def comandos(self, novo):
        d = self.validar(novo)
        t = self.tipo
        c = self.commands
        if t == "MbNumericPower":
            if self.threshold:
                return [Cmd(c[0] + hexn(round(-d * 10.0), 2) + "\n\r", 5)]
            if self.watt:
                n = int(round(10.0 * math.log10(d * 1000.0) * 10.0))
            else:
                n = int(round(d * 10.0))
            return [Cmd(c[1] + hexn(n, 2) + "\n\r", 5), Cmd(c[0] + hexn(n >> 8, 2) + "\n\r", 5)]
        if t == "MbNumericAlarmDelay":
            return [Cmd(c[0] + hexn(round(d * 10.0), 4) + "\n\r", 5)]
        if t == "MbNumericDoubleImp":
            n = int(round(round(d / self.step) * self.step * self.x_factor))
            return [Cmd(c[0] + hexn(n, 2) + "\n\r", 6)]
        if t == "MbNumericDoubleWhiteSync":
            n = int(round((d - self.subtract) * self.x_factor))
            return [Cmd(c[0] + hexn(n, 2) + "\n\r", 6)]
        if t == "MbNumericBerThreshold":
            n = int(round(1e6 * d))
            return [Cmd(c[1] + hexn(n, 2) + "\n\r", 5), Cmd(c[0] + hexn(n >> 8, 2) + "\n\r", 5)]
        raise Recusado("Tipo sem escrita: %s" % t)


class BerLimiar(Decimal):
    def __init__(self, tipo, var, calls):
        super().__init__(tipo, var, calls)
        self.dmax, self.dmin = 0.06, 1.0e-6


# ---------------------------------------------------------------- IP / MAC / data
class EnderecoIP(Campo):
    escrevivel = True

    def __init__(self, tipo, var, calls):
        self.commands = None
        self.inverted = False
        self.ip = [0, 0, 0, 0]
        super().__init__(tipo, var, calls)

    def set_commands(self, v):
        self.commands = list(v)

    def set_inverted(self, v):
        self.inverted = bool(v)

    def set_readOnlyGray(self, v):
        self.read_only = bool(v)

    def set_editable(self, v):
        self.read_only = not bool(v)

    @property
    def escrevivel_(self):
        return not self.read_only and self.commands

    def ler(self, st):
        i = self.index
        if self.is16:
            ip = [u8(st, i + 1), u8(st, i), u8(st, i + 3), u8(st, i + 2)]
        else:
            ip = [0] * 4
            for k in range(4):
                ip[3 - k if self.inverted else k] = u8(st, i + k)
        self.ip = ip
        return Valor(".".join(str(x) for x in ip), bruto=list(ip))

    def comandos(self, novo):
        if self.read_only or not self.commands:
            raise Recusado("Campo somente leitura")
        partes = str(novo).strip().split(".")
        if len(partes) != 4:
            raise Recusado("Endereço IP inválido")
        try:
            ip = [int(p) for p in partes]
        except ValueError:
            raise Recusado("Endereço IP inválido")
        if any(x < 0 or x > 255 for x in ip):
            raise Recusado("Cada parte do IP vai de 0 a 255")
        out = []
        if self.is16:
            if ip[0:2] != self.ip[0:2]:
                out.append(Cmd(self.commands[0] + hexn(ip[1] + (ip[0] << 8), 4) + "\n\r", 2))
            if ip[2:4] != self.ip[2:4]:
                out.append(Cmd(self.commands[1] + hexn(ip[3] + (ip[2] << 8), 4) + "\n\r", 2))
        else:
            for k in range(4):
                if ip[k] != self.ip[k]:
                    out.append(Cmd(self.commands[k] + hexn(ip[k], 2) + "\n\r", 2))
        return out


class EnderecoMAC(Campo):
    def ler(self, st):
        i = self.index
        if self.is16:
            mac = [u8(st, i + 1), u8(st, i), u8(st, i + 3), u8(st, i + 2), u8(st, i + 5), u8(st, i + 4)]
        else:
            mac = [u8(st, i + k) for k in range(6)]
        return Valor(":".join("%02X" % x for x in mac), bruto=mac)


class DataHora(Campo):
    """MbSpinnerDate2: data/hora de comutação (6 bytes)."""
    escrevivel = True
    REGS = ["w234", "w235", "w236", "w237", "w238", "w239"]

    def ler(self, st):
        i = self.index
        v = [u8(st, i) + 2000, u8(st, i + 1), u8(st, i + 2), u8(st, i + 3), u8(st, i + 4), u8(st, i + 5)]
        self.atual = v
        return Valor("%02d/%02d/%04d %02d:%02d:%02d" % (v[2], v[1], v[0], v[3], v[4], v[5]), bruto=v)

    def comandos(self, novo):
        a, m, d, h, mi, s = novo
        if not (2000 <= a <= 2099 and 1 <= m <= 12 and 1 <= d <= 31 and 0 <= h < 24 and 0 <= mi < 60 and 0 <= s < 60):
            raise Recusado("Data/hora inválida")
        atual = getattr(self, "atual", [None] * 6)
        out = []
        for k, (novo_v, reg) in enumerate(zip([a - 2000, m, d, h, mi, s], self.REGS)):
            antigo = atual[k] - 2000 if (k == 0 and atual[k] is not None) else atual[k]
            if novo_v != antigo:
                out.append(Cmd(reg + hexn(novo_v, 2) + "\n\r", 6))
        return out


class BarraNivel(Campo):
    """MbBar: nível de RX recebido."""

    def __init__(self, tipo, var, calls):
        super().__init__(tipo, var, calls)
        if not any(k == "index" for k, _ in calls):
            self.index = 743

    def ler(self, st):
        n = u8(st, self.index)
        return Valor(fmt_num(-n) + " dBm", bruto=-n)


# ---------------------------------------------------------------- compostos
class Composto(Campo):
    composto = True

    def sub(self, cls, tipo, calls):
        c = cls(tipo, self.var + "." + str(len(self.subcampos)), calls)
        self.subcampos.append(c)
        return c


class EstatisticaASI(Composto):
    def __init__(self, tipo, var, calls):
        super().__init__(tipo, var, [])
        S = self.sub
        self.clock = S(Texto, "MbTextField", [["16bitRegister", True], ["numbeOfChars", 8], ["title", "Word rate"]])
        self.packet = S(Texto, "MbTextField", [["16bitRegister", True], ["xFactor", 8.0], ["numbeOfChars", 8], ["title", "Bitrate"]])
        self.filtered = S(Texto, "MbTextField", [["16bitRegister", True], ["xFactor", 8.0], ["numbeOfChars", 8], ["title", "Filtered bitrate"]])
        self.wrong = S(Texto, "MbTextField", [["16bitRegister", True], ["mask", "1FFFFFF"], ["numbeOfChars", 8], ["title", "Word errors"]])
        self.lock = S(Led, "MbLed", [["16bitRegister", True], ["mask", "0100000000000000"], ["title", "Lock"], ["valueOn", "0100000000000000"]])
        self.overflow = S(Led, "MbLed", [["16bitRegister", True], ["colorOn", "#ff0000"], ["mask", "1000000000000000"], ["title", "Overflow"], ["valueOn", "1000000000000000"]])
        self.formato = S(TextoEscolha, "MbTextField2", [["items", ["204", "188"]], ["mask", "00010000"], ["title", "Format"], ["valuesOn", ["00000000", "00010000"]]])
        self.cd = S(Led, "MbLed", [["16bitRegister", True], ["mask", "0000100000000000"], ["title", "CD"], ["valueOn", "0000100000000000"]])
        self.standby = True
        for k, v in calls:
            self.aplicar(k, v)

    def set_index(self, n):
        self.index = n
        self.clock.index = n
        self.packet.index = n + 4
        self.filtered.index = n + 8
        for s in (self.wrong, self.lock, self.overflow, self.cd):
            s.index = n + 12
        self.formato.index = n + 13

    def ler(self, st):
        if self.standby:
            for s in self.subcampos:
                s.standby = True
            return Valor("—", estado="standby")
        sem_lock = (0x40 & st[self.lock.index + 1]) != 64
        for s in self.subcampos:
            s.standby = sem_lock
        return Valor("Travado" if not sem_lock else "Sem sinal", ligado=not sem_lock)


class EstatisticaGbE(Composto):
    def __init__(self, tipo, var, calls):
        super().__init__(tipo, var, [])
        S = self.sub
        self.lock = S(Led, "MbLed", [["16bitRegister", True], ["mask", "0000000000001000"], ["title", "Lock"], ["valueOn", "0000000000001000"]])
        self.overflow = S(Led, "MbLed", [["16bitRegister", True], ["colorOn", "#ff0000"], ["mask", "0000000000010000"], ["title", "Overflow"], ["valueOn", "0000000000010000"]])
        self.formato = S(TextoEscolha, "MbTextField2", [["16bitRegister", True], ["items", ["204", "188"]], ["mask", "0000000000000001"], ["title", "Format"]])
        self.filtered = S(Texto, "MbTextField", [["16bitRegister", True], ["xFactor", 1504.0], ["numbeOfChars", 8], ["title", "Filtered bitrate"]])
        self.rtp = S(Led, "MbLed", [["16bitRegister", True], ["mask", "0001000000000000"], ["title", "RTP"], ["valueOn", "0001000000000000"]])
        self.udp = S(Led, "MbLed", [["16bitRegister", True], ["mask", "0001000000000000"], ["title", "UDP"], ["valueOn", "0000000000000000"]])
        self.bitrate = S(Texto, "MbTextField", [["16bitRegister", True], ["xFactor", 1504.0], ["numbeOfChars", 8], ["title", "Bitrate"]])
        self.standby = True
        for k, v in calls:
            self.aplicar(k, v)

    def set_index(self, n):
        self.index = n
        self.bitrate.index = n
        self.filtered.index = n + 4
        for s in (self.lock, self.formato, self.overflow, self.udp, self.rtp):
            s.index = n + 8

    def ler(self, st):
        if self.standby:
            for s in self.subcampos:
                s.standby = True
            return Valor("—", estado="standby")
        self.formato.ler(st)
        self.bitrate.x_factor = 1632.0 if self.formato.sel == 0 else 1504.0
        prot = (st[self.index + 9] & 1) != 0
        sem_lock = (8 & st[self.lock.index]) != 8
        for s in self.subcampos:
            s.standby = sem_lock
        self.rtp.cor_on = self.udp.cor_on = "#00ff00" if prot else "#c0c0c0"
        return Valor("Travado" if not sem_lock else "Sem sinal", ligado=not sem_lock)


class EstatisticaGbEComum(Composto):
    def __init__(self, tipo, var, calls):
        super().__init__(tipo, var, [])
        S = self.sub
        self.pacotes = S(Texto, "MbTextField", [["16bitRegister", True], ["numbeOfChars", 4], ["title", "GbE packets"]])
        self.erros = S(Texto, "MbTextField", [["16bitRegister", True], ["numbeOfChars", 4], ["title", "GbE Errors"]])
        self.velocidade = S(TextoEscolha, "MbTextField2", [["16bitRegister", True], ["items", ["10 Mb/s", "100 Mb/s", "1 Gb/s", "Absent"]], ["mask", "0000000000000011"], ["title", "Speed"]])
        self.title = "GbE Statistic"
        for k, v in calls:
            self.aplicar(k, v)

    def set_indexGbePackets(self, n):
        self.pacotes.index = n

    def set_indexSpeed(self, n):
        self.velocidade.index = n

    def set_indexBadFrame(self, n):
        self.erros.index = n

    def ler(self, st):
        return self.velocidade.ler(st)


class EstatisticaSDI(Composto):
    def __init__(self, tipo, var, calls):
        super().__init__(tipo, var, [])
        S = self.sub
        self.status = S(TextoEscolha, "MbTextFieldChoice", [["items", [
            "525 linhas 4:2:2 vídeo componente", "1 inválido", "525 linhas 4:2:2 16x9 vídeo componente",
            "525 linhas 4:4:4 13,5 MHz vídeo componente", "625 linhas 4:2:2 vídeo componente", "5 inválido",
            "625 linhas 4:2:2 16x9 vídeo componente", "625 linhas 4:4:4 13,5 MHz vídeo componente"]],
            ["title", "Standard "]])
        self.cd = S(Led, "MbLed", [["16bitRegister", True], ["bitNumber", 0], ["index", 1223], ["mask", "0000000000001000"], ["title", "CD"], ["valueOn", "0000000000000000"]])
        self.lock = S(Led, "MbLed", [["16bitRegister", True], ["bitNumber", 0], ["index", 1201], ["mask", "0000000000000001"], ["title", "Lock"]])
        for s in self.subcampos:
            s.standby = True
        for k, v in calls:
            self.aplicar(k, v)

    def set_titlePan(self, v):
        self.title = v

    def set_indexCD(self, n):
        self.cd.index = n

    def set_indexLock(self, n):
        self.lock.index = n

    def set_indexStatus(self, n):
        self.status.index = n

    def set_maskCD(self, s):
        self.cd.set_mask(s)

    def set_maskLock(self, s):
        self.lock.set_mask(s)

    def set_maskStatus(self, s):
        self.status.set_mask(s)

    def set_valuOnCD(self, s):
        self.cd.set_valueOn(s)

    def set_valuOnLock(self, s):
        self.lock.set_valueOn(s)

    def set_valuOnStatus(self, v):
        self.status.set_valuesOn(v)

    def ler(self, st):
        if not self.enabled:
            return Valor(estado="desligado")
        if self.standby:
            for s in self.subcampos:
                s.standby = True
            return Valor("—", estado="standby")
        self.lock.standby = False
        on = self.lock.ler(st).ligado
        self.cd.standby = not on
        self.status.standby = not on
        return Valor("Travado" if on else "Sem sinal", ligado=on)


class TravaSTV(Composto):
    def __init__(self, tipo, var, calls):
        super().__init__(tipo, var, [])
        for b, t in ((7, "TPS"), (6, "Symbol Recovery"), (4, "Puncture Rate"), (3, "De-interleaver")):
            self.sub(Led, "MbLed", [["bitNumber", b], ["title", t]])
        for k, v in calls:
            self.aplicar(k, v)

    def set_index(self, n):
        self.index = n
        for s in self.subcampos:
            s.index = n

    def ler(self, st):
        ok = all(s.ler(st).ligado for s in self.subcampos)
        return Valor("Travado" if ok else "Sem trava", ligado=ok)


# ---------------------------------------------------------------- fábrica
TIPOS = {
    "MbLed": Led,
    "MbTextField": Texto,
    "MbTextFieldPower": TextoPotencia,
    "MbTextFieldRxLevel": TextoNivelRx,
    "MbTextFieldChoice": TextoEscolha,
    "MBTextFieldChoiceStandard": TextoEscolha,
    "MbTextField2": TextoEscolha,
    "MbTextFieldCustom": TextoEspecial,
    "MbChoice3_borderlayout": Escolha,
    "MbChoiceChangeMode": Escolha,
    "MbChoiceClockReference": Escolha,
    "MbChoiceMfnSfnIsdbt": Escolha,
    "MbChoicePower": Escolha,
    "MbChoice5000": Escolha,
    "MbChoice3GroupDelaySelector": Escolha,
    "MbChoiceCastom": Escolha,
    "MbChoiceChannelOut": EscolhaCanal,
    "MbChoice3_borderlayout_Fra1": EscolhaFra1,
    "MbChoiceTestBars": EscolhaBarras,
    "MbChoiceMfnSfnDvbt": EscolhaMfnSfnDvbt,
    "MbCheckBox3": Chave,
    "MbRadioButton": Chave,
    "MbCheckAudioMuteTest": ChaveMuteAudio,
    "MbButton3": Botao,
    "MbButtonRf": Botao,
    "MbButtonEmpty3": Botao,
    "MbNumeric": Numero,
    "MbNumeric5000": Numero,
    "MbNumericChannel": Numero,
    "MbNumericOffset": Numero,
    "MbNumericText": NumeroTexto,
    "MbNumericSquelch": NumeroSquelch,
    "MbNumericPower": Decimal,
    "MbNumericAlarmDelay": Decimal,
    "MbNumericDoubleImp": Decimal,
    "MbNumericDoubleWhiteSync": Decimal,
    "MbNumericBerThreshold": BerLimiar,
    "MbIpPanel3": EnderecoIP,
    "MbMacPanel3": EnderecoMAC,
    "MbSpinnerDate2": DataHora,
    "MbBar": BarraNivel,
    "MbStatAsi": EstatisticaASI,
    "MbStatGbe": EstatisticaGbE,
    "MbStatGbeCommon": EstatisticaGbEComum,
    "MbStatSDI": EstatisticaSDI,
    "MbStvLock": TravaSTV,
}


def criar(tipo, var, calls):
    cls = TIPOS.get(tipo)
    if cls is None:
        return None
    return cls(tipo, var, calls)
