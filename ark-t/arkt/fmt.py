"""Formatação de números no padrão brasileiro e utilidades do protocolo."""
import math


def hexn(v, n):
    """Equivalente a Utility.getHex(): os n dígitos hexadecimais menos
    significativos, em minúsculas (complemento de dois para negativos)."""
    v = int(v) & ((1 << (4 * n)) - 1)
    return format(v, "0%dx" % n)


def fmt_num(x, frac=3):
    """1234567.891 -> '1.234.567,891' (até `frac` casas, sem zeros à direita)."""
    if x is None:
        return ""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return str(x)
    if math.isnan(x) or math.isinf(x):
        return "—"
    s = ("{:,.%df}" % frac).format(x)
    if frac > 0:
        s = s.rstrip("0").rstrip(".")
    if s in ("-0", ""):
        s = "0"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def fmt_sci(x):
    """Notação 0.###E0 do Java (limiar de BER)."""
    if x == 0:
        return "0"
    e = int(math.floor(math.log10(abs(x))))
    m = x / 10 ** e
    s = ("%.3f" % m).rstrip("0").rstrip(".").replace(".", ",")
    return "%sE%d" % (s, e)


def parse_num(texto, inteiro=False):
    """Campos inteiros: '4.000.000' ou '4000000'. Campos decimais: '1,5' ou
    '1.5' (com vírgula, pontos são separadores de milhar). '1E-6' também vale."""
    t = str(texto).strip().replace(" ", "").replace(" ", "")
    if not t:
        raise ValueError("vazio")
    if inteiro:
        if "," in t:
            raise ValueError("inteiro com vírgula")
        return int(t.replace(".", ""))
    if "e" in t.lower():
        return float(t.replace(",", "."))
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif t.count(".") > 1:
        raise ValueError("número ambíguo")
    return float(t)
