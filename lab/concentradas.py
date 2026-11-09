"""Laboratório 9: pools de liquidez concentrada (DLMM da Meteora, Solana), sem dinheiro.

Versão 2 (09/11/2026, depois do estudo de ~150 pools em 8 dias de velas de 1 h, ensaio coleta_pools/estudo_pools):
a versão 1 trocava metade do SOL pela moeda na entrada (custo de ~1 % numa pool de taxa alta) e escolhia só a maior
taxa do dia, que quase sempre é uma moeda sendo vendida em massa. No estudo, isso perdeu ~2 % por posição na metade
ruim do período. Agora:
  - depósito só em SOL/USDC, numa faixa logo abaixo do preço (sem troca nenhuma: custo só da rede). Se a moeda cai
    para dentro da faixa, a posição recebe a taxa e vai virando moeda; se o preço sobe, a posição fica toda em SOL
    (não perde nada) e sai para abrir de novo no preço novo;
  - só pools com o preço calmo: o balanço da última 24 h (desvio das variações de 1 h) abaixo de 2 % por hora,
    e com pelo menos 24 h de vida; entre essas, a maior taxa sobre o dinheiro da pool nas últimas 24 h.
No estudo, essa regra ficou em −0,06 % na metade ruim e +1,3 % (faixa de 10 %) na boa, por posição de até 24 h.
O teste ao vivo é que confirma: o estudo usou velas de 1 h e o dinheiro da pool de agora.

Três faixas abaixo do preço da entrada, US$ 1.000 cada, até 3 pools por faixa:
  estreita (preço até −10 %), média (até −30 %), larga (até −60 %).
Taxa: a taxa da pool sobre o dinheiro dela na última hora (fee_tvl_ratio 1h), vezes o quanto a faixa concentra o
dinheiro (Uniswap v3, em relação a ±30 %), só nas velas de 5 min em que o preço ficou dentro da faixa.
Saída: quando uma vela de 5 min fecha abaixo da faixa, quando o preço fica 3 h acima dela (versão 3; antes saía
na hora e pagava entrada e saída toda hora) ou depois de 24 h. Versão 3: o valor é medido em SOL/USDC no preço do SOL
da entrada (o teste mede a pool; a variação do SOL é outra coisa) e a rede custa 0,02 % por ponta. Custo de saída: a taxa da pool + 0,2 % só
sobre a parte que virou moeda (é ela que precisa ser vendida).
"""
from __future__ import annotations

import math

VERSAO = 3
CAPITAL = 1000.0
HORA = 3600 * 1000
API = "https://dlmm.datapi.meteora.ag"
FAIXAS = {"estreita": 0.05, "media": 0.15, "larga": 0.30}   # largura da faixa abaixo do preço = 2 × r
NOMES = {"estreita": "Faixa estreita (até −10%)", "media": "Faixa média (até −30%)", "larga": "Faixa larga (até −60%)"}
POR_FAIXA = 3
PRAZO_H = 24
ESCORREGA = 0.002
QUOTES = {"SOL", "USDC"}
REDE = 0.0002          # taxa da rede para abrir ou fechar (sem troca; na Solana custa centavos)
ESPERA_ACIMA_H = 3     # preço acima da faixa (todo em SOL, sem perda): espera 3 h antes de reabrir no preço novo
BALANCO_MAX = 0.02     # desvio das variações de 1 h nas últimas 24 h
TVL_MIN, VOLUME_MIN = 10_000, 50_000


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
        if p.get("is_blacklisted") or y not in QUOTES or num(p.get("tvl")) < TVL_MIN or num((p.get("volume") or {}).get("24h")) < VOLUME_MIN:
            continue
        if num(p.get("current_price")) <= 0 or num((p.get("token_y") or {}).get("price")) <= 0:
            continue
        out.append(p)
    return sorted(out, key=lambda p: -num((p.get("fee_tvl_ratio") or {}).get("24h")))


def balanco(closes: list[float]) -> float | None:
    """Desvio das variações de 1 h (log) nas últimas 24 velas; None se a pool tem menos de 24 h de velas."""
    cs = [c for c in closes if c > 0][-25:]
    if len(cs) < 25:
        return None
    rets = [math.log(cs[i] / cs[i - 1]) for i in range(1, len(cs))]
    m = sum(rets) / len(rets)
    return math.sqrt(sum((r - m) ** 2 for r in rets) / len(rets))


def parte_moeda(L: float, p: float, a: float, b: float) -> float:
    """Fração do valor da posição que está na moeda (o resto está em SOL/USDC)."""
    v = valor_y(L, p, a, b)
    if v <= 0 or p >= b:
        return 0.0
    if p <= a:
        return 1.0
    sp, sb = math.sqrt(p), math.sqrt(b)
    return L * (1 / sp - 1 / sb) * p / v


def liquidez(valor_y: float, p0: float, a: float, b: float) -> float:
    """L de uma posição com valor_y (em unidades da moeda de cotação) no preço p0, faixa [a, b]."""
    sp, sa, sb = math.sqrt(min(p0, b)), math.sqrt(a), math.sqrt(b)
    por_l = (1 / sp - 1 / sb) * p0 + (sp - sa)          # valor (em y) de L = 1 (no topo da faixa: tudo em y)
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
    taxa = num(pool.get("dynamic_fee_pct") or (pool.get("pool_config") or {}).get("base_fee_pct")) / 100
    custo = REDE                                         # só SOL/USDC, sem troca
    liquido = dolares * (1 - custo)
    a, b = p0 * (1 - 2 * r), p0                          # faixa logo abaixo do preço
    return {"pool": pool["address"], "nome": pool.get("name", ""), "token_x": pool["token_x"]["address"], "faixa": faixa,
            "entrou": agora, "ult_t": agora, "p0": p0, "a": a, "b": b, "L": liquidez(liquido / py, p0, a, b), "py": py,
            "p": p0, "taxas": 0.0, "custo_entrada": round(dolares * custo, 4), "dolares": dolares, "taxa_pct": taxa + ESCORREGA,
            "fora_min": 0, "dentro_min": 0}


def valor_usd(pos: dict, p: float | None = None, py: float | None = None) -> float:
    return valor_y(pos["L"], pos["p"] if p is None else p, pos["a"], pos["b"]) * (pos["py"] if py is None else py) + pos["taxas"]


def andar(pos: dict, velas: list, ftvl_1h_pct: float, py: float, agora: int) -> str | None:
    """Passa as velas de 5 min (preço de x em y) desde a última vez: recebe a taxa enquanto dentro da faixa.

    Devolve o motivo da saída ("saiu da faixa" ou "24 horas") ou None se continua."""
    # versão 3: o valor fica em SOL/USDC no preço do SOL da entrada (o teste mede a pool, não a variação do SOL)
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
            pos["acima_desde"] = None
        elif c < pos["a"]:
            pos["fora_min"] += 5
            return "caiu abaixo da faixa"
        else:                                            # acima: todo em SOL, não perde nada; só reabre se ficar lá
            pos["fora_min"] += 5
            pos["acima_desde"] = pos.get("acima_desde") or t
            if t + 5 * 60 * 1000 - pos["acima_desde"] >= ESPERA_ACIMA_H * HORA:
                return "subiu e ficou 3 h acima: reabre no preço novo"
        if pos["ult_t"] >= pos["entrou"] + PRAZO_H * HORA:
            return "24 horas"
    if agora >= pos["entrou"] + PRAZO_H * HORA:
        return "24 horas"
    return None


def fechar(pos: dict) -> float:
    """Dólares que voltam ao caixa: valor da posição + taxas − custo de saída (vender a parte que virou moeda + rede)."""
    v = valor_usd(pos)
    moeda = parte_moeda(pos["L"], pos["p"], pos["a"], pos["b"]) * (v - pos["taxas"])
    return v - moeda * pos["taxa_pct"] - v * REDE
