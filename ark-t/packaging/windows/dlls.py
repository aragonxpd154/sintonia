#!/usr/bin/env python3
"""Copia para o pacote só as DLLs do GTK que o Ark-T usa: o fecho de
dependências (tabela de importação PE) a partir das bibliotecas citadas
nas typelibs, dos módulos .pyd e dos carregadores do gdk-pixbuf.

Uso: dlls.py <bin de origem> <bin de destino> <typelibs> <site-packages> <pasta gdk-pixbuf>
"""
import os
import re
import shutil
import struct
import sys

ORIGEM, DESTINO, TYPELIBS, SITE, PIXBUF = sys.argv[1:6]
SOBRAM = ("GtkSource-", "DBus", "xlib-", "xft-", "xfixes-", "xrandr-", "DBusGLib", "Rsvg-", "libxml2-")


def importacoes(caminho):
    """Nomes das DLLs importadas por um PE (import + delay-import)."""
    with open(caminho, "rb") as fh:
        d = fh.read()
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    if d[pe:pe + 4] != b"PE\0\0":
        return []
    n_sec = struct.unpack_from("<H", d, pe + 6)[0]
    opt_tam = struct.unpack_from("<H", d, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", d, opt)[0]
    dirs = opt + (112 if magic == 0x20B else 96)
    secoes = []
    s0 = opt + opt_tam
    for i in range(n_sec):
        va, tam, raw = struct.unpack_from("<III", d, s0 + i * 40 + 12)
        vs = struct.unpack_from("<I", d, s0 + i * 40 + 8)[0]
        secoes.append((va, max(vs, tam), raw))

    def off(rva):
        for va, tam, raw in secoes:
            if va <= rva < va + tam:
                return rva - va + raw
        return None

    def cstr(o):
        return d[o:d.index(b"\0", o)].decode("latin-1")

    nomes = []
    imp_rva = struct.unpack_from("<I", d, dirs + 8)[0]
    o = off(imp_rva) if imp_rva else None
    while o is not None:
        nome_rva = struct.unpack_from("<I", d, o + 12)[0]
        if nome_rva == 0:
            break
        nomes.append(cstr(off(nome_rva)))
        o += 20
    dly_rva = struct.unpack_from("<I", d, dirs + 13 * 8)[0]
    o = off(dly_rva) if dly_rva else None
    while o is not None:
        nome_rva = struct.unpack_from("<I", d, o + 4)[0]
        if nome_rva == 0:
            break
        x = off(nome_rva)
        if x is not None:
            nomes.append(cstr(x))
        o += 32
    return nomes


disponiveis = {f.lower(): f for f in os.listdir(ORIGEM) if f.lower().endswith(".dll")}

for f in os.listdir(TYPELIBS):
    if f.startswith(SOBRAM):
        os.remove(os.path.join(TYPELIBS, f))

raizes = set()
for f in os.listdir(TYPELIBS):
    with open(os.path.join(TYPELIBS, f), "rb") as fh:
        for m in re.findall(rb"[A-Za-z0-9_.+-]+\.dll", fh.read()):
            raizes.add(m.decode().lower())
pes = []
for base in (SITE, PIXBUF):
    for dp, _, fs in os.walk(base):
        pes += [os.path.join(dp, f) for f in fs if f.lower().endswith((".pyd", ".dll"))]
for p in pes:
    raizes.update(n.lower() for n in importacoes(p))

copiadas, fila, faltando = set(), [r for r in raizes if r in disponiveis], set()
while fila:
    n = fila.pop()
    if n in copiadas:
        continue
    copiadas.add(n)
    src = os.path.join(ORIGEM, disponiveis[n])
    shutil.copy2(src, os.path.join(DESTINO, disponiveis[n]))
    for dep in importacoes(src):
        k = dep.lower()
        if k in disponiveis:
            fila.append(k)
        elif not k.startswith(("api-ms-", "ext-ms-")):
            faltando.add(k)

total = sum(os.path.getsize(os.path.join(DESTINO, disponiveis[n])) for n in copiadas)
print("  %d DLLs (%.1f MB) de %d" % (len(copiadas), total / 1e6, len(disponiveis)))
print("  importadas do sistema/Python:", ", ".join(sorted(faltando)))
