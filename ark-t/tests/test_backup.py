"""Backup da pré-correção (.zip com manifesto)."""
import io
import json
import os
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arkt import backup as B  # noqa: E402


class Backup(unittest.TestCase):
    PREC = {"CANAL28.dpre": b"\x00\x01curvas", "LIN.dlin": b"\x00\x60" + bytes(768)}
    REF = {"canais.cdef": b"0;\n1;0\n"}

    def test_escolher(self):
        p, r = B.escolher(["a.def", "x.dpre", "y.apre", "z.dlin", "c.cdef", "p.dpwr", "cfg.sav"])
        self.assertEqual(p, ["x.dpre", "y.apre", "z.dlin"])
        self.assertEqual(r, ["c.cdef", "p.dpwr"])

    def test_ida_e_volta(self):
        z = B.montar(self.PREC, self.REF, {"equipamento": "Teste"})
        man, arqs = B.ler(z)
        self.assertEqual(dict(arqs), self.PREC)                       # referência não volta
        self.assertEqual(man["equipamento"], "Teste")
        with zipfile.ZipFile(io.BytesIO(z)) as zz:
            self.assertIn("referencia/canais.cdef", zz.namelist())

    def test_corrompido(self):
        z = B.montar(self.PREC, {}, {})
        buf = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(z)) as a, zipfile.ZipFile(buf, "w") as b:
            for n in a.namelist():
                d = a.read(n)
                b.writestr(n, d + b"!" if n == "LIN.dlin" else d)
        with self.assertRaises(B.ErroBackup):
            B.ler(buf.getvalue())

    def test_nome_perigoso(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(B.MANIFESTO, json.dumps({"arquivos": [{"nome": "../../etc/x.dpre"}]}))
            z.writestr("../../etc/x.dpre", b"x")
        with self.assertRaises(B.ErroBackup):
            B.ler(buf.getvalue())

    def test_sem_manifesto(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("A.dpre", b"abc")
        _man, arqs = B.ler(buf.getvalue())
        self.assertEqual(arqs, [("A.dpre", b"abc")])

    def test_nao_zip(self):
        with self.assertRaises(B.ErroBackup):
            B.ler(b"isto nao e zip")


if __name__ == "__main__":
    unittest.main()
