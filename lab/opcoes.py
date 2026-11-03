"""Laboratório 5: vender opções de cripto (Deribit, dados públicos), sem dinheiro.

Duas estratégias, cada uma com US$ 1.000 de mentira, em BTC e em ETH:
- Put semanal ~10 % abaixo do preço ("garantida em dinheiro"): recebe o prêmio; se no vencimento o preço estiver abaixo
  do preço de exercício, paga a diferença (é como ser obrigado a comprar a moeda mais caro).
- Call coberta semanal ~10 % acima: tem a moeda e vende o direito de comprá-la mais caro; recebe o prêmio, mas se o
  preço passar do exercício, a alta acima dele fica com o comprador.
Vende pelo preço de compra do livro (bid), paga a taxa da Deribit (0,03 % da moeda, no máximo 12,5 % do prêmio) e liquida
pelo preço oficial de entrega (08:00 UTC). Quantidade fracionada (a Deribit exige no mínimo 0,1 BTC / 1 ETH na real).
"""
from __future__ import annotations

from datetime import datetime, timezone

DIA = 86400000
API = "https://www.deribit.com/api/v2/public/"
MESES = {m: i + 1 for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}
ESTRATEGIAS = [{"id": f"{tipo}-{moeda}", "tipo": tipo, "moeda": moeda} for tipo in ("put", "call") for moeda in ("BTC", "ETH")]
DISTANCIA = 0.10
CAPITAL = 1000.0


def ler_nome(nome: str) -> dict | None:
    """BTC-13NOV26-83000-P → moeda, vencimento (ms, 08:00 UTC), exercício, tipo."""
    try:
        moeda, data, k, t = nome.split("-")
        dia, mes, ano = int(data[:-5]), MESES[data[-5:-2]], 2000 + int(data[-2:])
        venc = int(datetime(ano, mes, dia, 8, tzinfo=timezone.utc).timestamp() * 1000)
        return {"moeda": moeda, "venc": venc, "k": float(k), "tipo": "put" if t == "P" else "call", "nome": nome}
    except (ValueError, KeyError):
        return None


def escolher(livro: list[dict], tipo: str, indice: float, agora: int) -> dict | None:
    """A opção do vencimento entre 5 e 9 dias, com exercício mais perto de 10 % fora do preço, que tenha comprador."""
    alvo = indice * (1 - DISTANCIA if tipo == "put" else 1 + DISTANCIA)
    opc = []
    for b in livro:
        x = ler_nome(b.get("instrument_name", ""))
        if not x or x["tipo"] != tipo or not b.get("bid_price"):
            continue
        dias = (x["venc"] - agora) / DIA
        if 5 <= dias <= 9:
            opc.append((abs(dias - 7), abs(x["k"] - alvo), x, b))
    if not opc:
        return None
    opc.sort(key=lambda o: (o[0], o[1]))
    _, _, x, b = opc[0]
    return {**x, "bid": float(b["bid_price"]), "mark": float(b.get("mark_price") or b["bid_price"]), "iv": b.get("mark_iv")}


def taxa(indice: float, qtd: float, premio_usd: float) -> float:
    return min(0.0003 * indice * qtd, 0.125 * premio_usd)


def novo(estrategia: dict, indice: float, agora: int) -> dict:
    e = {**estrategia, "inicio": agora, "caixa": CAPITAL, "moeda_qtd": 0.0, "aberta": None, "historico": [], "curva": []}
    if estrategia["tipo"] == "call":                    # call coberta: compra a moeda no começo
        e["moeda_qtd"] = CAPITAL / indice
        e["caixa"] = 0.0
    return e


def passo(e: dict, livro: list[dict], indice: float, entregas: dict[str, float], agora: int) -> None:
    """Uma rodada: liquida a vencida (se já tem o preço de entrega), abre a próxima e marca o patrimônio."""
    a = e["aberta"]
    if a and agora >= a["venc"]:
        data = datetime.fromtimestamp(a["venc"] / 1000, timezone.utc).strftime("%Y-%m-%d")
        s = entregas.get(data)
        if s is not None:
            paga = max(0.0, a["k"] - s) * a["qtd"] if a["tipo"] == "put" else max(0.0, s - a["k"]) * a["qtd"]
            e["caixa"] -= paga
            e["historico"].append({"nome": a["nome"], "venceu": a["venc"], "premio": round(a["premio"], 2), "pagou": round(paga, 2), "entrega": s, "k": a["k"]})
            e["aberta"] = a = None
    if not a:
        o = escolher(livro, e["tipo"], indice, agora)
        if o:
            patrimonio = e["caixa"] + e["moeda_qtd"] * indice
            qtd = patrimonio / o["k"] if e["tipo"] == "put" else e["moeda_qtd"]
            if qtd > 0:
                premio = o["bid"] * indice * qtd
                premio -= taxa(indice, qtd, premio)
                e["caixa"] += premio
                e["aberta"] = {"nome": o["nome"], "tipo": o["tipo"], "k": o["k"], "venc": o["venc"], "qtd": qtd, "premio": premio,
                               "iv": o["iv"], "aberta_em": agora, "indice_na_venda": indice}
    # patrimônio: caixa + moeda − o que custaria recomprar a opção vendida agora (preço de referência)
    devo = 0.0
    if e["aberta"]:
        b = next((x for x in livro if x.get("instrument_name") == e["aberta"]["nome"]), None)
        if b and b.get("mark_price") is not None:
            devo = float(b["mark_price"]) * indice * e["aberta"]["qtd"]
    pat = e["caixa"] + e["moeda_qtd"] * indice - devo
    if not e["curva"] or agora - e["curva"][-1][0] >= 6 * 3600 * 1000:
        e["curva"].append([agora, round(pat, 2)])
    e["curva"] = e["curva"][-400:]
    e["patrimonio"] = round(pat, 2)
    e["segurar"] = round(CAPITAL * indice / e.setdefault("indice_inicio", indice), 2)   # comparação: só ter a moeda
