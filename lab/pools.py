"""Laboratório 4: pools de liquidez e empréstimo em cascata (looping), sem dinheiro. Dados do DefiLlama (grátis).

Pools: separa o rendimento "de verdade" (taxas das trocas, apyBase) do "de prêmio" (token de incentivo, apyReward, que
costuma derreter e não entra na conta). Nas pools de duas moedas voláteis, calcula a perda impermanente com o preço das
duas: quando uma anda diferente da outra, a pool fica com mais da que caiu. A conta usa a fórmula da pool comum (50/50);
nas de faixa concentrada (Uniswap v3) a perda é maior.

Looping (Aave): deposita um token de staking de ETH (wstETH, weETH...), pega ETH emprestado, troca pelo token e deposita
de novo, L vezes. Rende L × (staking + depósito) − (L − 1) × juro do empréstimo. Se o token se descolar do ETH, liquida.
"""
from __future__ import annotations

import math

POOLS = "https://yields.llama.fi/pools"
EMPRESTIMO = "https://yields.llama.fi/lendBorrow"
PRECOS = "https://coins.llama.fi/chart/{moedas}?span=31&period=1d"
CADEIAS = {"Ethereum": "ethereum", "Arbitrum": "arbitrum", "Base": "base", "BSC": "bsc", "Polygon": "polygon", "Optimism": "optimism",
           "Avalanche": "avax", "Solana": "solana", "Sonic": "sonic", "Hyperliquid L1": "hyperliquid", "Unichain": "unichain", "Linea": "linea"}
EMPRESTA = {"aave-v3", "spark", "compound-v3", "morpho-blue", "fluid-lending", "sparklend", "euler-v2"}
LST = {"WSTETH": "STETH", "WEETH": "WEETH", "RETH": "RETH", "CBETH": "CBETH"}
PADRAO = {"tvl_minimo": 5_000_000, "dias_minimos": 30, "quantos": 10}


def boa(p: dict, f: dict) -> bool:
    return (p.get("tvlUsd") or 0) >= f["tvl_minimo"] and (p.get("count") or 0) >= f["dias_minimos"] and not p.get("outlier") and (p.get("apyBase") or 0) > 0


def _firme(p: dict) -> float:
    """Ordena pelo menor entre o rendimento de hoje e a média de 30 dias (um dia bom isolado não conta)."""
    return min(p.get("apyBase") or 0, p.get("apyMean30d") or p.get("apyBase") or 0)


def resumo(p: dict) -> dict:
    return {"id": p["pool"], "projeto": p["project"], "rede": p["chain"], "par": p["symbol"], "tvl": round(p.get("tvlUsd") or 0),
            "taxas_ano": round((p.get("apyBase") or 0) / 100, 4), "premio_ano": round((p.get("apyReward") or 0) / 100, 4),
            "media_30d": round((p.get("apyMean30d") or 0) / 100, 4), "meta": p.get("poolMeta"), "tokens": p.get("underlyingTokens") or []}


def estaveis(pools: list[dict], f: dict) -> list[dict]:
    ps = [p for p in pools if p.get("stablecoin") and p.get("ilRisk") == "no" and boa(p, f)]
    ps.sort(key=lambda p: -_firme(p))
    return [resumo(p) for p in ps[: f["quantos"]]]


def volateis(pools: list[dict], f: dict) -> list[dict]:
    ps = [p for p in pools if p.get("exposure") == "multi" and p.get("ilRisk") == "yes" and not p.get("stablecoin") and boa(p, f)
          and len(p.get("underlyingTokens") or []) == 2 and p["chain"] in CADEIAS]
    ps.sort(key=lambda p: -_firme(p))
    return [resumo(p) for p in ps[: f["quantos"]]]


def perda_impermanente(r: float) -> float:
    """r = quanto o preço de uma moeda mudou em relação à outra (1,2 = 20 %). Pool comum 50/50."""
    return 2 * math.sqrt(r) / (1 + r) - 1 if r > 0 else -1.0


def chave_preco(rede: str, token: str) -> str:
    return f"{CADEIAS[rede]}:{token}"


def com_perda(v: dict, precos: dict) -> dict:
    """Acrescenta a perda impermanente dos últimos 30 dias e o "líquido" (taxas do mês + perda)."""
    ks = [chave_preco(v["rede"], t) for t in v["tokens"]]
    serie = [((precos.get(k) or {}).get("prices") or []) for k in ks]
    if any(len(s) < 2 for s in serie):
        return {**v, "perda_30d": None, "liquido_30d": None}
    a0, a1 = serie[0][0]["price"], serie[0][-1]["price"]
    b0, b1 = serie[1][0]["price"], serie[1][-1]["price"]
    r = (a1 / a0) / (b1 / b0)
    il = perda_impermanente(r)
    return {**v, "perda_30d": round(il, 4), "liquido_30d": round(v["taxas_ano"] / 12 + il, 4),
            "moedas_30d": [round(a1 / a0 - 1, 4), round(b1 / b0 - 1, 4)]}


def loops(pools: list[dict], emprestimos: dict[str, dict]) -> list[dict]:
    """Looping de tokens de staking de ETH contra ETH nos protocolos de empréstimo."""
    staking = {}
    for p in pools:
        s = p.get("symbol", "").upper()
        if s in LST.values() and p.get("project") not in EMPRESTA and p.get("exposure") == "single":
            if s not in staking or (p.get("tvlUsd") or 0) > staking[s][1]:
                staking[s] = ((p.get("apyBase") or 0) / 100, p.get("tvlUsd") or 0)
    out = []
    for p in pools:
        if p.get("project") not in EMPRESTA:
            continue
        s = p.get("symbol", "").upper()
        if s not in LST:
            continue
        weth = next((q for q in pools if q.get("project") == p["project"] and q.get("chain") == p["chain"] and q.get("symbol", "").upper() in ("WETH", "ETH")
                     and q.get("poolMeta") == p.get("poolMeta")), None)
        if not weth:
            continue
        eb, ew = emprestimos.get(p["pool"], {}), emprestimos.get(weth["pool"], {})
        ltv, juro = eb.get("ltv") or 0, ew.get("apyBaseBorrow")
        if not ltv or juro is None or not ew.get("borrowable", True):
            continue
        stk = staking.get(LST[s], (0, 0))[0]
        dep = (p.get("apyBase") or 0) / 100
        juro = juro / 100
        max_l = 1 / (1 - ltv) if ltv < 1 else 10
        niveis = []
        for L in (2, 3, 4):
            if L > max_l * 0.9:
                continue
            liq = 1 - (L - 1) / (L * min(0.97, ltv + 0.03))
            niveis.append({"vezes": L, "ao_ano": round(L * (stk + dep) - (L - 1) * juro, 4), "descolamento_que_liquida": round(liq, 4)})
        if niveis:
            out.append({"protocolo": p["project"], "rede": p["chain"], "token": s, "staking": round(stk, 4), "deposito": round(dep, 4),
                        "juro_eth": round(juro, 4), "ltv": ltv, "tvl": round(p.get("tvlUsd") or 0), "sem_loop": round(stk + dep, 4), "niveis": niveis})
    out.sort(key=lambda x: -max(n["ao_ano"] for n in x["niveis"]))
    return out
