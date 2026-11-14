"""Equipamentos cadastrados e preferências (~/.config/arkt/ no Linux,
%APPDATA%\\Ark-T no Windows)."""
import json
import os

if os.name == "nt":
    PASTA = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Ark-T")
else:
    PASTA = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "arkt")
ARQ = os.path.join(PASTA, "equipamentos.json")


def carregar():
    try:
        with open(ARQ, encoding="utf-8") as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        d = {}
    d.setdefault("equipamentos", [])
    d.setdefault("intervalo", 2.0)
    return d


def salvar(d):
    os.makedirs(PASTA, exist_ok=True)
    tmp = ARQ + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, ARQ)


def lembrar(nome, ip, porta=10001, porta_http=80):
    d = carregar()
    lst = [e for e in d["equipamentos"] if not (e["ip"] == ip and e.get("porta", 10001) == porta)]
    lst.insert(0, {"nome": nome or ip, "ip": ip, "porta": porta, "porta_http": porta_http})
    d["equipamentos"] = lst[:30]
    salvar(d)


def esquecer(ip, porta=10001):
    d = carregar()
    d["equipamentos"] = [e for e in d["equipamentos"] if not (e["ip"] == ip and e.get("porta", 10001) == porta)]
    salvar(d)
