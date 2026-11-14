"""Editor gráfico de curvas de pré-correção (Interpolator/InterpolatorB do
original), desenhado com cairo.

Uso com o mouse: clique num espaço vazio cria um ponto, arrastar move,
botão direito (ou Delete) apaga. O primeiro e o último ponto só sobem e
descem. Rolagem do mouse aproxima o eixo vertical; o botão do meio volta à
escala inteira. Setas do teclado movem o ponto selecionado.
"""
from __future__ import annotations

import math

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GObject, Gtk  # noqa: E402

from ..precorrecao import LINEAR, Curva, Eixo  # noqa: E402

AZUL = (0.21, 0.52, 0.89)
VERMELHO = (0.88, 0.11, 0.14)
LARANJA = (0.90, 0.38, 0.0)
RAIO = 5.0
ALCANCE = 10.0


class EditorCurva(Gtk.DrawingArea):
    __gsignals__ = {
        # final=False durante o arraste; True ao soltar / teclado / apagar
        "alterada": (GObject.SignalFlags.RUN_LAST, None, (bool,)),
    }

    def __init__(self, eixo: Eixo, titulo: str, rotulo_y, rotulo_x, altura=300):
        super().__init__(hexpand=True, vexpand=True, focusable=True)
        self.set_content_height(altura)
        self.set_content_width(320)
        self.eixo = eixo
        self.titulo = titulo
        self.rotulo_y = rotulo_y          # fn(y_editor) -> str
        self.rotulo_x = rotulo_x          # fn(x) -> str
        self.curva = Curva(eixo)
        self._pontos = self.curva.pontos()
        self.referencia = None            # lista de y (curva gravada), tracejada
        self.nome_referencia = ""
        self.medida = None                # lista de y (lida do equipamento), vermelha
        self.nome_medida = ""
        self.editavel = True
        self.sel = None
        self._arraste = None
        self._mouse = None
        self.vista = (0, eixo.faixa)      # faixa vertical visível (y do editor)
        self.ml, self.mr, self.mt, self.mb = 64, 14, 30, 26

        self.set_draw_func(self._desenhar)
        arr = Gtk.GestureDrag(button=Gdk.BUTTON_PRIMARY)
        arr.connect("drag-begin", self._ini_arraste)
        arr.connect("drag-update", self._arrastando)
        arr.connect("drag-end", self._fim_arraste)
        self.add_controller(arr)
        cli = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        cli.connect("pressed", self._direito)
        self.add_controller(cli)
        meio = Gtk.GestureClick(button=Gdk.BUTTON_MIDDLE)
        meio.connect("pressed", lambda *a: self.restaurar_vista())
        self.add_controller(meio)
        mov = Gtk.EventControllerMotion()
        mov.connect("motion", self._movendo)
        mov.connect("leave", self._saiu)
        self.add_controller(mov)
        rol = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        rol.connect("scroll", self._rolar)
        self.add_controller(rol)
        tec = Gtk.EventControllerKey()
        tec.connect("key-pressed", self._tecla)
        self.add_controller(tec)

    # ------------------------------------------------------------ dados
    def set_curva(self, curva: Curva):
        self.curva = curva
        self.sel = None
        self._recalcular()

    def set_modo(self, modo):
        self.curva.modo = modo
        self._recalcular()
        self.emit("alterada", True)

    def set_referencia(self, ys, nome=""):
        self.referencia = ys
        self.nome_referencia = nome
        self.queue_draw()

    def set_medida(self, ys, nome=""):
        self.medida = ys
        self.nome_medida = nome
        self.queue_draw()

    def set_editavel(self, b):
        self.editavel = b
        self.queue_draw()

    def pontos(self):
        return self._pontos

    def _recalcular(self):
        self._pontos = self.curva.pontos()
        self.queue_draw()

    def restaurar_vista(self):
        self.vista = (0, self.eixo.faixa)
        self.queue_draw()

    # ------------------------------------------------------------ coordenadas
    def _area(self):
        w = self.get_width() - self.ml - self.mr
        h = self.get_height() - self.mt - self.mb
        return max(w, 10), max(h, 10)

    def _px(self, x, y):
        w, h = self._area()
        y0, y1 = self.vista
        return (self.ml + x * w / (self.eixo.resolucao - 1),
                self.mt + (y - y0) * h / max(1, (y1 - y0)))

    def _dados(self, px, py):
        w, h = self._area()
        y0, y1 = self.vista
        x = (px - self.ml) * (self.eixo.resolucao - 1) / w
        y = y0 + (py - self.mt) * (y1 - y0) / h
        return x, y

    def _achar(self, px, py):
        melhor, dist = None, ALCANCE
        for i, (x, y) in enumerate(self.curva.controles):
            qx, qy = self._px(x, y)
            d = math.hypot(qx - px, qy - py)
            if d <= dist:
                melhor, dist = i, d
        return melhor

    def _limitar(self, i, x, y):
        cs = self.curva.controles
        y = int(round(min(max(y, 0), self.eixo.faixa)))
        if i == 0:
            return 0, y
        if i == len(cs) - 1:
            return self.eixo.resolucao - 1, y
        x = int(round(min(max(x, 1), self.eixo.resolucao - 2)))
        return x, y

    def _reordenar(self, i, x, y):
        """Interpolator: o ponto movido é reinserido na ordem de x."""
        cs = self.curva.controles
        del cs[i]
        k = 1
        while k < len(cs) - 1 and cs[k][0] < x:
            k += 1
        cs.insert(k, [x, y])
        return k

    # ------------------------------------------------------------ mouse/teclado
    def _ini_arraste(self, g, px, py):
        self.grab_focus()
        if not self.editavel:
            g.set_state(Gtk.EventSequenceState.DENIED)
            return
        i = self._achar(px, py)
        if i is None:
            x, y = self._dados(px, py)
            if not (0 <= x <= self.eixo.resolucao - 1):
                return
            cs = self.curva.controles
            x, y = self._limitar(1 if len(cs) > 1 else 0, x, y)
            if len(cs) >= 2 and x in (0, self.eixo.resolucao - 1):
                return
            cs.insert(len(cs) - 1, [x, y])
            i = self._reordenar(len(cs) - 2, x, y)
            self._recalcular()
            self.emit("alterada", False)
        self.sel = i
        self._arraste = (i, self.curva.controles[i][0], self.curva.controles[i][1])
        self.queue_draw()

    def _arrastando(self, g, dx, dy):
        if self._arraste is None or self.sel is None:
            return
        i, x0, y0 = self._arraste
        qx, qy = self._px(x0, y0)
        x, y = self._dados(qx + dx, qy + dy)
        x, y = self._limitar(self.sel, x, y)
        if [x, y] == self.curva.controles[self.sel]:
            return
        if 0 < self.sel < len(self.curva.controles) - 1:
            self.sel = self._reordenar(self.sel, x, y)
        else:
            self.curva.controles[self.sel] = [x, y]
        self._mouse = (qx + dx, qy + dy)
        self._recalcular()
        self.emit("alterada", False)

    def _fim_arraste(self, g, dx, dy):
        if self._arraste is not None:
            self._arraste = None
            self.emit("alterada", True)

    def _direito(self, g, n, px, py):
        if not self.editavel:
            return
        i = self._achar(px, py)
        self._apagar(i)

    def _apagar(self, i):
        cs = self.curva.controles
        if i is None or i == 0 or i == len(cs) - 1:
            return
        del cs[i]
        self.sel = None
        self._recalcular()
        self.emit("alterada", True)

    def _movendo(self, c, px, py):
        self._mouse = (px, py)
        self.queue_draw()

    def _saiu(self, c):
        self._mouse = None
        self.queue_draw()

    def _rolar(self, c, dx, dy):
        y0, y1 = self.vista
        faixa = y1 - y0
        centro = (y0 + y1) / 2
        if self._mouse is not None:
            centro = self._dados(*self._mouse)[1]
        nova = faixa * (1.25 if dy > 0 else 0.8)
        nova = min(max(nova, 32), self.eixo.faixa)
        frac = (centro - y0) / faixa if faixa else 0.5
        a = centro - frac * nova
        a = min(max(a, 0), self.eixo.faixa - nova)
        self.vista = (int(a), int(a + nova))
        self.queue_draw()
        return True

    def _tecla(self, c, keyval, code, mods):
        if not self.editavel or self.sel is None or self.sel >= len(self.curva.controles):
            return False
        x, y = self.curva.controles[self.sel]
        passo_y = max(1, int((self.vista[1] - self.vista[0]) / max(self._area()[1], 1)))
        if mods & Gdk.ModifierType.SHIFT_MASK:
            passo_y *= 10
        if keyval == Gdk.KEY_Left:
            x -= 1
        elif keyval == Gdk.KEY_Right:
            x += 1
        elif keyval == Gdk.KEY_Up:
            y -= passo_y
        elif keyval == Gdk.KEY_Down:
            y += passo_y
        elif keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            self._apagar(self.sel)
            return True
        else:
            return False
        x, y = self._limitar(self.sel, x, y)
        if 0 < self.sel < len(self.curva.controles) - 1:
            self.sel = self._reordenar(self.sel, x, y)
        else:
            self.curva.controles[self.sel] = [x, y]
        self._recalcular()
        self.emit("alterada", True)
        return True

    # ------------------------------------------------------------ desenho
    def _desenhar(self, area, cr, largura, altura):
        fg = self.get_color()
        cor = (fg.red, fg.green, fg.blue)
        w, h = self._area()
        ml, mt = self.ml, self.mt

        # fundo da área de gráfico
        cr.set_source_rgba(*cor, 0.04)
        cr.rectangle(ml, mt, w, h)
        cr.fill()

        # grade
        cr.set_line_width(1)
        cr.select_font_face("Sans")
        cr.set_font_size(10.5)
        y0, y1 = self.vista
        n_lin = max(2, min(10, int(h / 40)))
        for k in range(n_lin + 1):
            yv = y0 + (y1 - y0) * k / n_lin
            _, py = self._px(0, yv)
            cr.set_source_rgba(*cor, 0.12 if 0 < k < n_lin else 0.3)
            cr.move_to(ml, int(py) + 0.5)
            cr.line_to(ml + w, int(py) + 0.5)
            cr.stroke()
            txt = self.rotulo_y(yv)
            ext = cr.text_extents(txt)
            cr.set_source_rgba(*cor, 0.65)
            cr.move_to(ml - 6 - ext.x_advance, py + ext.height / 2)
            cr.show_text(txt)
        n_col = max(2, min(8, int(w / 80)))
        res = self.eixo.resolucao - 1
        for k in range(n_col + 1):
            xv = res * k / n_col
            px, _ = self._px(xv, y0)
            cr.set_source_rgba(*cor, 0.12 if 0 < k < n_col else 0.3)
            cr.move_to(int(px) + 0.5, mt)
            cr.line_to(int(px) + 0.5, mt + h)
            cr.stroke()
            txt = self.rotulo_x(xv)
            ext = cr.text_extents(txt)
            cr.set_source_rgba(*cor, 0.65)
            ax = px - ext.x_advance / 2
            ax = min(max(ax, ml - 8), ml + w - ext.x_advance + 6)
            cr.move_to(ax, mt + h + 16)
            cr.show_text(txt)

        # título
        cr.set_font_size(12.5)
        cr.set_source_rgba(*cor, 0.9)
        cr.move_to(ml, 19)
        cr.show_text(self.titulo)
        legenda = []
        if self.referencia is not None and self.nome_referencia:
            legenda.append((self.nome_referencia, cor + (0.45,), True))
        if self.medida is not None and self.nome_medida:
            legenda.append((self.nome_medida, VERMELHO + (0.9,), False))
        lx = ml + w
        cr.set_font_size(10.5)
        for nome, rgba, trac in reversed(legenda):
            ext = cr.text_extents(nome)
            lx -= ext.x_advance
            cr.set_source_rgba(*rgba[:3], 0.8)
            cr.move_to(lx, 19)
            cr.show_text(nome)
            lx -= 26
            cr.set_source_rgba(*rgba)
            cr.set_line_width(2)
            cr.set_dash([4, 3] if trac else [])
            cr.move_to(lx, 15)
            cr.line_to(lx + 20, 15)
            cr.stroke()
            cr.set_dash([])
            lx -= 14

        cr.save()
        cr.rectangle(ml, mt, w, h)
        cr.clip()

        def linha(ys, rgba, largura_, trac=False):
            if not ys:
                return
            cr.set_source_rgba(*rgba)
            cr.set_line_width(largura_)
            cr.set_dash([5, 4] if trac else [])
            n = len(ys)
            passo = max(1, n // max(int(w), 1))
            for i in range(0, n, passo):
                px, py = self._px(i * (self.eixo.resolucao - 1) / max(n - 1, 1), ys[i])
                if i == 0:
                    cr.move_to(px, py)
                else:
                    cr.line_to(px, py)
            px, py = self._px(self.eixo.resolucao - 1, ys[-1])
            cr.line_to(px, py)
            cr.stroke()
            cr.set_dash([])

        if self.referencia is not None:
            linha(self.referencia, cor + (0.45,), 1.6, True)
        if self.medida is not None:
            linha(self.medida, VERMELHO + (0.9,), 1.6)
        alfa = 1.0 if self.editavel else 0.45
        linha(self._pontos, AZUL + (alfa,), 2.2)

        # pontos de controle
        for i, (x, y) in enumerate(self.curva.controles):
            px, py = self._px(x, y)
            cr.arc(px, py, RAIO + (1.5 if i == self.sel else 0), 0, 2 * math.pi)
            if i == self.sel:
                cr.set_source_rgba(*LARANJA, alfa)
                cr.fill_preserve()
            else:
                cr.set_source_rgba(1, 1, 1, alfa)
                cr.fill_preserve()
            cr.set_source_rgba(*AZUL, alfa)
            cr.set_line_width(2)
            cr.stroke()
        cr.restore()

        # leitura da posição do mouse
        if self._mouse is not None:
            mx, my = self._mouse
            if ml <= mx <= ml + w and mt <= my <= mt + h:
                x, y = self._dados(mx, my)
                i = int(round(min(max(x, 0), self.eixo.resolucao - 1)))
                txt = "%s   ·   %s" % (self.rotulo_x(i), self.rotulo_y(y))
                cr.set_font_size(10.5)
                ext = cr.text_extents(txt)
                bx = ml + w - ext.x_advance - 10
                cr.set_source_rgba(*cor, 0.08)
                cr.rectangle(bx - 6, mt + 6, ext.x_advance + 12, 20)
                cr.fill()
                cr.set_source_rgba(*cor, 0.8)
                cr.move_to(bx, mt + 20)
                cr.show_text(txt)
                cr.set_source_rgba(*cor, 0.25)
                cr.set_line_width(1)
                cr.move_to(int(mx) + 0.5, mt)
                cr.line_to(int(mx) + 0.5, mt + h)
                cr.stroke()


def modo_nome(modo):
    return "Linear" if modo == LINEAR else "Polinomial"
