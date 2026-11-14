"""Importação das telas a partir do .jar — com uma classe Java sintética,
montada aqui byte a byte (nada do fabricante)."""
import io
import os
import struct
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arkt import jar  # noqa: E402


class Montador:
    """Assembler mínimo de .class (só o que o teste precisa)."""

    def __init__(self):
        self.cp = [None]
        self.idx = {}

    def _add(self, chave, dados):
        if chave in self.idx:
            return self.idx[chave]
        self.cp.append(dados)
        self.idx[chave] = len(self.cp) - 1
        if chave[0] in ("float",):
            pass
        return self.idx[chave]

    def utf8(self, s):
        b = s.encode("utf-8")
        return self._add(("utf8", s), b"\x01" + struct.pack(">H", len(b)) + b)

    def classe(self, nome):
        return self._add(("class", nome), b"\x07" + struct.pack(">H", self.utf8(nome)))

    def string(self, s):
        return self._add(("str", s), b"\x08" + struct.pack(">H", self.utf8(s)))

    def float_(self, v):
        return self._add(("float", v), b"\x04" + struct.pack(">f", v))

    def nat(self, nome, desc):
        return self._add(("nat", nome, desc), b"\x0c" + struct.pack(">HH", self.utf8(nome), self.utf8(desc)))

    def campo(self, cls, nome, desc):
        return self._add(("f", cls, nome, desc), b"\x09" + struct.pack(">HH", self.classe(cls), self.nat(nome, desc)))

    def metodo(self, cls, nome, desc):
        return self._add(("m", cls, nome, desc), b"\x0a" + struct.pack(">HH", self.classe(cls), self.nat(nome, desc)))

    def montar(self, nome, super_, campos, metodos):
        this, sup = self.classe(nome), self.classe(super_)
        f_bytes = b"".join(struct.pack(">HHHH", 2, self.utf8(n), self.utf8(d), 0) for n, d in campos)
        m_bytes = b""
        code_nome = self.utf8("Code")
        for n, d, codigo in metodos:
            attr = struct.pack(">HHI", 20, 10, len(codigo)) + codigo + struct.pack(">HH", 0, 0)
            m_bytes += struct.pack(">HHHH", 1, self.utf8(n), self.utf8(d), 1)
            m_bytes += struct.pack(">HI", code_nome, len(attr)) + attr
        cp = b"".join(self.cp[1:])
        return (struct.pack(">IHHH", 0xCAFEBABE, 0, 50, len(self.cp)) + cp +
                struct.pack(">HHHH", 0x21, this, sup, 0) +
                struct.pack(">H", len(campos)) + f_bytes + struct.pack(">H", len(metodos)) + m_bytes +
                struct.pack(">H", 0))


def _painel_sintetico():
    m = Montador()
    P = "mbinternational/panels/MbPanOutputIsdbt"
    W = "mb/widgets/MbTextField"
    L = "javax/swing/GroupLayout"
    PG = "javax/swing/GroupLayout$ParallelGroup"
    f = m.campo(P, "txtFreq", "L%s;" % W)
    c = bytearray()

    def u2(v):
        return struct.pack(">H", v)
    # this.txtFreq = new MbTextField();
    c += b"\x2a" + b"\xbb" + u2(m.classe(W)) + b"\x59" + b"\xb7" + u2(m.metodo(W, "<init>", "()V")) + b"\xb5" + u2(f)
    # this.txtFreq.setIndex(747);
    c += b"\x2a\xb4" + u2(f) + b"\x11" + struct.pack(">h", 747) + b"\xb6" + u2(m.metodo(W, "setIndex", "(I)V"))
    # this.txtFreq.setTitle(Bundle.getString("TITULO_FREQ"));
    c += b"\x2a\xb4" + u2(f) + b"\x13" + u2(m.string("TITULO_FREQ"))
    c += b"\xb8" + u2(m.metodo("mb/messages/Bundle", "getString", "(Ljava/lang/String;)Ljava/lang/String;"))
    c += b"\xb6" + u2(m.metodo(W, "setTitle", "(Ljava/lang/String;)V"))
    # this.txtFreq.set16bitRegister(true);
    c += b"\x2a\xb4" + u2(f) + b"\x04" + b"\xb6" + u2(m.metodo(W, "set16bitRegister", "(Z)V"))
    # this.txtFreq.setXFactor(0.1f);
    c += b"\x2a\xb4" + u2(f) + b"\x13" + u2(m.float_(0.1)) + b"\xb6" + u2(m.metodo(W, "setXFactor", "(F)V"))
    # this.txtFreq.setItems(new String[]{"A", "B"});
    c += b"\x2a\xb4" + u2(f) + b"\x05" + b"\xbd" + u2(m.classe("java/lang/String"))
    c += b"\x59\x03\x13" + u2(m.string("A")) + b"\x53"
    c += b"\x59\x04\x13" + u2(m.string("B")) + b"\x53"
    c += b"\xb6" + u2(m.metodo(W, "setItems", "([Ljava/lang/String;)V"))
    # GroupLayout l = new GroupLayout(this); l.setVerticalGroup(l.createParallelGroup().addComponent(this.txtFreq));
    c += b"\xbb" + u2(m.classe(L)) + b"\x59\x2a" + b"\xb7" + u2(m.metodo(L, "<init>", "(Ljava/awt/Container;)V"))
    c += b"\x4c"                                                            # astore_1
    c += b"\x2b\x2b" + b"\xb6" + u2(m.metodo(L, "createParallelGroup", "()L%s;" % PG))
    c += b"\x2a\xb4" + u2(f) + b"\xb6" + u2(m.metodo(PG, "addComponent", "(Ljava/awt/Component;)L%s;" % PG))
    c += b"\xb6" + u2(m.metodo(L, "setVerticalGroup", "(Ljavax/swing/GroupLayout$Group;)V"))
    c += b"\xb1"                                                            # return
    init = b"\x2a\xb7" + u2(m.metodo("javax/swing/JPanel", "<init>", "()V"))
    init += b"\x2a\xb7" + u2(m.metodo(P, "initComponents", "()V")) + b"\xb1"
    return m.montar(P, "javax/swing/JPanel", [("txtFreq", "L%s;" % W)],
                    [("<init>", "()V", init), ("initComponents", "()V", bytes(c))])


def _jar():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mbinternational/panels/MbPanOutputIsdbt.class", _painel_sintetico())
        z.writestr("mb/messages/Bundle.properties", "TITULO_FREQ=Frequency Out [Hz]\nTITLE_ROW_ISDBT=A,B\n")
    return buf.getvalue()


class ImportarJar(unittest.TestCase):
    def test_extrair(self):
        spec = jar.extrair(_jar())
        arvore = spec["panels"]["MbPanOutputIsdbt"]["tree"]
        self.assertEqual(arvore, [{
            "kind": "widget", "type": "MbTextField", "var": "txtFreq",
            "calls": [["index", 747], ["title", "Frequency Out [Hz]"], ["16bitRegister", True],
                      ["xFactor", 0.1], ["items", ["A", "B"]]]}])
        self.assertEqual(spec["bundle"], {"TITLE_ROW_ISDBT": "A,B"})

    def test_jar_embrulhado(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("app.jar", _jar())
        self.assertIn("MbPanOutputIsdbt", jar.extrair(buf.getvalue())["panels"])

    def test_nao_e_o_programa(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("outra/Coisa.class", b"\xca\xfe\xba\xbe")
        with self.assertRaises(jar.ErroJar):
            jar.extrair(buf.getvalue())
        with self.assertRaises(jar.ErroJar):
            jar.extrair(b"nada")

    def test_importar_grava_na_pasta_do_usuario(self):
        with tempfile.TemporaryDirectory() as d:
            antigo = os.environ.get("XDG_DATA_HOME"), os.environ.get("APPDATA")
            os.environ["XDG_DATA_HOME"] = os.environ["APPDATA"] = d
            try:
                destino = jar.importar(_jar(), "teste")
                self.assertTrue(destino.startswith(d))
                self.assertTrue(os.path.isfile(destino))
            finally:
                for k, v in zip(("XDG_DATA_HOME", "APPDATA"), antigo):
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

    def test_float32_como_no_codigo_fonte(self):
        f = struct.unpack(">f", struct.pack(">f", 0.1))[0]
        self.assertEqual(jar._float32(f), 0.1)
        self.assertEqual(jar._args_desc("(IZLjava/lang/String;[J)V"), (["I", "Z", "Ljava/lang/String;", "[J"], "V"))


if __name__ == "__main__":
    unittest.main()
