"""Humano ou robô? Sinais tirados só das execuções (fills) de cada carteira.

Nenhum sinal sozinho prova nada; juntos dão uma boa ideia. Cada sinal soma ou tira pontos de uma nota
de 0 (com certeza humano) a 100 (com certeza robô), a partir de 50.

Sinais:
1. Horário de dormir: humano fica sempre as mesmas horas sem operar; robô opera de madrugada igual ao dia.
2. Horas ativas: robô espalha as ordens pelas 24 horas.
3. Fechamento de vela: robô costuma mandar a ordem no segundo exato em que a vela fecha (:00 do minuto).
4. Rajadas: várias ordens no mesmo segundo, ou dezenas por minuto, ninguém faz no dedo.
5. Tamanho redondo: humano digita 0,5 BTC ou US$ 1.000; robô calcula 0,4873 a partir do saldo.
6. Intervalos regulares: robô com agenda fixa repete o mesmo intervalo entre ordens.
7. ID próprio na ordem (cloid): quem manda ordem pela API costuma numerar as próprias ordens.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import median

import numpy as np

H = 3600 * 1000
D = 24 * H


def _ordens(fills: list[dict]) -> list[dict]:
    """Uma entrada por ordem (oid): hora da primeira execução, moeda, tamanho total e preço médio."""
    por = {}
    for f in fills:
        k = f.get("o") if f.get("o") is not None else (f["t"], f["c"])
        o = por.get(k)
        if o is None:
            por[k] = {"t": f["t"], "c": f["c"], "z": f["z"], "n": f["p"] * f["z"], "x": f.get("x", 1)}
            if "cl" in f:
                por[k]["cl"] = f["cl"]
        else:
            o["t"] = min(o["t"], f["t"]); o["z"] += f["z"]; o["n"] += f["p"] * f["z"]
    out = sorted(por.values(), key=lambda o: o["t"])
    for o in out:
        o["p"] = o["n"] / o["z"] if o["z"] else 0
    return out


def _redondo(x: float) -> bool:
    """Número com no máximo 2 algarismos significativos (0,5 · 1,2 · 300 · 1.500)."""
    if x <= 0:
        return False
    e = math.floor(math.log10(x))
    m = x / 10 ** (e - 1)  # dois primeiros algarismos
    return abs(m - round(m)) < 1e-6 * max(1, m)


def avaliar(fills: list[dict]) -> dict:
    ords = _ordens(fills)
    n = len(ords)
    if n < 20:
        return {"nota": None, "rotulo": "Poucos dados", "sinais": [], "ordens": n}
    ts = np.asarray([o["t"] for o in ords], dtype=np.int64)
    dias = max(1.0, (ts[-1] - ts[0]) / D)
    sinais = []

    def sinal(nome, valor, leitura, pontos):
        sinais.append({"nome": nome, "valor": valor, "leitura": leitura, "pontos": int(round(pontos))})

    # 1. horário de dormir: o maior bloco de horas seguidas (dando a volta na meia-noite) quase sem ordens
    horas = Counter(datetime.fromtimestamp(t / 1000, timezone.utc).hour for t in ts)
    if n >= 100:
        mortas = [horas.get(h, 0) < 0.01 * n for h in range(24)]
        bloco = atual = 0
        for m in mortas + mortas:
            atual = atual + 1 if m else 0
            bloco = max(bloco, min(atual, 24))
        if bloco >= 5:
            sinal("Horário de dormir", f"{bloco} h seguidas paradas", "fica sempre as mesmas horas do dia sem operar, como quem dorme", -18)
        elif bloco == 0 and n >= 200:
            sinal("Horário de dormir", "nenhuma hora parada", "opera em todas as horas do dia, inclusive de madrugada", 18)
        else:
            sinal("Horário de dormir", f"{bloco} h seguidas paradas", "não tem um horário claro de parada", 4)

    # 2. horas ativas (UTC) com pelo menos 2 % das ordens
    ativas = sum(1 for h in range(24) if horas.get(h, 0) >= 0.02 * n)
    if ativas >= 20:
        sinal("Horas ativas", f"{ativas} de 24", "ordens espalhadas pelo dia inteiro", 8)
    elif ativas <= 12:
        sinal("Horas ativas", f"{ativas} de 24", "concentra as ordens em parte do dia", -8)
    else:
        sinal("Horas ativas", f"{ativas} de 24", "meio-termo", 0)

    # 3. ordens no fechamento de vela (segundo 0 a 2 do minuto); ao acaso daria ~5 %
    seg = np.asarray([(t // 1000) % 60 for t in ts])
    fech = float(np.mean(seg <= 2))
    if fech >= 0.25:
        sinal("Fechamento de vela", f"{fech:.0%} das ordens", "muitas ordens nos primeiros segundos do minuto: espera a vela fechar", 22)
    elif fech >= 0.12:
        sinal("Fechamento de vela", f"{fech:.0%} das ordens", "um pouco acima do acaso (5 %)", 8)
    else:
        sinal("Fechamento de vela", f"{fech:.0%} das ordens", "nada de especial (o acaso dá uns 5 %)", -4)

    # 4. rajadas: ordens em moedas diferentes no mesmo segundo; pico de ordens por minuto
    por_seg = defaultdict(set)
    for o in ords:
        por_seg[o["t"] // 1000].add(o["c"])
    multi = sum(1 for s in por_seg.values() if len(s) >= 2) / max(1, len(por_seg))
    por_min = Counter(t // 60000 for t in ts)
    pico = max(por_min.values())
    pts = 0
    leit = []
    if multi >= 0.05:
        pts += 15; leit.append(f"{multi:.0%} dos segundos com ordens em moedas diferentes ao mesmo tempo")
    if pico >= 20:
        pts += 10; leit.append(f"chegou a {pico} ordens num minuto (ou usa ordens escalonadas do site)")
    sinal("Rajadas", f"pico de {pico}/min", "; ".join(leit) if leit else "ritmo que dá para fazer na mão", pts if pts else -4)

    # 5. tamanho redondo (quantidade ou valor em dólares)
    red = float(np.mean([_redondo(o["z"]) or _redondo(round(o["n"], 2)) for o in ords]))
    if red >= 0.6:
        sinal("Tamanho redondo", f"{red:.0%} das ordens", "digita tamanhos redondos (0,5 · 100 · 1.000), jeito de pessoa", -15)
    elif red <= 0.2:
        sinal("Tamanho redondo", f"{red:.0%} das ordens", "tamanhos quebrados (0,4873...): calculados por programa ou digitados em dólares", 8)
    else:
        sinal("Tamanho redondo", f"{red:.0%} das ordens", "mistura de redondos e quebrados", 0)

    # 6. intervalos regulares: o intervalo mais comum (arredondado a 5 s) explica quanto das pausas?
    gaps = np.diff(ts) / 1000
    gaps = gaps[(gaps > 1) & (gaps < 6 * 3600)]
    if len(gaps) >= 20:
        moda, q = Counter(np.round(gaps / 5).astype(int)).most_common(1)[0]
        frac = q / len(gaps)
        if frac >= 0.2 and moda > 0 and moda * 5 <= 30:
            sinal("Intervalos regulares", f"{frac:.0%} a cada ~{moda * 5:.0f} s", "fatias de uma ordem grande a cada poucos segundos (TWAP do site ou robô)", 5)
        elif frac >= 0.2 and moda > 0:
            sinal("Intervalos regulares", f"{frac:.0%} a cada ~{moda * 5:.0f} s", "repete o mesmo intervalo entre ordens: agenda fixa", 15)
        else:
            sinal("Intervalos regulares", f"{frac:.0%} no intervalo mais comum", "intervalos variados", -3)

    # 7. ID próprio nas ordens (só existe nos fills coletados a partir de 03/11)
    com_cl = [o for o in ords if "cl" in o]
    if len(com_cl) >= 20:
        fc = float(np.mean([o["cl"] for o in com_cl]))
        if fc >= 0.8:
            sinal("ID próprio na ordem", f"{fc:.0%} das ordens", "numera as próprias ordens (comum em quem usa a API)", 10)
        elif fc <= 0.1:
            sinal("ID próprio na ordem", f"{fc:.0%} das ordens", "ordens sem ID próprio", -5)

    nota = max(0, min(100, 50 + sum(s["pontos"] for s in sinais)))
    rotulo = "Robô provável" if nota >= 65 else "Humano provável" if nota <= 35 else "Indefinido"
    return {"nota": nota, "rotulo": rotulo, "sinais": sinais, "ordens": n, "ordens_por_dia": round(n / dias, 1)}


CRITERIOS = [
    "Horário de dormir: maior bloco de horas seguidas com menos de 1 % das ordens (com 100 ordens ou mais). 5 h ou mais = humano (−18); nenhuma hora parada com 200 ordens ou mais = robô (+18); senão +4.",
    "Horas ativas: horas do dia com pelo menos 2 % das ordens. 20 ou mais = robô (+8); 12 ou menos = humano (−8).",
    "Fechamento de vela: ordens nos segundos 0 a 2 do minuto. 25 % ou mais = robô (+22); 12 % ou mais = +8; o acaso dá uns 5 %.",
    "Rajadas: ordens em moedas diferentes no mesmo segundo (5 % ou mais = +15) e 20 ou mais ordens num minuto (+10).",
    "Tamanho redondo: quantidade ou valor com até 2 algarismos significativos. 60 % ou mais = humano (−15); 20 % ou menos = robô (+8).",
    "Intervalos regulares: se 20 % ou mais das pausas têm o mesmo tamanho (±5 s): até 30 s = fatias de ordem grande (+5); mais que isso = agenda fixa de robô (+15).",
    "ID próprio na ordem (cloid): 80 % ou mais = +10; 10 % ou menos = −5 (só nos dados coletados a partir de 03/11).",
    "A nota começa em 50 e soma os pontos: 65 ou mais = Robô provável; 35 ou menos = Humano provável; entre os dois = Indefinido. Precisa de pelo menos 20 ordens.",
]
