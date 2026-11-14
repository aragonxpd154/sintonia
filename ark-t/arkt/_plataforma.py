"""Ajustes de plataforma feitos antes de importar o GTK.

No Windows, o Ark-T roda com um Python e um GTK próprios dentro de
runtime\\ (veja packaging/windows). O lançador Ark-T.exe já monta o
ambiente; isto cobre também quem abre runtime\\python\\python.exe direto
(o .bat de depuração) e garante que as DLLs do GTK sejam achadas pelos
módulos .pyd (o Python 3.8+ não usa o PATH para isso)."""
import os
import sys


def preparar():
    if os.name != "nt":
        return
    # runtime\python\python.exe  ->  runtime\gtk
    runtime = os.path.dirname(os.path.dirname(os.path.abspath(sys.executable)))
    gtk = os.path.join(runtime, "gtk")
    if not os.path.isdir(gtk):
        return                       # GTK instalado de outro jeito (MSYS2, gvsbuild no PATH…)
    binario = os.path.join(gtk, "bin")
    os.environ["PATH"] = binario + os.pathsep + os.environ.get("PATH", "")
    try:
        os.add_dll_directory(binario)
    except (AttributeError, OSError):
        pass
    padroes = {
        "GI_TYPELIB_PATH": os.path.join(gtk, "lib", "girepository-1.0"),
        "XDG_DATA_DIRS": os.path.join(gtk, "share"),
        "GSETTINGS_SCHEMA_DIR": os.path.join(gtk, "share", "glib-2.0", "schemas"),
        "GDK_PIXBUF_MODULEDIR": os.path.join(gtk, "lib", "gdk-pixbuf-2.0", "2.10.0", "loaders"),
    }
    for k, v in padroes.items():
        os.environ.setdefault(k, v)
