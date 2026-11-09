"""Laboratório 4: pools de liquidez e empréstimo em cascata (looping), sem dinheiro. Dados do DefiLlama (grátis).

Pools: separa o rendimento "de verdade" (taxas das trocas, apyBase) do "de prêmio" (token de incentivo, apyReward, que
costuma derreter e não entra na conta). Nas pools de duas moedas voláteis, calcula a perda impermanente com o preço das
duas: quando uma anda diferente da outra, a pool fica com mais da que caiu. A conta usa a fórmula da pool comum (50/50);
nas de faixa concentrada (Uniswap v3) a perda é maior.

Looping (Aave): deposita um token de staking de ETH (wstETH, weETH...), pega ETH emprestado, troca pelo token e deposita
de novo, L vezes. Rende L × (staking + depósito) − (L − 1) × juro do empréstimo. Se o token se descolar do ETH, liquida.

Versão 2 da carteira (09/11/2026): "protegida". Na versão 1 os pares que oscilam e o looping seguiam o preço do ETH (e o
looping nem contava esse preço). Agora cada um tem uma venda no perpétuo da Hyperliquid do tamanho da parte em moeda
volátil, refeita a cada rodada: o preço some da conta e sobra a taxa das trocas (ou o rendimento do looping), mais o
funding que a venda recebe, menos os custos. Pares só com um lado estável e o outro com perpétuo na Hyperliquid.
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
ESTAVEIS = {"USDC", "USDT", "DAI", "USDS", "USDE", "SUSDE", "FDUSD", "PYUSD", "USDC.E", "USDT0", "USD₮0", "GHO", "FRAX", "LUSD",
            "CRVUSD", "USD0", "RLUSD", "USDBC", "USDBC", "SUSDS", "USDTB", "USDG"}
VERSAO_CARTEIRA = 2
MARGEM_PAR = 0.2          # par protegido: 80 % na pool, 20 % de margem para vender metade (a parte volátil) no perpétuo (2×)
MARGEM_LOOP = 1 / 3       # looping protegido: 2/3 no looping, 1/3 de margem para vender o valor todo em ETH (2×)
CUSTO_PROTECAO = 0.00015 + 0.0001   # ordem limitada na Hyperliquid + escorregamento, por lado, a cada ajuste


def moeda_perp(simbolo: str, perps: set[str]) -> str | None:
    """WETH → ETH, WBTC/cbBTC → BTC...: a moeda do perpétuo da Hyperliquid que protege o token, se houver."""
    s = simbolo.upper().replace(".E", "")
    if s in ("CBBTC", "TBTC", "WBTC", "BTCB"):
        s = "BTC"
    elif s in ("WSTETH", "WEETH", "STETH", "RETH", "CBETH", "WETH"):
        s = "ETH"
    elif s.startswith("W") and s[1:] in perps:
        s = s[1:]
    return s if s in perps else None


def volateis_protegiveis(pools: list[dict], f: dict, perps: set[str]) -> list[dict]:
    """Pares com um lado estável e o outro com perpétuo na Hyperliquid (dá para vender a parte volátil), sem repetir moeda."""
    out, vistas = [], set()
    ps = [p for p in pools if p.get("exposure") == "multi" and p.get("ilRisk") == "yes" and not p.get("stablecoin") and boa(p, f)
          and len(p.get("underlyingTokens") or []) == 2 and p["chain"] in CADEIAS]
    ps.sort(key=lambda p: -_firme(p))
    for p in ps:
        partes = [x.strip().upper() for x in (p.get("symbol") or "").split("-")]
        if len(partes) != 2:
            continue
        est = [x for x in partes if x in ESTAVEIS]
        vol = [x for x in partes if x not in ESTAVEIS]
        if len(est) != 1 or len(vol) != 1:
            continue
        m = moeda_perp(vol[0], perps)
        if not m or m in vistas:
            continue
        vistas.add(m)
        out.append({**resumo(p), "moeda_perp": m, "volatil": partes.index(vol[0])})
        if len(out) >= f["quantos"]:
            break
    return out


def sem_repetir(lista: list[dict], n: int) -> list[dict]:
    """Os n primeiros sem repetir o mesmo token no mesmo projeto (na v1 a mesma moeda da Pendle entrou duas vezes)."""
    out, vistos = [], set()
    for v in lista:
        k = (v["par"], v["projeto"])
        if k in vistos:
            continue
        vistos.add(k)
        out.append(v)
        if len(out) >= n:
            break
    return out


def valor_protegido(fotos: list[dict], item: dict, parte: float, ano_ms: float) -> dict:
    """Refaz o item protegido foto a foto: pool (ou looping) + venda no perpétuo ajustada a cada rodada + funding − custos.
    Cada foto guarda [rendimento ao ano, preço do token volátil] e o funding somado desde a foto anterior."""
    margem = parte * (MARGEM_PAR if item["tipo"] == "volatil" else MARGEM_LOOP)
    lado = 0.5 if item["tipo"] == "volatil" else 1.0       # quanto do valor está na moeda volátil
    v0 = parte - margem
    prim = ult = None
    rend = 1.0
    venda = pnl = fund = custos = 0.0
    valor_pos = v0
    for ft in fotos:
        x = ft["v"].get(item["id"])
        if not x or x[1] is None:
            continue
        px = x[1]
        if prim is None:
            prim, ult = (ft["t"], x), (ft["t"], x)
            venda = v0 * lado
            custos += venda * CUSTO_PROTECAO
            continue
        if ult[1][0] is not None:
            rend *= 1 + ult[1][0] * (ft["t"] - ult[0]) / ano_ms
        r = px / prim[1][1]
        valor_pos = v0 * (math.sqrt(r) if item["tipo"] == "volatil" else r) * rend
        pnl += -venda * (px / ult[1][1] - 1)
        fund += venda * (ft.get("f") or {}).get(item["moeda_perp"], 0.0)
        nova = valor_pos * lado
        custos += abs(nova - venda) * CUSTO_PROTECAO
        venda = nova
        ult = (ft["t"], x)
    total = valor_pos + margem + pnl + fund - custos
    return {"valor": round(total, 2), "taxas": round((v0 * (rend - 1)), 2), "moedas": round(valor_pos - v0 * rend, 2),
            "protecao": round(pnl, 2), "funding": round(fund, 2), "custos": round(custos, 2)}


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
