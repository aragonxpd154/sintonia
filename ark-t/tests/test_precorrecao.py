"""Pré-correção: curvas, arquivos e a sessão na porta 5000 (contra o simulador).
Nada aqui usa arquivos do fabricante."""
import os
import socket
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arkt import campos as C  # noqa: E402
from arkt import javaser  # noqa: E402
from arkt import precorrecao as P  # noqa: E402
from arkt import protocolo, simulador  # noqa: E402


def _porta():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Curvas(unittest.TestCase):
    def test_padrao_e_conversoes(self):
        am = P.Curva(P.AM)
        pts = am.pontos()
        self.assertEqual(len(pts), P.AM.resolucao)
        self.assertEqual(P.equipamento_para_am(P.am_para_equipamento(pts)), pts)
        pm = P.Curva(P.PM, [[0, 32767], [500, 30000], [1023, 33000]], P.POLINOMIAL).pontos()
        self.assertEqual(P.equipamento_para_pm(P.pm_para_equipamento(pm)), pm)

    def test_interpolacao_linear_passa_pelos_pontos(self):
        c = P.Curva(P.AM, [[0, 3000], [200, 1000], [511, 4000]], P.LINEAR)
        pts = c.pontos()
        # o original (e esta cópia, bit a bit) suaviza levemente as pontas
        for x, y in ((0, 3000), (200, 1000), (511, 4000), (100, 2000)):
            self.assertLessEqual(abs(pts[x] - y), 15, (x, pts[x]))
        self.assertTrue(all(pts[i] >= pts[i + 1] for i in range(5, 195)))

    def test_unidades(self):
        self.assertAlmostEqual(P.y_para_db(4095), 0.0)
        self.assertAlmostEqual(P.y_para_db(3095), 1.0)
        self.assertAlmostEqual(P.y_para_ns(89999), 0.0)
        self.assertAlmostEqual(P.x_para_mhz(0), -P.x_para_mhz(2047), places=2)


class Arquivos(unittest.TestCase):
    def test_pre_ida_e_volta(self):
        a = P.ArquivoPre(5, 3)
        c = P.Curva(P.AM, [[0, 2559], [300, 2320], [511, 1780]], P.LINEAR)
        a.am[1][2] = c
        a.definir_curva(1, 2, True, P.am_para_equipamento(c.pontos()))
        dados = a.bytes_completo("TESTE.dpre")
        b = P.ArquivoPre.ler(dados, "TESTE.dpre")
        self.assertEqual((b.n_pot, b.n_can), (5, 3))
        self.assertEqual(b.am[1][2].controles, c.controles)
        self.assertEqual(list(b.curva_gravada(1, 2, True)), list(P.am_para_equipamento(c.pontos())))
        self.assertEqual(b.bytes_completo("TESTE.dpre"), dados)

    def test_ajustar_canais(self):
        a = P.ArquivoPre(4, 2)
        a.ajustar_canais(5)
        self.assertEqual(a.n_can, 5)
        b = P.ArquivoPre.ler(a.bytes_completo("X.dpre"), "X.dpre")
        self.assertEqual(b.n_can, 5)

    def test_linear_ida_e_volta(self):
        lin = P.ArquivoLinear()
        lin.modulo = P.Curva(P.MODULO, [[0, 3000], [1024, 1500], [2047, 3000]])
        dados = lin.bytes_completo("L.ldknb")
        self.assertEqual(dados[:2], b"\x00\x60")
        self.assertEqual(dados[2:770], lin.calcular())
        b = P.ArquivoLinear.ler(dados, "L.dlin")
        self.assertEqual(b.modulo.controles, lin.modulo.controles)

    def test_resposta_dos_coeficientes(self):
        mod = P.Curva(P.MODULO, [[0, 3000], [1024, 1500], [2047, 3000]]).pontos()
        fas = P.Curva(P.FASE, [[0, 95000], [1024, 89999], [2047, 95000]]).pontos()
        m, f = P.resposta_no_editor(P.coeficientes_lineares(mod, fas).hex(), mod)
        faixa = range(200, 1848)
        self.assertLess(max(abs(m[i] - mod[i]) for i in faixa), 40)       # 0,04 dB
        self.assertLess(max(abs(f[i] - fas[i]) for i in faixa), 800)      # 8 ns

    def test_serializacao_java(self):
        a = P.ArquivoPre(3, 2)
        o = javaser.ler(javaser.escrever(a.objeto_knb("Y.dpre")))
        self.assertEqual(o.get("fileName"), "Y.dpre")


class CanalPotencia(unittest.TestCase):
    PASSOS = [300, 330, 360, 400, 430]

    def test_itens_standalone(self):
        itens = P.itens_potencia(self.PASSOS, True)
        self.assertEqual(len(itens), 4)
        self.assertEqual(itens[0], ("30.0 a 33.0 dBm", "op14a\n\r", 5000))
        self.assertEqual(itens[1][0], "33.1 a 36.0 dBm")

    def test_itens_driver(self):
        itens = P.itens_potencia(self.PASSOS, False)
        self.assertEqual(itens[-1], ("Curva plana", "w229ff\n\r", 10001))
        self.assertEqual(itens[0][1], "w22900\n\r")

    def test_status(self):
        st = bytearray(1405)
        st[532], st[533] = 0x01, 0x68         # 360
        self.assertEqual(P.potencia_no_status(st, self.PASSOS, True), 1)
        st[562] = 255
        self.assertEqual(P.potencia_no_status(st, self.PASSOS, False), 4)
        st[523] = 30
        self.assertEqual(P.canal_no_status(st, [28, 29, 30]), 2)


class Sessao(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p, cls.h, cls.p5 = _porta(), _porta(), _porta()
        cls.eq, cls.tcp, cls.web = simulador.rodar(cls.p, cls.h, em_thread=True, porta_prec=cls.p5)
        time.sleep(0.2)

    def login(self, u, s):
        with protocolo.Conexao("127.0.0.1", self.p) as c:
            return c.comando(C.Cmd(P.cmd_login(u, s), 4))

    def test_login(self):
        self.assertEqual(self.login("admin", "errada")[3:4], b"n")
        self.assertEqual(self.login("admin", "admin")[3:4], b"y")

    def test_sessao_completa(self):
        s = P.Sessao5000("127.0.0.1", self.p5)
        s.abrir()
        try:
            time.sleep(0.1)
            self.assertTrue(self.eq.st[731] & 1, "porta 5000 deveria aparecer ocupada")
            pts = P.Curva(P.AM, [[0, 2559], [256, 1500], [511, 1780]]).pontos()
            s.enviar_am(pts)
            rec = self.eq.curvas["p0"]
            self.assertEqual([(rec[2 * i] << 8) | rec[2 * i + 1] for i in range(512)], P.am_para_equipamento(pts))
            coef = P.ArquivoLinear().calcular()
            s.enviar_linear(coef)
            self.assertTrue(s.ler_coeficientes().startswith(coef.hex()))
            dados = P.ArquivoPre(5, 3).bytes_completo("UNIT.dpre")
            s.enviar_arquivo("UNIT.dpre", dados)
            self.assertEqual(simulador.ARQUIVOS.get("UNIT.dpre"), dados)
        finally:
            s.fechar()
        time.sleep(0.2)
        self.assertFalse(self.eq.st[731] & 1, "porta 5000 deveria estar livre")

    def test_trabalhador_coalesce(self):
        import threading
        t = P.Trabalhador5000("127.0.0.1", self.p5)
        segura = threading.Event()
        t.executar(lambda s: segura.wait(5))          # ocupa a fila enquanto "arrasta"
        enviados = []
        ultimo = None
        for k in range(30):
            pts = P.Curva(P.AM, [[0, 2000 + 20 * k], [511, 2000]]).pontos()
            ultimo = pts
            t.coalescer("am", lambda s, p=pts, k=k: (s.enviar_am(p), enviados.append(k)))
        fim = []
        t.executar(lambda s: fim.append(True))
        segura.set()
        for _ in range(100):
            if fim:
                break
            time.sleep(0.05)
        t.fechar()
        self.assertTrue(fim)
        self.assertEqual(enviados[-1], 29)            # a última versão sempre vai
        self.assertEqual(enviados, [29])              # e as intermediárias são puladas
        rec = self.eq.curvas["p0"]
        self.assertEqual((rec[0] << 8) | rec[1], P.am_para_equipamento(ultimo)[0])


if __name__ == "__main__":
    unittest.main()
