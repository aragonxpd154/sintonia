<p align="center">
  <img src="assets/banner.png" alt="Sintonia: programas nativos, sem Java, para equipamentos de transmissão" width="100%">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Zorin%20OS-pronto-15A6F0?logo=zorin&logoColor=white" alt="Zorin OS">
  <img src="https://img.shields.io/badge/Linux-Ubuntu%2024.04%20%7C%20Debian-1C71D8?logo=linux&logoColor=white" alt="Linux">
  <img src="https://img.shields.io/badge/Windows-10%20%7C%2011-0078D4?logo=windows&logoColor=white" alt="Windows 10 e 11">
  <img src="https://img.shields.io/badge/GTK4-libadwaita-62A0EA?logo=gnome&logoColor=white" alt="GTK4 + libadwaita">
  <img src="https://img.shields.io/badge/Java-n%C3%A3o%20precisa-F6D32D?logo=openjdk&logoColor=black" alt="Sem Java">
  <img src="https://img.shields.io/badge/licen%C3%A7a-MIT-9FB7C2" alt="MIT">
</p>

**Sintonia** é uma coleção de programas nativos para gerenciar **equipamentos de transmissão de TV e rádio** cujo software de fábrica é um applet ou programa **Java** antigo. Cada app reescreve um desses programas como um aplicativo de verdade para **Linux e Windows**: mesma comunicação com o equipamento, telas em português, modo edição com confirmação, simulador para treinar e pacotes `.deb` e `.exe` prontos.

O problema é sempre o mesmo. Excitadores, multiplexadores e afins chegaram com um `.jar` de mais de dez anos que só roda num Java antigo, abre com avisos de segurança e não evolui. Nos computadores de hoje, em especial no Linux, abrir a gerência de um transmissor vira um trabalho à parte. O Sintonia coloca esses equipamentos de volta "em sintonia" com o computador de hoje.

---

## Apps

| App | Equipamento | Situação | Pacotes |
|---|---|---|---|
| **[Ark-T](ark-t)** | excitadores **ARK-T** ISDB-T e DVB-T (MB International / Screen Service) - substitui o *ARK-T Installer Utility 5.5* | ![disponível](https://img.shields.io/badge/-1.1.0-33D17A) | [`.deb`, instalador e portátil do Windows](https://github.com/aragonxpd154/sintonia/releases) |
| **ARK-6** | excitadores ARK-6 | ![em breve](https://img.shields.io/badge/-em%20breve-5F6E86) | - |
| **Multiplexador** | multiplexador com gerência em Java | ![em breve](https://img.shields.io/badge/-em%20breve-5F6E86) | - |

<p align="center">
  <a href="ark-t"><img src="ark-t/assets/tela-precorrecao-ampm.png" alt="Ark-T: editor da pré-correção AM/AM e AM/PM" width="100%"></a><br>
  <sub>Ark-T: editor da pré-correção AM/AM e AM/PM de um ARK-T (simulado).</sub>
</p>

---

## Como os apps funcionam

- **Nada do fabricante no repositório.** As telas de cada equipamento (que campo fica em que posição, comandos, opções) saem do programa original. O app lê o `.jar` que o próprio equipamento publica - ou que você já tem -, **sem executá-lo**, e guarda a descrição no seu computador. Veja o [`NOTICE`](NOTICE).
- **Mesma conversa com o equipamento.** Os protocolos (TCP, HTTP, arquivos de configuração e de pré-correção) são reproduzidos e conferidos contra o programa original (a matemática da pré-correção do Ark-T, por exemplo, dá resultado idêntico ao do Java).
- **Seguro para usar no ar.** Nada é alterado sem o modo edição, e toda mudança sensível mostra os comandos antes de enviar.
- **Simulador embutido** em cada app, para treinar e testar sem mexer no transmissor.
- **Linux e Windows** com o mesmo código: GTK4 + libadwaita, `.deb` para Zorin OS / Ubuntu / Debian e instalador `.exe` (sem administrador) ou `.zip` portátil para Windows.

## Instalação

Cada app tem as instruções na própria pasta - por exemplo, [Ark-T](ark-t#instalação). Os pacotes ficam na página de [Releases](https://github.com/aragonxpd154/sintonia/releases), uma Release por versão de cada app (`Ark-T 1.1.0`, …).

## Estrutura

```text
sintonia/
├── ark-t/          Ark-T - excitadores ARK-T (código, testes, pacotes, prints)
├── assets/         logo e banner do Sintonia
└── .github/        testes e Releases de cada app (ark-t.yml, ark-t-release.yml)
```

Cada app é independente dentro da sua pasta: tem o próprio código, testes, `CHANGELOG.md`, `NOTICE` e scripts de pacote. As versões são marcadas com tags por app (`ark-t-v1.1.0`); a tag dispara a Release só daquele app.

## Marcas e licença

ARK-T, MB International, Screen Service e as demais marcas citadas pertencem a seus donos. O Sintonia é um projeto independente, sem vínculo com esses fabricantes, e não inclui arquivos deles.

Código sob a licença [MIT](LICENSE) © Marcos Santos
