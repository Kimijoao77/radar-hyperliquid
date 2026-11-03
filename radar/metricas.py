"""Números de cada carteira e o teste de sorte x habilidade.

Sorte x habilidade, em português simples:
1. Teste estatístico por operação: se o ganho médio fosse zero, qual a chance de ver um resultado
   tão bom só por acaso (p-valor por bootstrap, sorteando as operações com reposição)?
2. Correção por olhar muitas carteiras (Benjamini-Hochberg, o "q"): entre milhares de carteiras,
   algumas parecem gênios só por sorte. O q já desconta isso.
3. Dependência de uma tacada: se tirar a melhor operação e o lucro some, foi sorte.
4. Constância: semanas positivas e as duas metades do período no azul.
5. O teste que mais vale: o desempenho DEPOIS que a carteira entrou na observação (fora da amostra).
"""
from __future__ import annotations

import math
from collections import defaultdict
from statistics import median

import numpy as np

from .trades import Operacao

SEMANA_MS = 7 * 24 * 3600 * 1000


def p_bootstrap(retornos: list[float], n: int = 4000, semente: int = 7) -> float:
    """Chance (unilateral) de a média ser tão alta se o ganho real fosse zero."""
    r = np.asarray(retornos, dtype=float)
    if len(r) < 5 or not np.isfinite(r).all():
        return 1.0
    media = r.mean()
    centrado = r - media
    rng = np.random.default_rng(semente)
    amostras = rng.choice(centrado, size=(n, len(r)), replace=True).mean(axis=1)
    return float((np.sum(amostras >= media) + 1) / (n + 1))


def benjamini_hochberg(ps: dict[str, float]) -> dict[str, float]:
    """q-valores (taxa de falsas descobertas) para vários testes ao mesmo tempo."""
    itens = sorted(ps.items(), key=lambda kv: kv[1])
    m = len(itens)
    q, menor = {}, 1.0
    for i in range(m - 1, -1, -1):
        chave, p = itens[i]
        menor = min(menor, p * m / (i + 1))
        q[chave] = min(1.0, menor)
    return q


def numeros(ops: list[Operacao]) -> dict:
    """Estatísticas das operações fechadas e completas."""
    fs = [o for o in ops if o.fechada and not o.parcial]
    n = len(fs)
    if not n:
        return {"n": 0}
    res = [o.resultado for o in fs]
    ret = [o.retorno for o in fs]
    ganhos = [x for x in res if x > 0]
    perdas = [x for x in res if x < 0]
    total = sum(res)
    t0, t1 = min(o.t0 for o in fs), max(o.t1 for o in fs)
    dias = max(1.0, (t1 - t0) / 86400000)
    # semanas
    sem = defaultdict(float)
    for o in fs:
        sem[o.t1 // SEMANA_MS] += o.resultado
    sem_pos = sum(1 for v in sem.values() if v > 0) / len(sem) if sem else 0
    # metades
    ordem = sorted(fs, key=lambda o: o.t1)
    meio = n // 2
    m1 = sum(o.resultado for o in ordem[:meio]) if meio else 0
    m2 = sum(o.resultado for o in ordem[meio:])
    # curva e queda máxima
    acum, pico, queda = 0.0, 0.0, 0.0
    curva = []
    for o in ordem:
        acum += o.resultado
        pico = max(pico, acum)
        queda = max(queda, pico - acum)
        curva.append((o.t1, round(acum, 2)))
    melhor = max(res)
    top = sorted(res, reverse=True)[: max(1, math.ceil(n * 0.05))]
    r = np.asarray(ret)
    dp = float(r.std(ddof=1)) if n > 1 else 0.0
    return {
        "n": n,
        "dias": round(dias, 1),
        "por_dia": round(n / dias, 2),
        "acerto": round(len(ganhos) / n, 3),
        "resultado": round(total, 2),
        "ganho_medio": round(sum(ganhos) / len(ganhos), 2) if ganhos else 0,
        "perda_media": round(sum(perdas) / len(perdas), 2) if perdas else 0,
        "fator_lucro": round(sum(ganhos) / -sum(perdas), 2) if perdas else (99.0 if ganhos else 0),
        "retorno_medio": round(float(r.mean()), 5),
        "t": round(float(r.mean()) / (dp / math.sqrt(n)), 2) if dp > 0 and n > 1 else 0,
        "p": round(p_bootstrap(ret), 4) if n >= 5 else 1.0,
        "sem_melhor": round(total - melhor, 2),
        "peso_top5": round(sum(top) / total, 2) if total > 0 else None,
        "semanas": len(sem),
        "semanas_positivas": round(sem_pos, 3),
        "metade1": round(m1, 2), "metade2": round(m2, 2),
        "queda_max": round(queda, 2),
        "duracao_mediana_min": round(median(o.duracao_min for o in fs), 1),
        "maker": round(sum(o.maker for o in fs) / max(1, sum(o.fills for o in fs)), 3),
        "liquidacoes": sum(1 for o in fs if o.liquidada),
        "taxas": round(sum(o.taxas for o in fs), 2),
        "curva": curva,
    }


def copiavel(m: dict, cfg: dict) -> tuple[bool, str]:
    """Só informação (não descarta nem muda a classe): dá para copiar com atraso de segundos/minutos e ordens pequenas?"""
    if not m.get("n"):
        return True, ""
    if m["por_dia"] > cfg["max_operacoes_por_dia"]:
        return False, f"{m['por_dia']:.0f} operações por dia: rápido demais para copiar"
    if m["duracao_mediana_min"] < cfg["duracao_mediana_minima_min"]:
        return False, f"segura as posições só {m['duracao_mediana_min']:.0f} min (mediana): o atraso da cópia come o lucro"
    if m["maker"] > cfg["max_maker_com_duracao_curta"] and m["duracao_mediana_min"] < 60:
        return False, "quase só ordens limitadas e posições curtas: cara de market maker"
    return True, ""


def fq(q: float) -> str:
    return "menos de 0,001" if q < 0.001 else f"{q:.3f}".replace(".", ",")


def classificar(geral: dict, depois: dict, q: float | None, cfg: dict) -> tuple[str, str]:
    """Classe e o motivo, em português simples. Dar ou não para copiar NÃO entra aqui (desde 03/11 o João decide):
    vai como informação à parte (copiavel)."""
    n = geral.get("n", 0)
    if n < cfg["min_operacoes"]:
        return "observando", f"só {n} operações fechadas; precisa de {cfg['min_operacoes']} para julgar"
    if geral["resultado"] <= 0:
        return "perdendo", "no prejuízo depois das taxas"
    if geral["sem_melhor"] <= 0:
        return "sorte", "o lucro vem de uma operação só: sem a melhor, fica no prejuízo"
    if geral.get("peso_top5") and geral["peso_top5"] > 1.0:
        return "sorte", "as 5 % melhores operações valem mais que o lucro inteiro"
    nd = depois.get("n", 0)
    if nd >= cfg["min_operacoes_acompanhadas"] and depois.get("resultado", 0) <= 0:
        return "sorte", f"depois que entrou no radar ({nd} operações) passou a perder"
    qq = 1.0 if q is None else q
    firme = (qq <= cfg["q_maximo_habilidade"] and geral["fator_lucro"] >= cfg["fator_lucro_minimo"]
             and geral["semanas_positivas"] >= cfg["semanas_positivas_minimo"] and geral["metade1"] > 0 and geral["metade2"] > 0)
    if firme and nd >= cfg["min_operacoes_acompanhadas"]:
        return "habilidade", f"lucro consistente (q = {fq(qq)}) e continuou ganhando depois que entrou no radar"
    if firme:
        return "promissora", f"números fortes (q = {fq(qq)}), falta confirmar no período acompanhado ({nd}/{cfg['min_operacoes_acompanhadas']} operações)"
    if qq <= cfg["q_maximo_promissora"]:
        return "promissora", f"tende a ganhar (q = {fq(qq)}), mas ainda sem constância suficiente"
    return "sorte", f"lucro dentro do que o acaso explica (q = {fq(qq)})"
