"""Escreve em cada tipo de campo pelo protocolo e confere a releitura."""
import sys, time
sys.path.insert(0, ".")
from arkt import simulador, protocolo, arquivos, modelo, campos as C

simulador.rodar(19031, 18111, em_thread=True); time.sleep(0.3)
def http(n): return protocolo.baixar_http("127.0.0.1", n, 18111)
with protocolo.Conexao("127.0.0.1", 19031) as c:
    lista = arquivos.lista_de_arquivos(c.pergunta("yh\n\r")); st = c.status()
d = arquivos.DefinicaoSistema.ler(http(arquivos.procurar(lista, ".def")).decode("latin-1"))
cd = arquivos.TabelaCanais.ler(http(arquivos.procurar(lista, ".cdef")).decode("latin-1"))
dp = arquivos.passos_potencia(http(arquivos.procurar(lista, ".dpwr")))
m = modelo.Modelo(d); m.aplicar_arquivos(lista, d, cd, dp, dp); m.atualizar(st)

def escrever(campo, valor):
    cmds = campo.comandos(valor)
    with protocolo.Conexao("127.0.0.1", 19031) as c:
        for k in cmds: c.comando(k)
        st = c.status()
    m.atualizar(st)
    return campo.ler(st), cmds

casos = [
    ("MbPanOutputIsdbt", "numFreqOffsetA", -12345),
    ("MbPanOutputIsdbt", "numFreqOffsetA", 250000),
    ("MbPanOutputIsdbt", "numPowerADbm", 36.0),
    ("MbPanOutputIsdbt", "numPowerAW", 15.0),
    ("MbPanOutputIsdbt", "choChannelOutputA", 20),
    ("MbPanOutputIsdbt", "mbButtonRf1", False),
    ("MbPanOutputIsdbt", "mbButtonRf1", True),
    ("MbPanOutputIsdbt", "mbNumericPower3", -4.5),
    ("MbPanOutputIsdbt", "mbNumericEmpty3_27", 65),
    ("MbPanOutputIsdbt", "mbChoiceClockReference1", 0),
    ("MbPanOutputIsdbt", "mbNumericEmpty3_26", 12),
    ("MbPanSwitchIsdbtItu", "choModeB", 0),
    ("MbPanSwitchIsdbtItu", "choSwitchMode", 0),
    ("MbPanSwitchIsdbtItu", "mbNumeric3", 45),
    ("MbPanSwitchIsdbtItu", "mbNumericAlarmDelay1", 2.5),
    ("MbPanSwitchIsdbtItu", "mbCheckAutoInputEnable", True),
    ("MbPanSwitchIsdbtItu", "choInputHpA", 4),
    ("MbPanModIsdbt", "mbChoice3_borderlayout6", 1),
    ("MbPanModIsdbt", "mbChoice3_borderlayout29", 10),
    ("MbPanModIsdbt", "choGuardTime", 3),
    ("MbPanModIsdbt", "mbCheckBox39", True),
    ("MbPanModIsdbt", "mbNumericEmpty3_33", 77),
    ("MbPanNetworkIsdbt", "mbIpGb1", "239.10.1.5"),
    ("MbPanNetworkIsdbt", "mbNumPortGb1", 1234),
    ("MbPanNetworkIsdbt", "mbNumSSRCGb1", 3000000000),
    ("PanTrap", "mbIpPanel41", "10.0.0.9"),
    ("PanComunity", "mbNumericText1", "gazeta"),
]
falhas = 0
for painel, var, val in casos:
    c = m.campo(painel, var)
    if c is None:
        print("??", painel, var); falhas += 1; continue
    try:
        c.ler(m.status)
        v, cmds = escrever(c, val)
    except C.Recusado as e:
        print("RECUSADO", var, e); falhas += 1; continue
    lido = v.bruto
    ok = (lido == val) or (isinstance(val, float) and isinstance(lido, float) and abs(lido - val) < 0.05 * max(1, abs(val))) \
         or (isinstance(val, str) and v.texto == val) or (isinstance(val, bool) and v.ligado == val)
    falhas += not ok
    print("%-4s %-28s %-14r -> %-28s %s" % ("ok" if ok else "FALHA", var, val, v.texto, [k.texto.strip() for k in cmds]))
print("falhas:", falhas)
