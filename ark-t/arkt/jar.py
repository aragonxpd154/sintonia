"""Importa as telas do programa original (o .jar do ARK-T Installer Utility).

O Ark-T não traz nada do fabricante: a descrição das telas (que campo fica
em que posição do status, máscaras, comandos, títulos) é lida do próprio
.jar — que o equipamento publica na lista de arquivos — e gravada na pasta
de dados do usuário.

O código das telas foi gerado pelo editor visual do NetBeans, então o
construtor e o initComponents() de cada painel são uma sequência linear de
"this.x = new Tipo()", "this.x.setAlgo(valor)" e do GroupLayout. Aqui um
pequeno interpretador simbólico de bytecode reproduz essas chamadas sem
executar nada do .jar.
"""
from __future__ import annotations

import io
import json
import os
import struct
import zipfile

# ====================================================================== classfile


class Classe:
    def __init__(self, dados: bytes):
        self.d = dados
        self.p = 0
        if self._u4() != 0xCAFEBABE:
            raise ValueError("não é um .class")
        self._u2(); self._u2()
        n = self._u2()
        self.cp = [None] * n
        i = 1
        while i < n:
            tag = self._u1()
            if tag == 1:
                tam = self._u2()
                self.cp[i] = ("utf8", self._mutf8(self.d[self.p:self.p + tam]))
                self.p += tam
            elif tag == 3:
                self.cp[i] = ("int", struct.unpack(">i", self._n(4))[0])
            elif tag == 4:
                self.cp[i] = ("float", struct.unpack(">f", self._n(4))[0])
            elif tag == 5:
                self.cp[i] = ("long", struct.unpack(">q", self._n(8))[0])
                i += 1
            elif tag == 6:
                self.cp[i] = ("double", struct.unpack(">d", self._n(8))[0])
                i += 1
            elif tag == 7:
                self.cp[i] = ("class", self._u2())
            elif tag == 8:
                self.cp[i] = ("string", self._u2())
            elif tag in (9, 10, 11):
                self.cp[i] = (("field", "method", "imethod")[tag - 9], self._u2(), self._u2())
            elif tag == 12:
                self.cp[i] = ("nat", self._u2(), self._u2())
            elif tag == 15:
                self.cp[i] = ("mhandle", self._u1(), self._u2())
            elif tag == 16:
                self.cp[i] = ("mtype", self._u2())
            elif tag in (17, 18):
                self.cp[i] = ("indy", self._u2(), self._u2())
            elif tag in (19, 20):
                self.cp[i] = ("module", self._u2())
            else:
                raise ValueError("constante %d desconhecida" % tag)
            i += 1
        self._u2()
        self.nome = self.nome_classe(self._u2())
        sup = self._u2()
        self.super_ = self.nome_classe(sup) if sup else None
        for _ in range(self._u2()):
            self._u2()
        self.campos = {}
        for _ in range(self._u2()):
            self._u2()
            nm, desc = self._u2(), self._u2()
            self.campos[self.utf8(nm)] = self.utf8(desc)
            self._atributos()
        self.metodos = {}
        for _ in range(self._u2()):
            self._u2()
            nm, desc = self._u2(), self._u2()
            attrs = self._atributos()
            if "Code" in attrs:
                c = attrs["Code"]
                tam = struct.unpack_from(">I", c, 4)[0]
                codigo = c[8:8 + tam]
                n_exc = struct.unpack_from(">H", c, 8 + tam)[0]
                handlers = {struct.unpack_from(">H", c, 10 + tam + 8 * k + 4)[0] for k in range(n_exc)}
                self.metodos[(self.utf8(nm), self.utf8(desc))] = (codigo, handlers)

    # leitura
    def _n(self, k):
        v = self.d[self.p:self.p + k]
        self.p += k
        return v

    def _u1(self):
        self.p += 1
        return self.d[self.p - 1]

    def _u2(self):
        self.p += 2
        return struct.unpack_from(">H", self.d, self.p - 2)[0]

    def _u4(self):
        self.p += 4
        return struct.unpack_from(">I", self.d, self.p - 4)[0]

    @staticmethod
    def _mutf8(b):
        try:
            return b.decode("utf-8")
        except UnicodeDecodeError:
            return b.replace(b"\xc0\x80", b"\0").decode("utf-8", "replace")

    def _atributos(self):
        out = {}
        for _ in range(self._u2()):
            nm = self.utf8(self._u2())
            tam = self._u4()
            out[nm] = self._n(tam)
        return out

    def utf8(self, i):
        return self.cp[i][1]

    def nome_classe(self, i):
        return self.utf8(self.cp[i][1])

    def ref(self, i):
        """(classe, nome, descritor) de field/method."""
        _t, c, nat = self.cp[i]
        _n, nm, desc = self.cp[nat]
        return self.nome_classe(c), self.utf8(nm), self.utf8(desc)


def _args_desc(desc):
    """Tipos dos parâmetros de um descritor de método, e o retorno."""
    i = 1
    tipos = []
    while desc[i] != ")":
        j = i
        while desc[j] == "[":
            j += 1
        if desc[j] == "L":
            j = desc.index(";", j)
        tipos.append(desc[i:j + 1])
        i = j + 1
    return tipos, desc[i + 1:]


def _float32(v):
    """Menor decimal que representa o float32 (como o literal do código-fonte)."""
    for d in range(1, 10):
        s = float("%.*g" % (d, v))
        if struct.unpack(">f", struct.pack(">f", s))[0] == v:
            return s
    return v


# ====================================================================== valores simbólicos


class Obj:
    """Objeto criado por "new" (ou desconhecido)."""
    __slots__ = ("tipo", "args", "campo", "filhos", "layout", "eixo", "titulo")

    def __init__(self, tipo, args=None):
        self.tipo = tipo
        self.args = args or []
        self.campo = None      # var a que foi atribuído (this.var)
        self.filhos = []       # para grupos do GroupLayout
        self.layout = None
        self.titulo = None


class Campo:
    """this.var (referência a um campo do painel)."""
    __slots__ = ("var",)

    def __init__(self, var):
        self.var = var


class Lista(list):
    pass


ESTE = object()          # this
NADA = object()          # valor desconhecido

CORES = {"green": "#00ff00", "red": "#ff0000", "RED": "#ff0000", "GREEN": "#00ff00", "yellow": "#ffff00",
         "YELLOW": "#ffff00", "orange": "#ffc800", "ORANGE": "#ffc800", "lightGray": "#c0c0c0",
         "LIGHT_GRAY": "#c0c0c0", "gray": "#808080", "GRAY": "#808080", "white": "#ffffff", "WHITE": "#ffffff",
         "black": "#000000", "BLACK": "#000000", "blue": "#0000ff", "BLUE": "#0000ff", "cyan": "#00ffff",
         "CYAN": "#00ffff", "magenta": "#ff00ff", "MAGENTA": "#ff00ff", "pink": "#ffafaf", "PINK": "#ffafaf",
         "darkGray": "#404040", "DARK_GRAY": "#404040"}

CHAMADAS = {"addTab", "setViewportView", "add"}


# ====================================================================== interpretador


class Painel:
    """Resultado de um painel: objetos (var -> tipo + chamadas) e quem
    contém quem (para montar a árvore de grupos e abas)."""

    def __init__(self, cls: Classe):
        self.cls = cls
        self.objs = {}           # var -> {"type", "calls": [(metodo, args)], "order"}
        self.layouts = []        # (container, [vars na vertical], [vars na horizontal])
        self.adds = {}           # var -> [var | {"tab", "child"}]  (add/addTab/setViewportView)
        self.adds_self = []      # this.add(this.x)
        self.membros = {}

    def montar_membros(self):
        """Mesma ordem do extrator antigo: primeiro o GroupLayout de cada
        container (vertical e depois horizontal), depois add/addTab."""
        m = {}
        for cont, vert, hor in self.layouts:
            lst = m.setdefault(cont, [])
            for v in vert + hor:
                if v not in lst:
                    lst.append(v)
        for var in sorted(self.adds, key=lambda v: self.objs[v]["order"] if v in self.objs else 0):
            m.setdefault(var, []).extend(self.adds[var])
        if self.adds_self:
            m.setdefault("__self__", []).extend(self.adds_self)
        self.membros = m


def _valor_publico(v):
    """Converte o valor simbólico no que o JSON das telas guarda."""
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, Lista):
        return [_valor_publico(x) for x in v]
    if isinstance(v, Campo):
        return {"const": "this." + v.var}
    if isinstance(v, Obj):
        if v.tipo == "titled":
            return {"titled": v.titulo if isinstance(v.titulo, str) else ""}
        if v.tipo == "Color" and len(v.args) >= 3 and all(isinstance(a, int) for a in v.args[:3]):
            return "#%02x%02x%02x" % tuple(v.args[:3])
        if v.tipo in ("Integer", "Long", "Boolean", "Double", "Float", "Short") and v.args:
            return _valor_publico(v.args[0])
        if v.tipo == "Insets":
            return None
        if v.tipo == "Dimension":
            return {"w": v.args[0], "h": v.args[1]} if len(v.args) >= 2 else None
        return {"new": v.tipo, "args": [_valor_publico(a) for a in v.args]}
    if v is ESTE:
        return {"const": "this"}
    return {"const": "?"}


class Interpretador:
    def __init__(self, cls: Classe, bundle: dict, painel: Painel, ordem, registrar):
        self.c = cls
        self.bundle = bundle
        self.p = painel
        self.ordem = ordem
        self.registrar = registrar     # 1ª passada: só descobre os objetos

    def rodar(self, codigo, handlers, n_locais_args):
        c = self.c
        pilha = []
        locais = {0: ESTE}
        for k in range(1, n_locais_args + 1):
            locais[k] = NADA
        alvos_goto = {}
        pc = 0
        n = len(codigo)
        while pc < n:
            if pc in handlers:
                pilha = [NADA]
            if pc in alvos_goto:
                pilha = list(alvos_goto.pop(pc))
            op = codigo[pc]
            prox = pc + 1

            def u1(k=1):
                return codigo[pc + k]

            def s1(k=1):
                return struct.unpack_from(">b", codigo, pc + k)[0]

            def u2(k=1):
                return struct.unpack_from(">H", codigo, pc + k)[0]

            def s2(k=1):
                return struct.unpack_from(">h", codigo, pc + k)[0]

            if op == 0x00:                                  # nop
                pass
            elif op == 0x01:                                # aconst_null
                pilha.append(None)
            elif 0x02 <= op <= 0x08:                        # iconst_m1..5
                pilha.append(op - 0x03)
            elif op in (0x09, 0x0A):                        # lconst
                pilha.append(op - 0x09)
            elif 0x0B <= op <= 0x0D:                        # fconst
                pilha.append(float(op - 0x0B))
            elif op in (0x0E, 0x0F):                        # dconst
                pilha.append(float(op - 0x0E))
            elif op == 0x10:                                # bipush
                pilha.append(s1())
                prox = pc + 2
            elif op == 0x11:                                # sipush
                pilha.append(s2())
                prox = pc + 3
            elif op in (0x12, 0x13, 0x14):                  # ldc, ldc_w, ldc2_w
                idx = u1() if op == 0x12 else u2()
                prox = pc + (2 if op == 0x12 else 3)
                e = c.cp[idx]
                if e[0] == "string":
                    pilha.append(c.utf8(e[1]))
                elif e[0] == "float":
                    pilha.append(_float32(e[1]))
                elif e[0] in ("int", "long", "double"):
                    pilha.append(e[1])
                else:
                    pilha.append(NADA)
            elif 0x15 <= op <= 0x19:                        # iload..aload n
                pilha.append(locais.get(u1(), NADA))
                prox = pc + 2
            elif 0x1A <= op <= 0x2D:                        # xload_n
                pilha.append(locais.get((op - 0x1A) % 4, NADA))
            elif 0x2E <= op <= 0x35:                        # xaload
                pilha.pop(); arr = pilha.pop()
                pilha.append(NADA if not isinstance(arr, Lista) else NADA)
            elif 0x36 <= op <= 0x3A:                        # xstore n
                locais[u1()] = pilha.pop()
                prox = pc + 2
            elif 0x3B <= op <= 0x4E:                        # xstore_n
                locais[(op - 0x3B) % 4] = pilha.pop()
            elif 0x4F <= op <= 0x56:                        # xastore
                v = pilha.pop(); i = pilha.pop(); arr = pilha.pop()
                if isinstance(arr, Lista) and isinstance(i, int):
                    while len(arr) <= i:
                        arr.append(None)
                    arr[i] = v
            elif op == 0x57:                                # pop
                pilha.pop()
            elif op == 0x58:                                # pop2
                pilha.pop()
            elif op == 0x59:                                # dup
                pilha.append(pilha[-1])
            elif op == 0x5A:                                # dup_x1
                pilha.insert(-2, pilha[-1])
            elif op == 0x5B:                                # dup_x2
                pilha.insert(-3, pilha[-1])
            elif op == 0x5C:                                # dup2
                pilha.extend(pilha[-2:])
            elif op == 0x5F:                                # swap
                pilha[-1], pilha[-2] = pilha[-2], pilha[-1]
            elif 0x60 <= op <= 0x83:                        # aritmética
                if op in (0x74, 0x75, 0x76, 0x77):          # neg
                    v = pilha.pop()
                    pilha.append(-v if isinstance(v, (int, float)) and not isinstance(v, bool) else NADA)
                else:
                    b = pilha.pop(); a = pilha.pop()
                    r = NADA
                    if all(isinstance(x, (int, float)) for x in (a, b)):
                        k = (op - 0x60) // 4
                        try:
                            r = [a + b, a - b, a * b, a / b if isinstance(a, float) else int(a / b),
                                 a % b][k] if k < 5 else (a << b if op in (0x78, 0x79) else a >> b if op <= 0x7B
                                                           else a & b if op <= 0x7F else a | b if op <= 0x81 else a ^ b)
                        except Exception:  # noqa: BLE001
                            r = NADA
                    pilha.append(r)
            elif op == 0x84:                                # iinc
                prox = pc + 3
            elif 0x85 <= op <= 0x93:                        # conversões
                v = pilha.pop()
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    if op in (0x86, 0x87, 0x89, 0x8A, 0x8C, 0x8D):
                        v = float(v)
                    elif op in (0x85, 0x88, 0x8B, 0x8E, 0x8F, 0x90, 0x91, 0x92, 0x93):
                        v = int(v)
                pilha.append(v)
            elif 0x94 <= op <= 0x98:                        # comparações
                pilha.pop(); pilha.pop(); pilha.append(NADA)
            elif 0x99 <= op <= 0x9E or op in (0xC6, 0xC7):  # if<cond>, ifnull
                pilha.pop()
                prox = pc + 3
            elif 0x9F <= op <= 0xA6:                        # if_icmp / if_acmp
                pilha.pop(); pilha.pop()
                prox = pc + 3
            elif op == 0xA7:                                # goto
                alvo = pc + s2()
                prox = pc + 3
                if alvo > pc:
                    alvos_goto[alvo] = list(pilha)
                    prox = alvo
            elif op in (0xAA, 0xAB):                        # tableswitch / lookupswitch
                pilha.pop()
                q = (pc + 4) & ~3
                if op == 0xAA:
                    lo, hi = struct.unpack_from(">ii", codigo, q + 4)
                    prox = q + 12 + 4 * (hi - lo + 1)
                else:
                    npar = struct.unpack_from(">i", codigo, q + 4)[0]
                    prox = q + 8 + 8 * npar
            elif 0xAC <= op <= 0xB1:                        # returns
                break
            elif op == 0xB2:                                # getstatic
                cl, nm, _d = c.ref(u2())
                prox = pc + 3
                if cl == "java/awt/Color" and nm in CORES:
                    pilha.append(CORES[nm])
                else:
                    pilha.append(NADA)
            elif op == 0xB3:                                # putstatic
                pilha.pop()
                prox = pc + 3
            elif op == 0xB4:                                # getfield
                cl, nm, _d = c.ref(u2())
                prox = pc + 3
                obj = pilha.pop()
                pilha.append(Campo(nm) if obj is ESTE else NADA)
            elif op == 0xB5:                                # putfield
                cl, nm, _d = c.ref(u2())
                prox = pc + 3
                v = pilha.pop(); obj = pilha.pop()
                if self.registrar and obj is ESTE and isinstance(v, Obj) and not v.args and nm not in self.p.objs:
                    v.campo = nm
                    self.p.objs[nm] = {"type": v.tipo, "calls": [], "order": next(self.ordem)}
            elif 0xB6 <= op <= 0xB9:                        # invoke*
                cl, nm, desc = c.ref(u2())
                prox = pc + (5 if op == 0xB9 else 3)
                tipos, ret = _args_desc(desc)
                args = [pilha.pop() for _ in tipos][::-1]
                args = [bool(a) if t == "Z" and isinstance(a, int) else a for a, t in zip(args, tipos)]
                rec = pilha.pop() if op != 0xB8 else None
                r = self._invocar(op, cl, nm, desc, rec, args, ret)
                if ret != "V":
                    pilha.append(r)
            elif op == 0xBA:                                # invokedynamic
                _t, _bsm, nat = c.cp[u2()]
                desc = c.utf8(c.cp[nat][2])
                tipos, ret = _args_desc(desc)
                for _ in tipos:
                    pilha.pop()
                pilha.append(NADA)
                prox = pc + 5
            elif op == 0xBB:                                # new
                tipo = c.nome_classe(u2()).rsplit("/", 1)[-1]
                pilha.append(Obj(tipo))
                prox = pc + 3
            elif op == 0xBC:                                # newarray
                pilha.pop(); pilha.append(Lista())
                prox = pc + 2
            elif op == 0xBD:                                # anewarray
                pilha.pop(); pilha.append(Lista())
                prox = pc + 3
            elif op == 0xBE:                                # arraylength
                pilha.pop(); pilha.append(NADA)
            elif op == 0xBF:                                # athrow
                pilha = []
            elif op == 0xC0:                                # checkcast
                prox = pc + 3
            elif op == 0xC1:                                # instanceof
                pilha.pop(); pilha.append(NADA)
                prox = pc + 3
            elif op in (0xC2, 0xC3):                        # monitor
                pilha.pop()
            elif op == 0xC4:                                # wide
                op2 = codigo[pc + 1]
                prox = pc + (6 if op2 == 0x84 else 4)
                if 0x15 <= op2 <= 0x19:
                    pilha.append(NADA)
                elif 0x36 <= op2 <= 0x3A:
                    pilha.pop()
            elif op == 0xC5:                                # multianewarray
                for _ in range(codigo[pc + 3]):
                    pilha.pop()
                pilha.append(Lista())
                prox = pc + 4
            elif op in (0xC8, 0xC9):                        # goto_w, jsr_w
                prox = pc + 5
            else:
                raise ValueError("opcode 0x%02x não tratado em %s" % (op, c.nome))
            pc = prox

    # ------------------------------------------------------------------ chamadas
    def _invocar(self, op, cl, nm, desc, rec, args, ret):
        curto = cl.rsplit("/", 1)[-1]
        if nm == "<init>":
            if isinstance(rec, Obj):
                rec.args = args
                if curto == "GroupLayout":
                    rec.layout = args[0] if args else None
            return None
        # construtores com valor
        if op == 0xB8:                                       # static
            if curto in ("Integer", "Long", "Double", "Float", "Boolean", "Short", "Byte") and nm == "valueOf":
                return args[0] if args else NADA
            if curto == "ResourceBundle" and nm == "getBundle":
                return Obj("bundle")
            if curto == "MessageFormat" and nm == "format" and args and isinstance(args[0], str):
                fmt = args[0]
                resto = args[1:]
                if len(resto) == 1 and isinstance(resto[0], Lista):
                    resto = resto[0]
                for i, a in enumerate(resto):
                    fmt = fmt.replace("{%d}" % i, str(_valor_publico(a)))
                return fmt
            if curto == "BorderFactory" and nm.startswith("createTitledBorder"):
                o = Obj("titled")
                strs = [a for a in args if isinstance(a, str)]
                o.titulo = strs[0] if strs else ""
                return o
            if curto == "Bundle" and nm == "getString" and args:
                return self._bundle(args[0])
            return NADA
        # métodos de instância
        if nm == "getString" and isinstance(rec, Obj) and rec.tipo == "bundle" and args:
            return self._bundle(args[0])
        if isinstance(rec, Obj) and rec.tipo == "Color":
            return NADA
        if isinstance(rec, Obj) and rec.tipo == "GroupLayout":
            if nm in ("createParallelGroup", "createSequentialGroup", "createBaselineGroup"):
                g = Obj("grupo")
                g.layout = rec
                return g
            if nm in ("setHorizontalGroup", "setVerticalGroup") and args and isinstance(args[0], Obj) \
                    and not self.registrar:
                cont = rec.layout
                chave = "__self__" if cont is ESTE else (cont.var if isinstance(cont, Campo) else None)
                if chave is not None:
                    if rec.titulo is None:
                        rec.titulo = [chave, [], []]
                        self.p.layouts.append(rec.titulo)
                    rec.titulo[1 if nm == "setVerticalGroup" else 2] = self._achatar(args[0])
            return None
        if isinstance(rec, Obj) and rec.tipo == "grupo":
            if nm == "addComponent" and args:
                comp = next((a for a in args if isinstance(a, Campo)), None)
                if comp is not None:
                    rec.filhos.append(comp.var)
            elif nm == "addGroup" and args:
                g = next((a for a in args if isinstance(a, Obj) and a.tipo == "grupo"), None)
                if g is not None:
                    rec.filhos.append(g)
            return rec
        if self.registrar:
            return NADA
        if isinstance(rec, Campo) and rec.var in self.p.objs:
            if nm.startswith("set") or nm in CHAMADAS:
                self.p.objs[rec.var]["calls"].append((nm, args))
                if nm == "addTab" and len(args) >= 2 and isinstance(args[1], Campo):
                    t = args[0] if isinstance(args[0], str) else ""
                    self.p.adds.setdefault(rec.var, []).append({"tab": t.strip(), "child": args[1].var})
                elif nm in ("add", "setViewportView") and args and isinstance(args[0], Campo):
                    if args[0].var in self.p.objs:
                        self.p.adds.setdefault(rec.var, []).append(args[0].var)
            return NADA
        if rec is ESTE and nm == "add" and args and isinstance(args[0], Campo):
            self.p.adds_self.append(args[0].var)
            return NADA
        return NADA

    def _achatar(self, g):
        out = []
        for f in g.filhos:
            if isinstance(f, Obj):
                out.extend(self._achatar(f))
            else:
                out.append(f)
        return out

    def _bundle(self, chave):
        if not isinstance(chave, str):
            return NADA
        return self.bundle.get(chave, chave).strip()


# ====================================================================== montagem do JSON

IGNORAR_CHAMADAS = {"add", "addTab", "setViewportView", "setLayout", "setPreferredSize", "setMinimumSize",
                    "setMaximumSize", "setLabelSize", "setFont", "setMargin", "setHorizontalAlignment",
                    "setLabelHorizontalAlignment", "setParentScrollPane", "setIconTextGap", "setOrientation",
                    "setModel", "setDefaultRenderer", "setRowHeight", "setShowGrid", "setTableHeader",
                    "setSelectionMode", "setCellRenderer", "setListData", "setIconImage",
                    "setDefaultCloseOperation", "setContentPane", "setHorizontalTextPosition"}
GRUPOS = ("JPanel", "MbPanel", "JScrollPane", "Box")
SWING = ("JLabel", "JButton", "JSeparator", "JList", "JTable", "JCheckBox", "JTextField", "JComboBox",
         "JTextArea", "JToggleButton", "JRadioButton", "ButtonGroup", "JSlider")


def _props(o, ordenado=False):
    props = {}
    seq = []
    for meth, args in o["calls"]:
        if meth in IGNORAR_CHAMADAS:
            continue
        chave = meth[3:] if meth.startswith("set") else meth
        chave = chave[0].lower() + chave[1:]
        val = _valor_publico(args[0]) if len(args) == 1 else [_valor_publico(a) for a in args]
        if chave == "border":
            if isinstance(val, dict) and "titled" in val:
                props["groupTitle"] = val["titled"] if isinstance(val["titled"], str) else ""
            continue
        props[chave] = val
        seq.append([chave, val])
    return seq if ordenado else props


def _arvore(p: Painel, no, vistos):
    out = []
    for item in p.membros.get(no, []):
        if isinstance(item, dict):
            filho = item["child"]
            if filho in vistos:
                continue
            vistos.add(filho)
            out.append({"kind": "tab", "title": item["tab"], "children": _filho(p, filho, vistos)})
            continue
        if item in vistos:
            continue
        vistos.add(item)
        out.extend(_filho(p, item, vistos))
    return out


def _filho(p: Painel, var, vistos):
    o = p.objs.get(var)
    if o is None:
        return []
    tipo = o["type"]
    props = _props(o)
    if tipo in GRUPOS:
        n = {"kind": "group", "var": var, "title": props.get("groupTitle"), "children": _arvore(p, var, vistos)}
        if props.get("visible") is False:
            n["visible"] = False
        if "name" in props:
            n["name"] = props["name"]
        return [n]
    if tipo == "JTabbedPane":
        return [{"kind": "tabs", "var": var, "tabs": _arvore(p, var, vistos)}]
    if tipo in SWING:
        return [{"kind": "swing", "type": tipo, "var": var}]
    return [{"kind": "widget", "type": tipo, "var": var, "props": props, "calls": _props(o, True)}]


def _painel(cls: Classe, bundle):
    p = Painel(cls)
    cont = iter(range(10 ** 6))
    metodos = [(nm, desc, cod, h) for (nm, desc), (cod, h) in cls.metodos.items()
               if nm == "<init>" or (nm == "initComponents" and desc == "()V")]
    for registrar in (True, False):
        for nm, desc, codigo, handlers in metodos:
            tipos, _ = _args_desc(desc)
            n_loc = sum(2 if t in ("J", "D") else 1 for t in tipos)
            Interpretador(cls, bundle, p, cont, registrar).rodar(codigo, handlers, n_loc)
    p.montar_membros()
    return p


# ====================================================================== limpeza (o que o app usa)

PULAR = {"MbPanDockable1", "MbPanelsScroller", "MbToolBar", "MbPanOptions", "MbPanel", "MbPanGenDigital2"}
DESCARTAR = ("labelPosition", "labeled", "toolTipText", "minimumSize")


def _limpar(nos):
    out = []
    for x in nos:
        k = x["kind"]
        if k == "swing":
            continue
        if k == "group":
            c = _limpar(x["children"])
            if not c:
                continue
            n = {"kind": "group", "var": x["var"], "title": (x.get("title") or "").strip()}
            if x.get("visible") is False:
                n["visible"] = False
            if x.get("name"):
                n["name"] = x["name"]
            n["children"] = c
            out.append(n)
        elif k == "tabs":
            t = _limpar(x["tabs"])
            if t:
                out.append({"kind": "tabs", "var": x["var"], "tabs": t})
        elif k == "tab":
            out.append({"kind": "tab", "title": x["title"].strip(), "children": _limpar(x["children"])})
        elif k == "widget":
            calls = [c for c in x["calls"] if c[0] not in DESCARTAR]
            calls = [c for c in calls if not isinstance(c[1], dict)]
            out.append({"kind": "widget", "type": x["type"], "var": x["var"], "calls": calls})
    return out


def _ler_bundle(texto: str):
    b = {}
    for linha in texto.splitlines():
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        k, v = linha.split("=", 1)
        b[k.strip()] = v
    return b


class ErroJar(Exception):
    pass


def extrair(dados_jar: bytes) -> dict:
    """Lê o .jar do ARK-T Installer Utility e devolve {"panels", "bundle"}."""
    try:
        z = zipfile.ZipFile(io.BytesIO(dados_jar))
    except zipfile.BadZipFile as e:
        raise ErroJar("o arquivo não é um .jar válido") from e
    with z:
        nomes = z.namelist()
        # o .jar pode vir embrulhado (app.jar dentro de outro)
        if not any(n.startswith("mbinternational/") for n in nomes):
            dentro = [n for n in nomes if n.endswith(".jar")]
            for n in dentro:
                try:
                    return extrair(z.read(n))
                except ErroJar:
                    continue
            raise ErroJar("este .jar não é o ARK-T Installer Utility (faltam as telas mbinternational/)")
        try:
            bundle = _ler_bundle(z.read("mb/messages/Bundle.properties").decode("latin-1"))
        except KeyError:
            bundle = {}
        bundle = {k: (bytes(v, "latin-1", "backslashreplace").decode("unicode_escape") if "\\" in v else v)
                  for k, v in bundle.items()}
        paineis = {}
        for n in sorted(nomes):
            if not (n.startswith("mbinternational/") and n.endswith(".class")) or "$" in n:
                continue
            cls = Classe(z.read(n))
            p = _painel(cls, bundle)
            nome = cls.nome.rsplit("/", 1)[-1]
            if nome in PULAR:
                continue
            paineis[nome] = {"tree": _limpar(_arvore_completa(p))}
    if "MbPanOutputIsdbt" not in paineis and "MbPanOutputDvbt" not in paineis:
        raise ErroJar("não encontrei as telas do ARK-T neste .jar")
    b = {k: v for k, v in bundle.items() if k.startswith(("TITLE_ROW", "TITLE_COLONNE", "ROWS_EDITABLE"))}
    return {"panels": paineis, "bundle": b}


def _arvore_completa(p: Painel):
    return _arvore(p, "__self__", set())


# ====================================================================== onde fica


def pasta_dados():
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "Ark-T")
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "arkt")


def caminho_telas():
    return os.path.join(pasta_dados(), "telas.json")


def importar(dados_jar: bytes, origem="") -> str:
    spec = extrair(dados_jar)
    spec["origem"] = origem
    os.makedirs(pasta_dados(), exist_ok=True)
    destino = caminho_telas()
    tmp = destino + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(spec, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, destino)
    return destino


def caminhos_telas():
    """Onde procurar a descrição das telas, em ordem."""
    out = []
    if os.environ.get("ARKT_TELAS"):
        out.append(os.environ["ARKT_TELAS"])
    out.append(os.path.join(os.path.dirname(__file__), "data", "telas.json"))   # pacote interno
    out.append(caminho_telas())
    return out


def carregar():
    for c in caminhos_telas():
        try:
            with open(c, encoding="utf-8") as fh:
                d = json.load(fh)
            if d.get("panels"):
                return d
        except (OSError, ValueError):
            continue
    return None


def disponivel():
    return carregar() is not None
