"""Laboratório 1: taxas de financiamento (funding), sem dinheiro.

A operação testada ("delta neutra"): comprar a moeda à vista e vender o mesmo valor no perpétuo da Hyperliquid.
O preço some da conta (um lado ganha o que o outro perde) e sobra o funding, que a Hyperliquid paga de hora em hora:
quando o funding é positivo, quem está vendido no perpétuo RECEBE. Quando fica negativo, paga.

Regras da carteira simulada (config.json → lab.funding):
- só moedas líquidas (volume do dia e posições abertas mínimos);
- entra nas que pagam mais na média das últimas 72 h (acima de um mínimo ao ano), até N posições do mesmo tamanho;
- sai quando a média das últimas 24 h cai abaixo de um mínimo ou o funding fica negativo por várias horas seguidas;
- paga taxas e escorregamento nas duas pontas ao entrar e ao sair;
- o perpétuo fica com 2× de alavancagem (metade da margem); anota quando uma alta teria exigido reforçar a margem.

As decisões só usam dados até a hora em que foram tomadas, então a mesma conta serve para o "teste no passado"
(últimos 30 dias, refeito a cada rodada) e para o "ao vivo" (desde o dia em que o laboratório começou).
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

HORA = 3600 * 1000
DIA = 24 * HORA
ANO_H = 24 * 365

PADRAO = {
    "capital": 1000.0,
    "posicoes": 5,
    "volume_minimo": 5_000_000,       # US$ negociados no dia (perpétuo)
    "abertas_minimo": 2_000_000,      # US$ em posições abertas
    "max_moedas": 60,
    "entrar_ao_ano": 0.20,            # média de 72 h acima de 20 % ao ano
    "sair_ao_ano": 0.05,              # média de 24 h abaixo de 5 % ao ano
    "horas_negativas_para_sair": 6,
    "troca_vantagem_ao_ano": 0.15,    # troca uma posição só se a nova pagar 15 pontos a mais
    "taxa_perp": 0.00045,             # Hyperliquid a mercado, por lado
    "taxa_spot": 0.0010,              # compra/venda à vista numa corretora comum, por lado
    "escorregamento": 0.0003,         # por lado, em cada ponta
    "alavancagem_perp": 2,
    "dias_passado": 30,
    "so_com_spot": True,              # só moedas que dá para comprar à vista de verdade (lista abaixo)
}

# Versão 2 (09/11/2026): a operação precisa COMPRAR a moeda à vista. Na versão 1 o teste escolhia moedas pequenas
# (USELESS, PONS, CASHCAT) que pagavam bem, mas que não têm mercado à vista fundo nas corretoras comuns: o teste
# não dava para repetir de verdade. Agora só entram moedas grandes, com mercado à vista nas maiores corretoras
# (e HYPE, à vista na própria Hyperliquid). Nomes como na Hyperliquid (kPEPE = mil PEPE).
COM_SPOT = {
    "BTC", "ETH", "SOL", "XRP", "BNB", "DOGE", "ADA", "AVAX", "LINK", "LTC", "DOT", "TRX", "BCH", "SUI", "TON", "NEAR",
    "APT", "ARB", "OP", "ATOM", "UNI", "AAVE", "HYPE", "ENA", "kPEPE", "WIF", "TAO", "SEI", "TIA", "INJ", "FIL", "ETC",
    "XLM", "HBAR", "ICP", "RENDER", "FET", "ONDO", "WLD", "JUP", "PENDLE", "LDO", "CRV", "POL", "ALGO", "STX", "IMX",
}


def cfg_de(cfg: dict) -> dict:
    return {**PADRAO, **(cfg.get("lab", {}).get("funding", {}))}


# ---------------- dados ----------------
class Banco:
    """Série por moeda: hora (ms) → [funding da hora, preço]. Guarda em lab/dados/funding/AAAA-MM.jsonl, uma linha
    por moeda e hora ([moeda, hora, funding, preço]); só acrescenta (o git guarda pouco)."""

    def __init__(self, pasta: Path):
        self.pasta = pasta
        self.s: dict[str, dict[int, list[float]]] = defaultdict(dict)
        if pasta.exists():
            for arq in sorted(pasta.glob("*.jsonl")):
                for linha in arq.read_text(encoding="utf-8").splitlines():
                    if linha.strip():
                        c, t, f, p = json.loads(linha)
                        self.s[c][t] = [f, p]

    def ultima(self, moeda: str) -> int:
        return max(self.s[moeda]) if self.s.get(moeda) else 0

    def acrescentar(self, linhas: list[list]) -> int:
        from datetime import datetime, timezone
        por_mes: dict[str, list[str]] = defaultdict(list)
        n = 0
        for c, t, f, p in linhas:
            if t in self.s[c]:
                continue
            self.s[c][t] = [f, p]
            por_mes[datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%Y-%m")].append(json.dumps([c, t, f, p], separators=(",", ":")))
            n += 1
        self.pasta.mkdir(parents=True, exist_ok=True)
        for mes, ls in por_mes.items():
            with (self.pasta / f"{mes}.jsonl").open("a", encoding="utf-8") as h:
                h.write("\n".join(ls) + "\n")
        return n


def universo(meta_ctx: list, p: dict) -> list[dict]:
    """Moedas líquidas, da mais negociada para a menos."""
    meta, ctxs = meta_ctx
    out = []
    for m, c in zip(meta.get("universe", []), ctxs):
        if m.get("isDelisted") or (p.get("so_com_spot") and m["name"] not in COM_SPOT):
            continue
        px = float(c.get("oraclePx") or c.get("markPx") or 0)
        vlm = float(c.get("dayNtlVlm") or 0)
        oi = float(c.get("openInterest") or 0) * px
        if vlm >= p["volume_minimo"] and oi >= p["abertas_minimo"]:
            out.append({"moeda": m["name"], "px": px, "volume": round(vlm), "abertas": round(oi),
                        "funding_agora": float(c.get("funding") or 0), "alav_max": m.get("maxLeverage")})
    out.sort(key=lambda x: -x["volume"])
    return out[: p["max_moedas"]]


def coletar(api, banco: Banco, moedas: list[str], agora: int, dias_inicio: int = 30) -> int:
    """Funding (já pago) e preço de cada hora desde a última guardada (ou dos últimos dias, na primeira vez)."""
    novas = 0
    for m in moedas:
        ini = banco.ultima(m) + 1 if banco.ultima(m) else agora - dias_inicio * DIA
        if agora - ini < HORA:
            continue
        fund: dict[int, float] = {}
        t = ini
        while t < agora:
            pag = api._post({"type": "fundingHistory", "coin": m, "startTime": int(t), "endTime": int(agora)}, 20) or []
            api.lim.gastar(math.ceil(len(pag) / 20))
            for r in pag:
                fund[int(r["time"]) // HORA * HORA] = float(r["fundingRate"])
            if len(pag) < 500:
                break
            t = max(int(r["time"]) for r in pag) + 1
        if not fund:
            continue
        precos = {int(v["t"]) // HORA * HORA: float(v["c"]) for v in api.velas(m, "1h", min(fund) - HORA, agora)}
        linhas, ult = [], None
        for h in sorted(fund):
            px = precos.get(h) or precos.get(h - HORA) or ult
            if px is None:
                continue
            ult = px
            linhas.append([m, h, fund[h], px])
        novas += banco.acrescentar(linhas)
    return novas


# ---------------- simulação ----------------
def _media(serie: dict[int, list[float]], h: int, horas: int) -> float | None:
    vs = [serie[t][0] for t in range(h - (horas - 1) * HORA, h + HORA, HORA) if t in serie]
    return sum(vs) / len(vs) if len(vs) >= horas * 0.6 else None


def simular(banco: Banco, moedas: list[str], inicio: int, fim: int, p: dict) -> dict:
    """Carteira simulada hora a hora entre inicio e fim. Só usa o que já tinha acontecido em cada hora."""
    cap = p["capital"]
    caixa = cap
    pos: dict[str, dict] = {}
    custo_lado = p["taxa_perp"] + p["taxa_spot"] + 2 * p["escorregamento"]   # as duas pontas, um lado
    recebido = custos = 0.0
    curva, trocas = [], []
    margem_avisos = 0
    tamanho = cap / p["posicoes"] / (1 + 1 / p["alavancagem_perp"])         # à vista + margem do perpétuo
    entrar_h, sair_h, vant_h = (p[k] / ANO_H for k in ("entrar_ao_ano", "sair_ao_ano", "troca_vantagem_ao_ano"))
    h = inicio // HORA * HORA
    while h <= fim:
        # 1) funding da hora nas posições abertas
        for m, x in list(pos.items()):
            r = banco.s[m].get(h)
            if not r:
                continue
            f, px = r
            pago = x["qtd"] * px * f            # vendido no perpétuo: recebe quando f > 0
            x["recebido"] += pago
            recebido += pago
            x["neg"] = x["neg"] + 1 if f < 0 else 0
            x["max_px"] = max(x["max_px"], px)
            if not x["aviso"] and px >= x["px0"] * (1 + 0.8 / p["alavancagem_perp"]):
                x["aviso"] = True
                margem_avisos += 1
        # 2) saídas
        for m, x in list(pos.items()):
            m24 = _media(banco.s[m], h, 24)
            r = banco.s[m].get(h)
            if (m24 is not None and m24 < sair_h) or x["neg"] >= p["horas_negativas_para_sair"] or (r is None and h - x["ult"] > 12 * HORA):
                px = (r or [0, x["px_ult"]])[1]
                c = x["qtd"] * px * custo_lado
                custos += c
                trocas.append({"moeda": m, "entrou": x["t0"], "saiu": h, "recebido": round(x["recebido"], 2), "custos": round(x["custo"] + c, 2)})
                del pos[m]
            elif r:
                x["ult"], x["px_ult"] = h, r[1]
        # 3) entradas (e trocas por uma bem melhor)
        cands = []
        for m in moedas:
            if m in pos or h not in banco.s[m]:
                continue
            m72 = _media(banco.s[m], h, 72)
            if m72 is not None and m72 >= entrar_h and banco.s[m][h][0] > 0:
                cands.append((m72, m))
        cands.sort(reverse=True)
        for m72, m in cands:
            if len(pos) >= p["posicoes"]:
                pior = min(pos, key=lambda k: _media(banco.s[k], h, 72) or 0)
                if m72 - (_media(banco.s[pior], h, 72) or 0) < vant_h:
                    break
                x = pos.pop(pior)
                px = banco.s[pior].get(h, [0, x["px_ult"]])[1]
                c = x["qtd"] * px * custo_lado
                custos += c
                trocas.append({"moeda": pior, "entrou": x["t0"], "saiu": h, "recebido": round(x["recebido"], 2), "custos": round(x["custo"] + c, 2), "troca": m})
            px = banco.s[m][h][1]
            c = tamanho * custo_lado
            custos += c
            pos[m] = {"qtd": tamanho / px, "px0": px, "px_ult": px, "max_px": px, "t0": h, "ult": h, "recebido": 0.0, "custo": c, "neg": 0, "aviso": False}
        saldo = caixa + recebido - custos
        if not curva or h - curva[-1][0] >= 6 * HORA or h + HORA > fim:
            curva.append([h, round(saldo, 2)])
        h += HORA
    horas = max(1, (fim - inicio) / HORA)
    lucro = recebido - custos
    return {
        "inicio": inicio, "fim": fim, "capital": cap, "saldo": round(cap + lucro, 2), "lucro": round(lucro, 2),
        "recebido": round(recebido, 2), "custos": round(custos, 2),
        "ao_ano": round(lucro / cap * ANO_H / horas, 4) if horas >= 24 else None,
        "pior_queda": round(_pior_queda(curva), 4),
        "posicoes": [{"moeda": m, "desde": x["t0"], "recebido": round(x["recebido"], 2), "custos": round(x["custo"], 2),
                      "alta_desde_entrada": round(x["max_px"] / x["px0"] - 1, 4), "aviso_margem": x["aviso"]} for m, x in pos.items()],
        "trocas": trocas[-30:], "n_trocas": len(trocas), "avisos_margem": margem_avisos,
        "curva": curva,
    }


def _pior_queda(curva: list) -> float:
    pico, pior = None, 0.0
    for _, v in curva:
        pico = v if pico is None else max(pico, v)
        if pico:
            pior = max(pior, (pico - v) / pico)
    return pior


def ranking(banco: Banco, uni: list[dict], agora_h: int) -> list[dict]:
    """As moedas que mais pagam: média de 7 dias, das últimas 24 h e quantas horas foram positivas."""
    out = []
    for u in uni:
        s = banco.s.get(u["moeda"], {})
        horas = [s[t][0] for t in range(agora_h - 167 * HORA, agora_h + HORA, HORA) if t in s]
        if len(horas) < 24:
            continue
        ult24 = [s[t][0] for t in range(agora_h - 23 * HORA, agora_h + HORA, HORA) if t in s]
        out.append({"moeda": u["moeda"], "ao_ano_7d": round(sum(horas) / len(horas) * ANO_H, 4),
                    "ao_ano_24h": round(sum(ult24) / max(1, len(ult24)) * ANO_H, 4),
                    "ao_ano_agora": round(u["funding_agora"] * ANO_H, 4),
                    "positivas_7d": round(sum(1 for v in horas if v > 0) / len(horas), 3),
                    "volume": u["volume"], "abertas": u["abertas"]})
    out.sort(key=lambda x: -x["ao_ano_7d"])
    return out
