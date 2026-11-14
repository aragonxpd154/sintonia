"""Leitura e escrita do formato de serialização do Java (ObjectOutputStream)
o suficiente para os pontos de controle que o programa original grava junto
das curvas de pré-correção (.dpre/.apre/.dlin/.alin).

Só os tipos que aparecem nesses arquivos: objetos com campos primitivos e de
referência, java.util.Vector, arrays de objetos, Strings e null.
"""
from __future__ import annotations

import struct

MAGIC = 0xACED
VERSAO = 5
TC_NULL, TC_REFERENCE, TC_CLASSDESC, TC_OBJECT, TC_STRING, TC_ARRAY = 0x70, 0x71, 0x72, 0x73, 0x74, 0x75
TC_BLOCKDATA, TC_ENDBLOCKDATA, TC_LONGSTRING, TC_BLOCKDATALONG = 0x77, 0x78, 0x7C, 0x7A
BASE = 0x7E0000
SC_WRITE_METHOD, SC_SERIALIZABLE = 0x01, 0x02

PRIM = {"B": ">b", "C": ">H", "D": ">d", "F": ">f", "I": ">i", "J": ">q", "S": ">h", "Z": ">?"}


class ErroSerializacao(Exception):
    pass


class Classe:
    def __init__(self, nome, suid, flags, campos, super_=None):
        self.nome = nome
        self.suid = suid
        self.flags = flags
        self.campos = campos        # [(tipo, nome, tipo_classe)]
        self.super = super_


class Objeto:
    """Instância lida: `classe` (nome) e `campos` (dict). Vector vira lista."""

    def __init__(self, classe, campos=None):
        self.classe = classe
        self.campos = campos or {}

    def __getitem__(self, k):
        return self.campos[k]

    def get(self, k, padrao=None):
        return self.campos.get(k, padrao)

    def __repr__(self):
        return "<%s %r>" % (self.classe.rsplit(".", 1)[-1], self.campos)


# =================================================================== leitura
class Leitor:
    def __init__(self, dados: bytes):
        self.d = dados
        self.p = 0
        self.refs = []

    def _ler(self, n):
        if self.p + n > len(self.d):
            raise ErroSerializacao("fim inesperado dos dados")
        b = self.d[self.p:self.p + n]
        self.p += n
        return b

    def u8(self):
        return self._ler(1)[0]

    def fmt(self, f):
        return struct.unpack(f, self._ler(struct.calcsize(f)))[0]

    def utf(self):
        n = self.fmt(">H")
        return self._ler(n).decode("utf-8", "replace")

    def ler(self):
        if self.fmt(">H") != MAGIC or self.fmt(">H") != VERSAO:
            raise ErroSerializacao("não é um fluxo de serialização Java")
        return self.conteudo()

    def conteudo(self):
        tc = self.u8()
        if tc == TC_NULL:
            return None
        if tc == TC_REFERENCE:
            h = self.fmt(">i") - BASE
            return self.refs[h]
        if tc == TC_STRING:
            s = self.utf()
            self.refs.append(s)
            return s
        if tc == TC_LONGSTRING:
            n = self.fmt(">q")
            s = self._ler(n).decode("utf-8", "replace")
            self.refs.append(s)
            return s
        if tc == TC_OBJECT:
            return self.objeto()
        if tc == TC_ARRAY:
            return self.array()
        if tc == TC_CLASSDESC:
            self.p -= 1
            return self.descricao()
        raise ErroSerializacao("código 0x%02x não suportado na posição %d" % (tc, self.p - 1))

    def descricao(self):
        tc = self.u8()
        if tc == TC_NULL:
            return None
        if tc == TC_REFERENCE:
            return self.refs[self.fmt(">i") - BASE]
        if tc != TC_CLASSDESC:
            raise ErroSerializacao("esperava descrição de classe (0x%02x)" % tc)
        nome = self.utf()
        suid = self.fmt(">q")
        cls = Classe(nome, suid, 0, [])
        self.refs.append(cls)
        cls.flags = self.u8()
        n = self.fmt(">H")
        for _ in range(n):
            t = chr(self.u8())
            nm = self.utf()
            tcls = self.conteudo() if t in "L[" else None
            cls.campos.append((t, nm, tcls))
        self._anotacoes()
        cls.super = self.descricao()
        return cls

    def _anotacoes(self):
        while True:
            tc = self.u8()
            if tc == TC_ENDBLOCKDATA:
                return
            if tc == TC_BLOCKDATA:
                self._ler(self.u8())
            elif tc == TC_BLOCKDATALONG:
                self._ler(self.fmt(">i"))
            else:
                self.p -= 1
                self.conteudo()

    def objeto(self):
        cls = self.descricao()
        obj = Objeto(cls.nome)
        self.refs.append(obj)
        cadeia = []
        c = cls
        while c is not None:
            cadeia.insert(0, c)
            c = c.super
        for c in cadeia:
            for t, nm, _ in c.campos:
                obj.campos[nm] = self.fmt(PRIM[t]) if t in PRIM else self.conteudo()
            if c.flags & SC_WRITE_METHOD:
                self._anotacoes()
        if cls.nome == "java.util.Vector":
            n = obj.campos.get("elementCount", 0)
            dados = obj.campos.get("elementData") or []
            lista = Vetor(dados[:n])
            # troca a referência para a lista (outros objetos podem apontar)
            self.refs[self.refs.index(obj)] = lista
            return lista
        return obj

    def array(self):
        cls = self.descricao()
        n = self.fmt(">i")
        lista = []
        self.refs.append(lista)
        tipo = cls.nome[1:2]
        for _ in range(n):
            lista.append(self.fmt(PRIM[tipo]) if tipo in PRIM else self.conteudo())
        return lista


class Vetor(list):
    """java.util.Vector."""


def ler(dados: bytes):
    return Leitor(dados).ler()


# =================================================================== escrita
VECTOR = Classe("java.util.Vector", -2767605614048989439, SC_SERIALIZABLE | SC_WRITE_METHOD,
                [("I", "capacityIncrement", None), ("I", "elementCount", None),
                 ("[", "elementData", "[Ljava/lang/Object;")])
ARRAY_OBJ = Classe("[Ljava.lang.Object;", -8012369246846506644, SC_SERIALIZABLE, [])


class Escritor:
    def __init__(self):
        self.out = bytearray()
        self.handles = {}
        self.prox = 0

    def _h(self, chave):
        self.handles[chave] = self.prox
        self.prox += 1

    def w(self, f, v):
        self.out += struct.pack(f, v)

    def utf(self, s):
        b = s.encode("utf-8")
        self.w(">H", len(b))
        self.out += b

    def string(self, s):
        chave = ("str", s)
        if chave in self.handles:
            self.out.append(TC_REFERENCE)
            self.w(">i", BASE + self.handles[chave])
            return
        self.out.append(TC_STRING)
        self._h(chave)
        self.utf(s)

    def descricao(self, cls: Classe):
        chave = ("cls", cls.nome)
        if chave in self.handles:
            self.out.append(TC_REFERENCE)
            self.w(">i", BASE + self.handles[chave])
            return
        self.out.append(TC_CLASSDESC)
        self.utf(cls.nome)
        self.w(">q", cls.suid)
        self._h(chave)
        self.out.append(cls.flags)
        self.w(">H", len(cls.campos))
        for t, nm, tcls in cls.campos:
            self.out.append(ord(t))
            self.utf(nm)
            if t in "L[":
                self.string(tcls)
        self.out.append(TC_ENDBLOCKDATA)
        if cls.super is None:
            self.out.append(TC_NULL)
        else:
            self.descricao(cls.super)

    def valor(self, v):
        if v is None:
            self.out.append(TC_NULL)
        elif isinstance(v, str):
            self.string(v)
        elif isinstance(v, Vetor):
            self.vetor(v)
        elif isinstance(v, (list, tuple)):
            self.array(v)
        elif isinstance(v, NovoObjeto):
            self.objeto(v)
        else:
            raise ErroSerializacao("tipo não suportado: %r" % (v,))

    def vetor(self, itens):
        self.out.append(TC_OBJECT)
        self.descricao(VECTOR)
        self._h(("obj", id(itens)))
        cap = max(10, len(itens))
        self.w(">i", 0)            # capacityIncrement
        self.w(">i", len(itens))   # elementCount
        self.array(list(itens) + [None] * (cap - len(itens)))
        self.out.append(TC_ENDBLOCKDATA)

    def array(self, itens):
        self.out.append(TC_ARRAY)
        self.descricao(ARRAY_OBJ)
        self._h(("arr", id(itens)))
        self.w(">i", len(itens))
        for x in itens:
            self.valor(x)

    def objeto(self, o):
        self.out.append(TC_OBJECT)
        self.descricao(o.cls)
        self._h(("obj", id(o)))
        for t, nm, _ in o.cls.campos:
            v = o.valores[nm]
            if t in PRIM:
                self.w(PRIM[t], v)
            else:
                self.valor(v)


class NovoObjeto:
    def __init__(self, cls: Classe, **valores):
        self.cls = cls
        self.valores = valores


def escrever(obj) -> bytes:
    e = Escritor()
    e.w(">H", MAGIC)
    e.w(">H", VERSAO)
    e.valor(obj)
    return bytes(e.out)
