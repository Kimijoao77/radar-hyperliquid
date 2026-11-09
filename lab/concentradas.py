"""Laboratório 9: pools de liquidez concentrada (DLMM da Meteora, Solana), sem dinheiro.

As pools que mostram "3.000 % ao mês" são pares de moedas novas com volume enorme e liquidez numa faixa estreita de
preço. O número da tela é a taxa das últimas 24 h multiplicada; aqui o teste recebe a taxa de verdade, hora a hora,
só enquanto o preço fica dentro da faixa, e paga a perda quando o preço anda (a moeda que cai fica toda com você).

Três faixas em volta do preço da entrada, US$ 1.000 cada, até 3 pools por faixa:
  estreita ±5 %, média ±15 %, larga ±30 %.
Escolha: as pools com a maior taxa sobre o dinheiro depositado nas últimas 24 h, com pelo menos US$ 50 mil de
liquidez e US$ 500 mil de volume no dia, par com SOL ou USDC, fora da lista negra da Meteora.
Taxa: a taxa da pool sobre o dinheiro dela na última hora (fee_tvl_ratio 1h), vezes o quanto a faixa concentra
o dinheiro em relação a uma faixa de ±30 % (a média das posições na DLMM, suposição do teste): 5,8× na estreita,
2× na média e 1× na larga, vezes a parte da hora em que o preço ficou dentro da faixa (velas de 5 min).
Saída: quando uma vela de 5 min fecha fora da faixa (sai naquele preço) ou depois de 24 h; aí abre de novo na pool
que estiver no topo. Custos: metade do dinheiro é trocada na entrada e na saída (paga a taxa da pool) + 0,2 % de
escorregamento e rede em cada ponta.
O valor da posição segue a conta da liquidez concentrada (Uniswap v3): abaixo da faixa vira toda a moeda,
acima vira todo SOL/USDC. Em dólar, o SOL também conta (preço do SOL do momento).
"""
from __future__ import annotations

import math

VERSAO = 1
CAPITAL = 1000.0
HORA = 3600 * 1000
API = "https://dlmm.datapi.meteora.ag"
FAIXAS = {"estreita": 0.05, "media": 0.15, "larga": 0.30}
NOMES = {"estreita": "Faixa estreita (±5%)", "media": "Faixa média (±15%)", "larga": "Faixa larga (±30%)"}
POR_FAIXA = 3
PRAZO_H = 24
ESCORREGA = 0.002
QUOTES = {"SOL", "USDC"}


def eficiencia(r: float) -> float:
    """Quanto uma faixa ±r concentra o dinheiro em relação à faixa inteira (Uniswap v3)."""
    return 1 / (1 - ((1 - r) / (1 + r)) ** 0.25)


FATOR = {k: eficiencia(r) / eficiencia(0.30) for k, r in FAIXAS.items()}


def num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def escolher(pools: list[dict]) -> list[dict]:
    """As pools elegíveis, da maior taxa sobre o dinheiro (24 h) para a menor."""
    out = []
    for p in pools:
        y = (p.get("token_y") or {}).get("symbol", "").upper()
        if p.get("is_blacklisted") or y not in QUOTES or num(p.get("tvl")) < 50_000 or num((p.get("volume") or {}).get("24h")) < 500_000:
            continue
        if num(p.get("current_price")) <= 0 or num((p.get("token_y") or {}).get("price")) <= 0:
            continue
        out.append(p)
    return sorted(out, key=lambda p: -num((p.get("fee_tvl_ratio") or {}).get("24h")))


def liquidez(valor_y: float, p0: float, a: float, b: float) -> float:
    """L de uma posição com valor_y (em unidades da moeda de cotação) no preço p0, faixa [a, b]."""
    sp, sa, sb = math.sqrt(p0), math.sqrt(a), math.sqrt(b)
    por_l = (1 / sp - 1 / sb) * p0 + (sp - sa)          # valor (em y) de L = 1
    return valor_y / por_l


def valor_y(L: float, p: float, a: float, b: float) -> float:
    """Valor da posição em unidades de y no preço p."""
    sa, sb = math.sqrt(a), math.sqrt(b)
    if p <= a:
        return L * (1 / sa - 1 / sb) * p
    if p >= b:
        return L * (sb - sa)
    sp = math.sqrt(p)
    return L * (1 / sp - 1 / sb) * p + L * (sp - sa)


def abrir(pool: dict, faixa: str, dolares: float, agora: int) -> dict:
    r = FAIXAS[faixa]
    p0, py = num(pool["current_price"]), num(pool["token_y"]["price"])
    custo = 0.5 * num(pool.get("dynamic_fee_pct") or (pool.get("pool_config") or {}).get("base_fee_pct")) / 100 + ESCORREGA
    liquido = dolares * (1 - custo)
    a, b = p0 * (1 - r), p0 * (1 + r)
    return {"pool": pool["address"], "nome": pool.get("name", ""), "token_x": pool["token_x"]["address"], "faixa": faixa,
            "entrou": agora, "ult_t": agora, "p0": p0, "a": a, "b": b, "L": liquidez(liquido / py, p0, a, b), "py": py,
            "p": p0, "taxas": 0.0, "custo_entrada": round(dolares * custo, 4), "dolares": dolares, "taxa_pct": custo,
            "fora_min": 0, "dentro_min": 0}


def valor_usd(pos: dict, p: float | None = None, py: float | None = None) -> float:
    return valor_y(pos["L"], pos["p"] if p is None else p, pos["a"], pos["b"]) * (pos["py"] if py is None else py) + pos["taxas"]


def andar(pos: dict, velas: list, ftvl_1h_pct: float, py: float, agora: int) -> str | None:
    """Passa as velas de 5 min (preço de x em y) desde a última vez: recebe a taxa enquanto dentro da faixa.

    Devolve o motivo da saída ("saiu da faixa" ou "24 horas") ou None se continua."""
    pos["py"] = py or pos["py"]
    vs = sorted(([int(v[0] * 1000) if v[0] < 1e12 else int(v[0]), float(v[4])] for v in velas), key=lambda v: v[0])
    taxa_5min = max(0.0, ftvl_1h_pct) / 100 / 12 * FATOR[pos["faixa"]]
    for t, c in vs:
        if t < pos["ult_t"] or t + 5 * 60 * 1000 > agora:
            continue
        pos["ult_t"] = t + 5 * 60 * 1000
        pos["p"] = c
        if pos["a"] <= c <= pos["b"]:
            pos["taxas"] += valor_y(pos["L"], c, pos["a"], pos["b"]) * pos["py"] * taxa_5min
            pos["dentro_min"] += 5
        else:
            pos["fora_min"] += 5
            return "saiu da faixa"
        if pos["ult_t"] >= pos["entrou"] + PRAZO_H * HORA:
            return "24 horas"
    if agora >= pos["entrou"] + PRAZO_H * HORA:
        return "24 horas"
    return None


def fechar(pos: dict) -> float:
    """Dólares que voltam ao caixa: valor da posição + taxas − custo de saída."""
    return valor_usd(pos) * (1 - pos["taxa_pct"])
