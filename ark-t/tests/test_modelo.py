"""Telas completas (precisa das telas importadas do .jar original; sem elas
o teste é pulado — o repositório não traz nada do fabricante)."""
import os
import subprocess
import sys
import unittest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from arkt import jar  # noqa: E402


@unittest.skipUnless(jar.disponivel(), "telas do programa original não importadas (arkt importar-jar)")
class TelasCompletas(unittest.TestCase):
    def rodar(self, script):
        r = subprocess.run([sys.executable, os.path.join(RAIZ, "tests", "roteiros", script)],
                           cwd=RAIZ, capture_output=True, text=True, timeout=120)
        return r.stdout + r.stderr

    def test_todos_os_campos_leem_o_status(self):
        out = self.rodar("teste_motor.py")
        self.assertIn("ERROS: 0", out, out[-2000:])

    def test_escrita_de_cada_tipo_de_campo(self):
        out = self.rodar("teste_escrita.py")
        self.assertIn("falhas: 0", out, out[-2000:])


if __name__ == "__main__":
    unittest.main()
