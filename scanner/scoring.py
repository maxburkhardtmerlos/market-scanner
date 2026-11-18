"""Puntuación y clasificación. Funciones puras: no descargan nada."""
from __future__ import annotations

import statistics
from datetime import date

from . import config as C

FINANCIAL_SECTORS = {"Financial Services", "Financials"}


def lin(x, lo, hi):
    """Escala lineal a 0..1 entre lo (0 puntos) y hi (1 punto). Admite lo > hi."""
    if x is None:
        return None
    if lo == hi:
        return None
    v = (x - lo) / (hi - lo)
    return max(0.0, min(1.0, v))


def quality_score(s: dict):
    """Calidad del negocio, 0-100. Devuelve (score, detalle)."""
    fin = s.get("sector") in FINANCIAL_SECTORS
    parts = {
        # nombre: (valor 0..1, peso)
        "crecimiento_ingresos": (lin(s.get("rev_cagr"), 0.0, 0.10), 15),
        "crecimiento_beneficio": (lin(s.get("ni_cagr"), 0.0, 0.10), 15),
        "margen_operativo": (lin(s.get("op_margin"), 0.05, 0.25), 15),
        "tendencia_margen": (lin(s.get("op_margin_change"), -0.05, 0.0), 10),
        "rentabilidad_capital": (
            lin(s.get("roe"), 0.05, 0.15) if fin else lin(s.get("roic") if s.get("roic") is not None else s.get("roe"), 0.05, 0.20),
            15,
        ),
        "margen_fcf": (None if fin else lin(s.get("fcf_margin"), 0.0, 0.15), 15),
        "deuda": (None if fin else lin(s.get("net_debt_ebitda"), 4.0, 1.0), 10),
        "margen_neto": (lin(s.get("net_margin"), 0.0, 0.15), 5),
    }
    avail = {k: v for k, v in parts.items() if v[0] is not None}
    if len(avail) < 4:
        return None, {}
    wsum = sum(w for _, w in avail.values())
    score = 100 * sum(v * w for v, w in avail.values()) / wsum
    return round(score, 1), {k: round(v * 100) for k, (v, _) in avail.items()}


def valuation_score(s: dict):
    """Valoración, 0-100 (100 = muy barata)."""
    pe, med = s.get("fwd_pe"), s.get("sector_pe")
    pe_rel = pe / med if pe and pe > 0 and med else None
    s["pe_rel"] = round(pe_rel, 2) if pe_rel is not None else None
    parts = {
        "pe_vs_sector": (lin(pe_rel, 1.3, 0.7), 50),
        "fcf_yield": (lin(s.get("fcf_yield"), 0.01, 0.06), 30),
        "peg": (lin(s.get("peg") if s.get("peg") and s.get("peg") > 0 else None, 3.0, 1.0), 20),
    }
    avail = {k: v for k, v in parts.items() if v[0] is not None}
    if "pe_vs_sector" not in avail:
        # Sin P/E forward positivo (pérdidas o sin estimaciones) no se puntúa la valoración
        return None
    wsum = sum(w for _, w in avail.values())
    return round(100 * sum(v * w for v, w in avail.values()) / wsum, 1)


def add_sector_medians(stocks: list[dict]):
    by = {}
    for s in stocks:
        pe = s.get("fwd_pe")
        if pe and 0 < pe < 200:
            by.setdefault(s.get("sector") or "?", []).append(pe)
    allpe = [p for v in by.values() for p in v]
    glob = statistics.median(allpe) if allpe else None
    med = {k: (statistics.median(v) if len(v) >= 5 else glob) for k, v in by.items()}
    for s in stocks:
        m = med.get(s.get("sector") or "?", glob)
        s["sector_pe"] = round(m, 1) if m else None


def categorize(s: dict, today: date):
    q, v, dd, rev = s.get("quality"), s.get("valuation"), s.get("dd_52w"), s.get("eps_rev_90d")
    flags = []
    ed = s.get("earnings_date")
    s["days_to_earnings"] = None
    if ed:
        try:
            d = (date.fromisoformat(ed) - today).days
            if d >= 0:
                s["days_to_earnings"] = d
                if d <= C.EARNINGS_WARN_DAYS:
                    flags.append("resultados_cerca")
            else:
                s["earnings_date"] = None
        except ValueError:
            s["earnings_date"] = None
    if s.get("fwd_pe") and 0 < s["fwd_pe"] <= C.PE_ABS_CHEAP:
        flags.append("pe_bajo_20")

    cat = "resto"
    if q is not None and q >= C.QUALITY_MIN and dd is not None:
        cat = "calidad"
        if dd <= -C.DRAWDOWN_ALERT:
            if rev is not None and rev < C.EPS_REV_MIN:
                cat = "deterioro"
            elif v is not None and v >= C.VALUATION_MIN:
                cat = "alerta"
                if rev is None:
                    flags.append("estimaciones_sin_dato")
            else:
                cat = "vigilar"
        elif dd <= -C.DRAWDOWN_WATCH:
            cat = "vigilar"
    s["category"] = cat
    s["flags"] = flags


def score_all(stocks: list[dict], today: date):
    add_sector_medians(stocks)
    for s in stocks:
        s["quality"], s["quality_parts"] = quality_score(s)
        s["valuation"] = valuation_score(s)
        categorize(s, today)
    return stocks
