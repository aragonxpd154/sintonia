"""Protocolo da porta 10001 e arquivos, contra o simulador."""
import os
import socket
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arkt import arquivos, eventos, protocolo, simulador  # noqa: E402


def _porta():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Protocolo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p, cls.h = _porta(), _porta()
        cls.eq, cls.tcp, cls.web = simulador.rodar(cls.p, cls.h, em_thread=True, porta_prec=_porta())
        time.sleep(0.2)

    def test_status_e_lista(self):
        with protocolo.Conexao("127.0.0.1", self.p) as c:
            st = c.status()
            lista = arquivos.lista_de_arquivos(c.pergunta("yh\n\r"))
            sobre = protocolo.ler_sobre(c.pergunta("\xa7\r\n"))
        self.assertEqual(len(st), 1405)
        self.assertTrue(arquivos.procurar(lista, ".def"))
        self.assertTrue(arquivos.procurar(lista, ".cdef"))
        self.assertIn("fpga", sobre)

    def test_arquivos_http(self):
        with protocolo.Conexao("127.0.0.1", self.p) as c:
            lista = arquivos.lista_de_arquivos(c.pergunta("yh\n\r"))
        d = arquivos.DefinicaoSistema.ler(
            protocolo.baixar_http("127.0.0.1", arquivos.procurar(lista, ".def"), self.h).decode("latin-1"))
        self.assertEqual(d.familia, "isdbt")
        t = arquivos.TabelaCanais.ler(
            protocolo.baixar_http("127.0.0.1", arquivos.procurar(lista, ".cdef"), self.h).decode("latin-1"))
        self.assertGreater(len(t.saida), 10)
        self.assertEqual(len(t.indices), len(t.saida))
        passos = arquivos.passos_potencia(
            protocolo.baixar_http("127.0.0.1", arquivos.procurar(lista, ".dpwr"), self.h))
        self.assertEqual(passos, sorted(passos))

    def test_escrita_8_bits(self):
        with protocolo.Conexao("127.0.0.1", self.p) as c:
            c.pergunta("w23105\n\r")
            st = c.status()
        self.assertEqual(st[521 + 0x31], 5)

    def test_eventos(self):
        with protocolo.Conexao("127.0.0.1", self.p) as c:
            st = c.status()
        n, cheia, maximo = eventos.contagem(st)
        self.assertGreaterEqual(n, 0)
        self.assertGreater(maximo, 0)


if __name__ == "__main__":
    unittest.main()
