"""Comunicação com o excitador ARK-T.

Porta TCP 10001 (Lantronix XPort): cada transação abre a conexão, envia os
comandos, pede o status ('t' -> 1405 bytes) e fecha — exatamente como o
MbThreadPoolExecutor do applet original. Arquivos de definição vêm por HTTP.
"""
from __future__ import annotations

import queue
import socket
import threading
import time
import urllib.request

from .campos import Cmd

TAMANHO_STATUS = 1405
CMD_STATUS = b"t\r\n"


class ErroConexao(Exception):
    pass


class Conexao:
    def __init__(self, host, porta=10001, timeout=10.0, tentativas=3):
        self.host = host
        self.porta = porta
        self.timeout = timeout
        self.tentativas = tentativas
        self.sock = None

    def __enter__(self):
        self.abrir()
        return self

    def __exit__(self, *a):
        self.fechar()

    def abrir(self):
        ultimo = None
        for n in range(self.tentativas):
            try:
                s = socket.create_connection((self.host, self.porta), timeout=min(self.timeout, 4.0))
                s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
                s.settimeout(self.timeout)
                self.sock = s
                return
            except OSError as e:
                ultimo = e
                time.sleep(0.6)
        raise ErroConexao("Não foi possível conectar em %s:%d (%s)" % (self.host, self.porta, ultimo))

    def fechar(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    def _descartar(self):
        """flushDis(): joga fora o que sobrou de respostas anteriores."""
        self.sock.setblocking(False)
        try:
            while True:
                d = self.sock.recv(4096)
                if not d:
                    break
        except (BlockingIOError, OSError):
            pass
        finally:
            self.sock.setblocking(True)
            self.sock.settimeout(self.timeout)

    def enviar(self, dados: bytes):
        self._descartar()
        self.sock.sendall(dados)

    def ler_exato(self, n, timeout=None):
        self.sock.settimeout(timeout or self.timeout)
        buf = bytearray()
        while len(buf) < n:
            try:
                d = self.sock.recv(n - len(buf))
            except socket.timeout:
                raise ErroConexao("Tempo esgotado esperando resposta (%d de %d bytes)" % (len(buf), n))
            if not d:
                raise ErroConexao("O equipamento fechou a conexão")
            buf.extend(d)
        return bytes(buf)

    def ler_linha(self, timeout=None):
        self.sock.settimeout(timeout or self.timeout)
        buf = bytearray()
        while True:
            try:
                d = self.sock.recv(1)
            except socket.timeout:
                raise ErroConexao("Tempo esgotado esperando resposta")
            if not d:
                raise ErroConexao("O equipamento fechou a conexão")
            if d == b"\n":
                return buf.decode("latin-1")
            buf.extend(d)

    def comando(self, cmd: Cmd):
        """Envia um comando de escrita e consome o eco do equipamento."""
        self.enviar(cmd.bytes())
        esp = cmd.esperado()
        if esp == "linha":
            return self.ler_linha()
        if not esp:
            return b""
        # O original lia exatamente esse número de bytes; se vier menos,
        # seguimos em frente (o resto é descartado no próximo envio).
        self.sock.settimeout(3.0)
        buf = bytearray()
        try:
            while len(buf) < esp:
                d = self.sock.recv(esp - len(buf))
                if not d:
                    break
                buf.extend(d)
        except socket.timeout:
            pass
        finally:
            self.sock.settimeout(self.timeout)
        return bytes(buf)

    def status(self) -> bytes:
        self.enviar(CMD_STATUS)
        return self.ler_exato(TAMANHO_STATUS)

    def pergunta(self, texto: str) -> str:
        """sendAndReceive(String): resposta até o \\n."""
        self.enviar(texto.encode("latin-1"))
        return self.ler_linha()


def baixar_http(host, nome, porta=80, timeout=8.0) -> bytes:
    url = "http://%s:%d/%s" % (host, porta, nome) if porta != 80 else "http://%s/%s" % (host, nome)
    req = urllib.request.Request(url, headers={"User-Agent": "ArkT-Linux"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


class Cliente:
    """Fila de trabalho em uma thread: leituras periódicas e escritas, uma
    transação por vez. Os callbacks são chamados na thread de trabalho —
    a interface usa GLib.idle_add para voltar à thread principal."""

    def __init__(self, host, porta=10001, porta_http=80, intervalo=2.0):
        self.host = host
        self.porta = porta
        self.porta_http = porta_http
        self.intervalo = intervalo
        self.fila: queue.Queue = queue.Queue()
        self.ao_status = None        # fn(bytes)
        self.ao_erro = None          # fn(str)
        self.ao_ocupado = None       # fn(bool)
        self._parar = threading.Event()
        self._pausado = threading.Event()
        self._thread = None
        self.ultimo_status = None
        self.ultimo_ok = 0.0
        self.falhas = 0

    def iniciar(self):
        self._thread = threading.Thread(target=self._loop, name="arkt-cliente", daemon=True)
        self._thread.start()

    def parar(self):
        self._parar.set()
        self.fila.put(None)

    def pausar(self, segundos):
        self._pausado.set()

        def volta():
            time.sleep(segundos)
            self._pausado.clear()
        threading.Thread(target=volta, daemon=True).start()

    def suspender(self):
        """Para as leituras até retomar() (gravação de arquivos na porta 5000)."""
        self._pausado.set()

    def retomar(self):
        self._pausado.clear()

    # --------------------------------------------------------------- tarefas
    def executar(self, funcao, ao_fim=None, ao_erro=None, ler_status=True):
        """funcao(conexao) roda com a conexão aberta; depois lê o status."""
        self.fila.put((funcao, ao_fim, ao_erro, ler_status))

    def escrever(self, cmds, ao_fim=None, ao_erro=None):
        def f(c):
            for cmd in cmds:
                c.comando(cmd)
            return len(cmds)
        self.executar(f, ao_fim, ao_erro)

    def _loop(self):
        proxima = 0.0
        while not self._parar.is_set():
            espera = max(0.0, proxima - time.monotonic())
            try:
                item = self.fila.get(timeout=espera if espera > 0 else 0.01)
            except queue.Empty:
                item = "poll"
            if item is None:
                break
            if self._pausado.is_set():
                if item != "poll":
                    self.fila.put(item)
                time.sleep(0.5)
                continue
            if item == "poll":
                if time.monotonic() < proxima:
                    continue
                self._transacao(None, None, None, True)
                proxima = time.monotonic() + self.intervalo
                continue
            f, ao_fim, ao_erro, ler = item
            self._transacao(f, ao_fim, ao_erro, ler and self.fila.empty())
            proxima = time.monotonic() + self.intervalo

    def _transacao(self, f, ao_fim, ao_erro, ler):
        if self.ao_ocupado:
            self.ao_ocupado(True)
        resultado = None
        try:
            with Conexao(self.host, self.porta) as c:
                if f is not None:
                    resultado = f(c)
                if ler:
                    st = c.status()
                    self.ultimo_status = st
                    self.ultimo_ok = time.time()
                    self.falhas = 0
                    if self.ao_status:
                        self.ao_status(st)
            if ao_fim:
                ao_fim(resultado)
        except Exception as e:  # noqa: BLE001
            self.falhas += 1
            if ao_erro:
                ao_erro(str(e))
            elif self.ao_erro:
                self.ao_erro(str(e))
        finally:
            if self.ao_ocupado:
                self.ao_ocupado(False)

    # --------------------------------------------------------------- consultas
    def http(self, nome):
        return baixar_http(self.host, nome, self.porta_http)


def ler_sobre(resp: str):
    """Resposta do comando '§' (About)."""
    r = resp
    out = {}
    try:
        out["fpga"] = "%d.%d" % (int(r[5:7], 16), int(r[7:9], 16))
        out["micro"] = "%d.%d" % (int(r[1:3], 16), int(r[3:5], 16))
    except ValueError:
        pass
    k = r.rfind(",")
    out["gps"] = r[k + 1:].strip() if k != -1 else "desconhecida"
    return out
