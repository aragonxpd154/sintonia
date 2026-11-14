"""Ponto de entrada: `arkt`, `arkt 192.168.1.50`, `arkt simulador`, `arkt importar-jar`."""
import argparse
import sys

from . import VERSAO
from ._plataforma import preparar

preparar()


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("importar-jar", "importar"):
        p = argparse.ArgumentParser(prog="arkt importar-jar",
                                    description="Importa as telas do programa original (ARK-T Installer Utility .jar)")
        p.add_argument("jar", help="arquivo .jar do ARK-T Installer Utility (ex.: arkT_v5_5s.jar)")
        a = p.parse_args(argv[1:])
        from . import jar
        try:
            with open(a.jar, "rb") as fh:
                destino = jar.importar(fh.read(), a.jar)
        except (OSError, jar.ErroJar, ValueError) as e:
            print("erro:", e, file=sys.stderr)
            return 1
        print("telas importadas em", destino)
        return 0
    if argv and argv[0] in ("simulador", "simulator"):
        p = argparse.ArgumentParser(prog="arkt simulador", description="Simula um excitador ARK-T (ISDB-T ou DVB-T)")
        p.add_argument("--porta", type=int, default=10001, help="porta TCP de comandos (padrão 10001)")
        p.add_argument("--http", type=int, default=8080, help="porta HTTP dos arquivos (padrão 8080)")
        p.add_argument("--prec", type=int, default=None,
                       help="porta da pré-correção (padrão 5000 com --porta 10001, senão porta+1)")
        p.add_argument("--endereco", default="127.0.0.1", help="interface (use 0.0.0.0 para a rede)")
        p.add_argument("--dvbt", action="store_true", help="simula um ARK-T DVB-T em vez de ISDB-T")
        p.add_argument("--jar", help="publica este .jar na lista de arquivos, como o equipamento real")
        a = p.parse_args(argv[1:])
        from . import simulador
        if a.dvbt:
            simulador.usar_dvbt()
        if a.jar:
            simulador.publicar_jar(a.jar)
        rodar = simulador.rodar
        rodar(a.porta, a.http, a.endereco, porta_prec=a.prec)
        return 0
    p = argparse.ArgumentParser(prog="arkt", description="Gerência dos excitadores ARK-T sem Java")
    p.add_argument("ip", nargs="?", help="conecta direto neste IP")
    p.add_argument("--porta", type=int, default=10001, help="porta TCP de comandos")
    p.add_argument("--http", type=int, default=80, help="porta HTTP dos arquivos do equipamento")
    p.add_argument("--prec", type=int, default=5000, help="porta da pré-correção (padrão 5000)")
    p.add_argument("--nome", default=None, help="nome para exibir")
    p.add_argument("--versao", action="store_true", help="mostra a versão")
    a = p.parse_args(argv)
    if a.versao:
        print("Ark-T", VERSAO)
        return 0
    from .ui.app import rodar
    alvo = (a.nome, a.ip, a.porta, a.http, a.prec) if a.ip else None
    return rodar(alvo)


if __name__ == "__main__":
    sys.exit(main())
