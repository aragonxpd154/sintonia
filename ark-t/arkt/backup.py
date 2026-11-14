"""Backup da pré-correção: os arquivos exatamente como estão no equipamento,
num .zip com um manifesto (nomes, tamanhos e SHA-256).

Na restauração só voltam os arquivos de pré-correção; .cdef/.dpwr/.apwr
vão junto apenas como referência (mudam canalização e potências)."""
from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile

from . import VERSAO

EXT_PREC = (".dpre", ".apre", ".dlin", ".alin")
EXT_REF = (".cdef", ".dpwr", ".apwr")
MANIFESTO = "manifesto.json"
PASTA_REF = "referencia/"


class ErroBackup(Exception):
    pass


def _sha(d):
    return hashlib.sha256(d).hexdigest()


def escolher(lista):
    """Da lista de arquivos do equipamento: (pré-correção, referência)."""
    prec = [n for n in lista if n.lower().endswith(EXT_PREC)]
    ref = [n for n in lista if n.lower().endswith(EXT_REF)]
    return prec, ref


def montar(prec: dict, ref: dict, info: dict) -> bytes:
    """prec/ref: {nome: bytes}. info: equipamento, endereco…"""
    man = {
        "formato": "arkt-backup-precorrecao",
        "versao": 1,
        "criado": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "programa": "Ark-T %s" % VERSAO,
        **info,
        "arquivos": [{"nome": n, "tamanho": len(d), "sha256": _sha(d)} for n, d in prec.items()],
        "referencia": [{"nome": n, "tamanho": len(d), "sha256": _sha(d)} for n, d in ref.items()],
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(MANIFESTO, json.dumps(man, ensure_ascii=False, indent=2))
        for n, d in prec.items():
            z.writestr(n, d)
        for n, d in ref.items():
            z.writestr(PASTA_REF + n, d)
    return buf.getvalue()


def _nome_ok(n):
    return (0 < len(n) <= 255 and "/" not in n and "\\" not in n and not n.startswith(".")
            and all(32 < ord(c) < 256 for c in n) and n.lower().endswith(EXT_PREC))


def ler(dados: bytes):
    """Valida o .zip e devolve (manifesto, [(nome, bytes)]) só com os
    arquivos de pré-correção. Aceita também um .zip sem manifesto, desde
    que tenha arquivos de pré-correção na raiz."""
    try:
        z = zipfile.ZipFile(io.BytesIO(dados))
    except zipfile.BadZipFile as e:
        raise ErroBackup("o arquivo não é um .zip válido") from e
    with z:
        nomes = z.namelist()
        man = {}
        if MANIFESTO in nomes:
            try:
                man = json.loads(z.read(MANIFESTO).decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as e:
                raise ErroBackup("manifesto ilegível") from e
            entradas = man.get("arquivos", [])
        else:
            entradas = [{"nome": n} for n in nomes if "/" not in n and n.lower().endswith(EXT_PREC)]
        out = []
        for ent in entradas:
            n = ent.get("nome", "")
            if not _nome_ok(n):
                raise ErroBackup("nome de arquivo inválido no backup: %r" % n)
            if n not in nomes:
                raise ErroBackup("o backup não contém %s" % n)
            d = z.read(n)
            if "sha256" in ent and ent["sha256"] != _sha(d):
                raise ErroBackup("%s está corrompido (SHA-256 não confere)" % n)
            if "tamanho" in ent and ent["tamanho"] != len(d):
                raise ErroBackup("%s está com tamanho diferente do manifesto" % n)
            out.append((n, d))
    if not out:
        raise ErroBackup("nenhum arquivo de pré-correção no backup")
    return man, out
