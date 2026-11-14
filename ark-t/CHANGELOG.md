# Histórico de versões

<p align="center">
  <img src="https://raw.githubusercontent.com/aragonxpd154/sintonia/main/ark-t/assets/linha-do-tempo.png" alt="Linha do tempo: 1.0.0 Linux nativo, 1.1.0 pré-correção e Windows" width="100%">
</p>

Legenda: ![novo](https://img.shields.io/badge/-novo-1C71D8) recurso novo · ![melhoria](https://img.shields.io/badge/-melhoria-0EA5E9) mudança em algo que já existia · ![correção](https://img.shields.io/badge/-corre%C3%A7%C3%A3o-F59E0B) defeito corrigido

## 1.1.0 - 2026-11-14

**Pré-correção e Windows.** O que faltava do programa original chega: o editor de curvas da porta 5000, o backup da pré-correção e a importação de configuração. E o Ark-T passa a ter instalador para Windows.

<img src="https://raw.githubusercontent.com/aragonxpd154/sintonia/main/ark-t/assets/tela-precorrecao-ampm.png" alt="Editor das curvas AM/AM e AM/PM" width="100%">

- ![novo](https://img.shields.io/badge/-novo-1C71D8) **Pré-correção AM/AM e AM/PM**: login próprio (e troca de usuário e senha), escolha de canal e faixa de potência, dois editores de curva com pontos arrastáveis, modo linear ou polinomial, envio **ao vivo** enquanto arrasta, curva gravada no equipamento tracejada ao fundo, restaurar do arquivo, salvar e salvar como.
- ![novo](https://img.shields.io/badge/-novo-1C71D8) **Pré-correção linear**: módulo (dB) e atraso de grupo (ns) por frequência, com a **resposta que o equipamento está usando** em vermelho, lida de volta dos coeficientes.
- ![novo](https://img.shields.io/badge/-novo-1C71D8) **Backup da pré-correção**: baixa os arquivos `.dpre`/`.apre`/`.dlin`/`.alin` exatamente como estão no equipamento, num `.zip` com SHA-256 de cada um (e `.cdef`/`.dpwr` como referência). **Restaurar backup** devolve os arquivos ao equipamento.
- ![novo](https://img.shields.io/badge/-novo-1C71D8) **Importar configuração** (`.sav`), com o botão para aplicar logo em seguida.
- ![novo](https://img.shields.io/badge/-novo-1C71D8) **Windows**: instalador `.exe` (instala sem administrador) e versão portátil `.zip`, com Python e GTK próprios. Não precisa de Java nem de nada instalado.
- ![novo](https://img.shields.io/badge/-novo-1C71D8) **Telas do DVB-T com as regras dinâmicas**: o que só vale para DVB-T, analógico, modo standalone ou sistemas MEDIASET é habilitado, desabilitado ou fica em espera como no original; abas da modulação somem conforme os modos do equipamento.
- ![melhoria](https://img.shields.io/badge/-melhoria-0EA5E9) **Nada do fabricante no repositório**: as telas são lidas do `.jar` original, que o próprio ARK-T publica — na primeira conexão o Ark-T baixa e lê sozinho (ou peça em **☰ › Importar telas do programa original**, ou `arkt importar-jar`).
- ![melhoria](https://img.shields.io/badge/-melhoria-0EA5E9) Referência de frequência no DVB-T manda o comando prévio do registro 3, como no original.
- ![melhoria](https://img.shields.io/badge/-melhoria-0EA5E9) Simulador com pré-correção (porta 5000, login `admin`/`admin`), troca de senha, DVB-T (`arkt simulador --dvbt`) e publicação de `.jar`.
- ![correção](https://img.shields.io/badge/-corre%C3%A7%C3%A3o-F59E0B) O alarme "Time Slicing LP" do DVB-T aparecia com o título do HP (erro do original).
- ![melhoria](https://img.shields.io/badge/-melhoria-0EA5E9) Testes automáticos com dados sintéticos e GitHub Actions (testes a cada push; `.deb`, instalador e portátil do Windows a cada tag).

## 1.0.0 - 2026-11-13

**Linux nativo, sem Java.** Primeira versão: substitui o ARK-T Installer Utility 5.5 (applet Java) por um programa GTK4/libadwaita.

<img src="https://raw.githubusercontent.com/aragonxpd154/sintonia/main/ark-t/assets/tela-visao-geral.png" alt="Visão geral do excitador" width="100%">

- ![novo](https://img.shields.io/badge/-novo-1C71D8) **Visão geral**: amplificador, RF, modo, canal e frequência, potência direta (dBm e W) com gráfico, refletida e ROE calculada, temperatura, referência, entrada com taxa de bits, GPS, alarmes e último evento.
- ![novo](https://img.shields.io/badge/-novo-1C71D8) Todas as telas do original em português — Geral, Entrada, Modos e comutação, Modulação (ISDB-T e ITU), Saída / RF, Rede e GPS —, com as camadas A/B/C do ISDB-T lado a lado.
- ![novo](https://img.shields.io/badge/-novo-1C71D8) **Alarmes** (onde cada um é sinalizado: programa, LCD, histórico, relés, traps, desligamento de RF) e **Eventos** com filtro, busca e exportação.
- ![novo](https://img.shields.io/badge/-novo-1C71D8) **Modo edição** com confirmação mostrando os comandos; desliga sozinho após 15 min.
- ![novo](https://img.shields.io/badge/-novo-1C71D8) Salvar/recarregar configuração, exportar `.sav`, reiniciar a placa, versões e números de série.
- ![novo](https://img.shields.io/badge/-novo-1C71D8) Equipamentos lembrados, **simulador** embutido e pacote `.deb` com ícone no menu.
