"""Visão geral: os números que importam numa olhada (página nova, não
existia no applet original)."""
from __future__ import annotations

import math
from collections import deque

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from ..fmt import fmt_num  # noqa: E402
from ..i18n import item  # noqa: E402


class Cartao:
    def __init__(self, titulo):
        self.widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, width_request=230)
        self.widget.add_css_class("card")
        self.widget.add_css_class("cartao")
        self.t = Gtk.Label(label=titulo.upper(), xalign=0)
        self.t.add_css_class("cartao-titulo")
        self.v = Gtk.Label(xalign=0, ellipsize=3)
        self.v.add_css_class("cartao-valor")
        self.s = Gtk.Label(xalign=0, wrap=True)
        self.s.add_css_class("cartao-sub")
        for w in (self.t, self.v, self.s):
            self.widget.append(w)
        self._est = None

    def set(self, valor, sub="", estado=None):
        self.v.set_text(valor)
        self.s.set_text(sub)
        self.s.set_visible(bool(sub))
        if estado != self._est:
            for c in ("alerta", "ok", "aviso"):
                self.widget.remove_css_class(c)
            if estado:
                self.widget.add_css_class(estado)
            self._est = estado


class Grafico:
    """Potência direta nos últimos minutos."""

    def __init__(self, n=180):
        self.dados = deque(maxlen=n)
        self.area = Gtk.DrawingArea(content_height=150, hexpand=True)
        self.area.set_draw_func(self._desenhar)

    def adicionar(self, v):
        self.dados.append(v)
        self.area.queue_draw()

    def _desenhar(self, area, cr, w, h):
        cor = area.get_color()
        vals = [v for v in self.dados if v is not None]
        cr.set_source_rgba(cor.red, cor.green, cor.blue, 0.12)
        cr.set_line_width(1)
        for k in range(1, 4):
            y = h * k / 4
            cr.move_to(0, y)
            cr.line_to(w, y)
        cr.stroke()
        if len(vals) < 2:
            return
        lo, hi = min(vals), max(vals)
        if hi - lo < 1:
            lo, hi = lo - 0.5, hi + 0.5
        pad = 18
        n = self.dados.maxlen
        x0 = w - (len(self.dados) - 1) * (w / (n - 1))
        cr.set_source_rgba(0.21, 0.52, 0.89, 1)
        cr.set_line_width(2)
        primeiro = True
        for i, v in enumerate(self.dados):
            if v is None:
                primeiro = True
                continue
            x = x0 + i * (w / (n - 1))
            y = pad + (h - 2 * pad) * (1 - (v - lo) / (hi - lo))
            if primeiro:
                cr.move_to(x, y)
                primeiro = False
            else:
                cr.line_to(x, y)
        cr.stroke()
        cr.set_source_rgba(cor.red, cor.green, cor.blue, 0.6)
        cr.select_font_face("Sans")
        cr.set_font_size(11)
        cr.move_to(4, 12)
        cr.show_text("%s dBm" % fmt_num(hi, 1))
        cr.move_to(4, h - 4)
        cr.show_text("%s dBm" % fmt_num(lo, 1))


def _w(dbm):
    return 10 ** (dbm / 10.0) / 1000.0


class VisaoGeral:
    def __init__(self, modelo, ctx):
        self.m = modelo
        self.ctx = ctx
        self.widget = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=1280, tightening_threshold=900)
        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=18, margin_bottom=24,
                        margin_start=18, margin_end=18)
        clamp.set_child(caixa)
        self.widget.set_child(clamp)

        self.cab = Gtk.Label(xalign=0)
        self.cab.add_css_class("titulo-tela")
        self.cab_sub = Gtk.Label(xalign=0)
        self.cab_sub.add_css_class("dim-label")
        caixa.append(self.cab)
        caixa.append(self.cab_sub)

        fluxo = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, min_children_per_line=2,
                            max_children_per_line=4, column_spacing=12, row_spacing=12)
        caixa.append(fluxo)
        nomes = ["amplificador", "rf", "modo", "canal", "direta", "refletida", "temperatura", "referencia",
                 "entrada", "gps", "alarmes", "evento"]
        titulos = ["Amplificador", "RF", "Modo em uso", "Canal / frequência", "Potência direta",
                   "Refletida / ROE", "Temperatura", "Referência de frequência", "Entrada", "GPS",
                   "Alarmes", "Último evento"]
        self.c = {}
        for n, t in zip(nomes, titulos):
            self.c[n] = Cartao(t)
            fluxo.append(self.c[n].widget)

        g = Adw.PreferencesGroup(title="Potência direta", description="Últimos 6 minutos")
        caixa_g = Gtk.Box()
        caixa_g.add_css_class("card")
        self.grafico = Grafico()
        caixa_g.append(self.grafico.area)
        g.add(caixa_g)
        caixa.append(g)

        self.lista_alarmes = Adw.PreferencesGroup(title="Alarmes ativos")
        caixa.append(self.lista_alarmes)
        self._linhas_alarme = []

    def set_editavel(self, ed):
        pass

    def _c(self, painel_isdbt, painel_dvbt, var):
        f = self.m.campo(painel_isdbt, var) or self.m.campo(painel_dvbt, var)
        return f

    def atualizar(self, st, ultimo_evento=None):
        m = self.m
        out = ("MbPanOutputIsdbt", "MbPanOutputDvbt")
        d = m.defs
        self.cab.set_text(d.sys_name or "ARK-T")
        partes = [x for x in (d.sys_cust, self.ctx.endereco, "família " + ("ISDB-T" if m.familia == "isdbt" else "DVB-T")) if x]
        self.cab_sub.set_text(" • ".join(partes))

        f = self._c(*out, "mbTextFieldChoice1")
        if f:
            v = f.ler(st)
            ok = v.bruto == 0
            self.c["amplificador"].set(item(v.texto), "", "ok" if ok else "alerta")
        f = self._c(*out, "mbButtonRf1")
        if f:
            v = f.ler(st)
            off_eq = v.extra.get("rf_global_off")
            self.c["rf"].set("Ligado" if v.ligado and not off_eq else "Desligado",
                             "desligado pelo equipamento" if off_eq else "", "ok" if v.ligado and not off_eq else "alerta")
        modo = m.modo_atual(st)
        cfg = m.config_modo(modo, st)
        self.c["modo"].set("Modo %s" % "AB"[modo], m.nome_config(cfg))
        ch = m.nome("cho_channel_%s_out" % "ab"[modo])
        freq = self._c(*out, "mbTextField10")
        fv = freq.ler(st).bruto if freq else None
        canal = item(ch.ler(st).texto) if ch and ch.items else "—"
        self.c["canal"].set(canal.split(" (")[0], ("%s MHz" % fmt_num(fv / 1e6, 6)) if isinstance(fv, (int, float)) and fv else "")
        fwd = self._c(*out, "mbTextField7")
        ref = self._c(*out, "mbTextField9")
        fdb = fwd.ler(st).bruto if fwd else None
        rdb = ref.ler(st).bruto if ref else None
        alvo = m.nome("power_%s_dbm" % "ab"[modo])
        alvo_v = alvo.ler(st).bruto if alvo else None
        if isinstance(fdb, (int, float)):
            sub = "%s W" % fmt_num(_w(fdb), 2)
            if isinstance(alvo_v, (int, float)):
                sub += " • ajuste %s dBm" % fmt_num(alvo_v, 1)
            est = "ok"
            if isinstance(alvo_v, (int, float)) and fdb < alvo_v - 3:
                est = "aviso"
            self.c["direta"].set("%s dBm" % fmt_num(fdb, 1), sub, est)
            self.grafico.adicionar(fdb)
        else:
            self.c["direta"].set("—", "sem leitura", "alerta")
            self.grafico.adicionar(None)
        if isinstance(rdb, (int, float)) and isinstance(fdb, (int, float)):
            pr, pf = _w(rdb), _w(fdb)
            gam = math.sqrt(pr / pf) if pf > 0 else 0
            roe = (1 + gam) / (1 - gam) if gam < 1 else float("inf")
            est = "ok" if roe < 1.5 else ("aviso" if roe < 2.0 else "alerta")
            self.c["refletida"].set("%s dBm" % fmt_num(rdb, 1), "%s W • ROE %s:1" % (fmt_num(pr, 3), fmt_num(roe, 2)), est)
        else:
            self.c["refletida"].set("—", "")
        t = self._c(*out, "mbTextField6")
        tv = t.ler(st).bruto if t else None
        aviso = self._c(*out, "mbNumericEmpty3_27")
        lim = aviso.ler(st).bruto if aviso else None
        if isinstance(tv, (int, float)):
            est = "ok"
            if isinstance(lim, (int, float)) and lim and tv >= lim:
                est = "alerta"
            self.c["temperatura"].set("%s °C" % fmt_num(tv, 1), ("aviso em %s °C" % fmt_num(lim, 0)) if lim else "", est)
        r = self._c(*out, "mbChoiceClockReference1")
        if r:
            self.c["referencia"].set(item(r.ler(st).texto))
        ent = m.campo("MbPanSwitchIsdbtItu", "mbTextFieldChoice6")
        if ent:
            nome_ent = ent.ler(st).texto
            stat = None
            mapa = {"ASI 1": "mbStatAsi1", "ASI 2": "mbStatAsi2", "ASI 3": "mbStatAsi3", "ASI 4": "mbStatAsi4",
                    "GbE 1": "mbStatGbeInput"}
            if nome_ent in mapa:
                stat = m.campo("MbPanInputIsdbt", mapa[nome_ent])
            sub, est = "", None
            if stat is not None and not stat.standby:
                sv = stat.ler(st)
                br = stat.packet if hasattr(stat, "packet") else getattr(stat, "bitrate", None)
                bv = br.ler(st).bruto if br is not None else None
                if sv.ligado:
                    sub = "travada" + (" • %s Mbit/s" % fmt_num(bv / 1e6, 2) if isinstance(bv, (int, float)) else "")
                    est = "ok"
                else:
                    sub, est = "sem sinal", "alerta"
            self.c["entrada"].set(item(nome_ent), sub, est)
        else:
            self.c["entrada"].set("—")
        gv = m.campo("MbPanGps2", "mbLed1")
        gt = m.campo("MbPanGps2", "mbTextFieldCustom2")
        if gv:
            ok = gv.ler(st).ligado
            sats = gt.ler(st).texto if gt else ""
            self.c["gps"].set("Válido" if ok else "Sem dados", ("%s satélites rastreados" % sats) if sats else "",
                              "ok" if ok else "alerta")
        ativos = [a for a in m.alarmes.ler(st) if a["ativo"]]
        self.c["alarmes"].set(str(len(ativos)) if ativos else "Nenhum",
                              ", ".join(a["nome"] for a in ativos[:3]) + ("…" if len(ativos) > 3 else ""),
                              "alerta" if ativos else "ok")
        for ln in self._linhas_alarme:
            self.lista_alarmes.remove(ln)
        self._linhas_alarme = []
        for a in ativos:
            row = Adw.ActionRow(title=a["nome"])
            p = Gtk.Label(label="●")
            p.add_css_class("led")
            p.add_css_class("led-vermelho")
            row.add_prefix(p)
            self.lista_alarmes.add(row)
            self._linhas_alarme.append(row)
        self.lista_alarmes.set_visible(bool(ativos))
        if ultimo_evento is not None:
            self.c["evento"].set(ultimo_evento.hora, ultimo_evento.texto[:90], "alerta" if ultimo_evento.tipo == "alarme" else None)
