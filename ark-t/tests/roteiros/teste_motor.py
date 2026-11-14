import sys, time
sys.path.insert(0, ".")
from arkt import simulador, protocolo, arquivos, modelo

eq, tcp, web = simulador.rodar(19001, 18081, em_thread=True)
time.sleep(0.3)
cli = protocolo.Conexao("127.0.0.1", 19001)
with cli as c:
    lista = arquivos.lista_de_arquivos(c.pergunta("yh\n\r"))
    print("arquivos:", lista)
    st = c.status()
    sobre = protocolo.ler_sobre(c.pergunta("\xa7\r\n"))
    print("sobre:", sobre)
def http(n): return protocolo.baixar_http("127.0.0.1", n, 18081)
d = arquivos.DefinicaoSistema.ler(http(arquivos.procurar(lista, ".def")).decode("latin-1"))
print("familia:", d.familia, d.mode_dis, "standalone", d.standalone)
cd = arquivos.TabelaCanais.ler(http(arquivos.procurar(lista, ".cdef")).decode("latin-1"))
dp = arquivos.passos_potencia(http(arquivos.procurar(lista, ".dpwr")))
m = modelo.Modelo(d)
m.aplicar_arquivos(lista, d, cd, dp, dp)
m.atualizar(st)
erros = 0
for t in m.telas:
    print("==", t.titulo)
    def walk(nos, ind=1):
        global erros
        for n in nos:
            if n.tipo == "campo":
                c = n.campo
                try:
                    v = c.ler(st)
                    print("  " * ind + "%-38s %-14s %s%s" % (c.title[:38], c.tipo[:14], v.texto if v.ligado is None else ("●" if v.ligado else "○") + " " + v.texto, " [" + v.estado + "]" if v.estado != "normal" else ""))
                    for s in c.subcampos:
                        sv = s.ler(st)
                        print("  " * (ind + 2) + "%-34s %s" % (s.title, sv.texto if sv.ligado is None else ("●" if sv.ligado else "○")))
                except Exception as e:
                    erros += 1
                    print("  " * ind + "ERRO", c, e)
            elif n.filhos:
                print("  " * ind + "[%s] %s" % (n.tipo, n.titulo) + ("" if n.visivel else " (oculto)"))
                walk(n.filhos, ind + 1)
    walk(t.raiz)
print("ERROS:", erros)
al = m.alarmes.ler(st)
print("alarmes ativos:", [a["nome"] for a in al if a["ativo"]], "total:", m.alarmes.total_ligado(st))
