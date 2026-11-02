"""A "impressão digital" de cada carteira: o que dá para saber do jeito de operar só pelos fills.

É o primeiro passo para descobrir o robô por trás: moedas, horários, quanto tempo segura,
se entra com ordem limitada, se o tamanho é fixo ou proporcional ao saldo, se faz preço médio,
se a saída de prejuízo é a mercado (cara de stop) e a de lucro limitada (cara de alvo).
A fase 2 cruza as entradas com as velas (indicadores) para achar as regras.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from statistics import median

import numpy as np

from .trades import Operacao

BRT = timezone(timedelta(hours=-3))


def impressao(ops: list[Operacao], fotos: list[dict] | None = None) -> dict:
    fs = [o for o in ops if o.fechada and not o.parcial]
    if not fs:
        return {}
    n = len(fs)
    moedas = Counter(o.moeda for o in fs)
    horas = Counter(datetime.fromtimestamp(o.t0 / 1000, BRT).hour for o in fs)
    dias_sem = Counter(datetime.fromtimestamp(o.t0 / 1000, BRT).weekday() for o in fs)
    longs = sum(1 for o in fs if o.lado == "long")
    durs = sorted(o.duracao_min for o in fs)
    noc = np.asarray([o.nocional_max for o in fs if o.nocional_max > 0])
    cv = float(noc.std() / noc.mean()) if len(noc) > 2 and noc.mean() > 0 else None
    ordens = [len(o.ordens_entrada) for o in fs]
    medio = sum(1 for o in fs if o.medio_prejuizo > 0)
    perdas = [o for o in fs if o.resultado < 0]
    ganhos = [o for o in fs if o.resultado > 0]
    taker_perda = sum(o.saidas_taker_perda for o in perdas) / max(1, sum(o.saidas_perda for o in perdas)) if perdas else None
    maker_ganho = (sum(o.maker for o in ganhos) / max(1, sum(o.fills for o in ganhos))) if ganhos else None
    # alavancagem pelas fotos da conta (nocional aberto ÷ saldo)
    alav = [f["ntl"] / f["v"] for f in (fotos or []) if f.get("v", 0) > 0 and f.get("ntl", 0) > 0]
    # tamanho proporcional ao saldo? correlação entre nocional e saldo da foto mais próxima
    prop = None
    if fotos and len(fotos) > 5 and len(noc) > 10:
        ts = np.asarray([f["t"] for f in fotos]); vs = np.asarray([f["v"] for f in fotos])
        pares = []
        for o in fs:
            i = int(np.argmin(np.abs(ts - o.t0)))
            if abs(ts[i] - o.t0) < 6 * 3600 * 1000 and o.nocional_max > 0:
                pares.append((vs[i], o.nocional_max))
        if len(pares) > 10:
            a = np.asarray(pares)
            if a[:, 0].std() > 0 and a[:, 1].std() > 0:
                prop = float(np.corrcoef(a[:, 0], a[:, 1])[0, 1])

    pistas = []
    if cv is not None and cv < 0.15:
        pistas.append("usa sempre o mesmo tamanho de posição")
    elif prop is not None and prop > 0.6:
        pistas.append("o tamanho acompanha o saldo (porcentagem fixa da conta)")
    if median(ordens) >= 3:
        pistas.append("entra aos poucos, em várias ordens")
    if medio / n > 0.3:
        pistas.append("costuma fazer preço médio quando a operação vai contra")
    if taker_perda is not None and taker_perda > 0.7 and maker_ganho is not None and maker_ganho > 0.6:
        pistas.append("sai do prejuízo a mercado e do lucro com ordem limitada: cara de stop + alvo programados")
    if horas:
        pico = horas.most_common(3)
        if sum(c for _, c in pico) / n > 0.6:
            pistas.append("opera concentrado em poucas horas do dia: " + ", ".join(f"{h}h" for h, _ in sorted(pico)))
    if longs / n > 0.85:
        pistas.append("quase só compra (long)")
    elif longs / n < 0.15:
        pistas.append("quase só vende (short)")
    if moedas.most_common(1)[0][1] / n > 0.7:
        pistas.append(f"especialista em {moedas.most_common(1)[0][0]}")

    return {
        "moedas": [[m, c] for m, c in moedas.most_common(6)],
        "long": round(longs / n, 3),
        "duracao_min": {"p25": round(durs[len(durs) // 4], 1), "mediana": round(median(durs), 1), "p75": round(durs[3 * len(durs) // 4], 1)},
        "horas_brt": [horas.get(h, 0) for h in range(24)],
        "dias_semana": [dias_sem.get(d, 0) for d in range(7)],
        "tamanho_medio": round(float(noc.mean()), 2) if len(noc) else 0,
        "tamanho_variacao": round(cv, 3) if cv is not None else None,
        "tamanho_x_saldo": round(prop, 2) if prop is not None else None,
        "ordens_por_entrada": round(float(median(ordens)), 1),
        "preco_medio": round(medio / n, 3),
        "saida_perda_a_mercado": round(taker_perda, 3) if taker_perda is not None else None,
        "saida_ganho_limitada": round(maker_ganho, 3) if maker_ganho is not None else None,
        "alavancagem_mediana": round(float(median(alav)), 2) if alav else None,
        "pistas": pistas,
    }
