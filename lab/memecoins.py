"""Laboratório 8: memecoins da Solana compradas no lançamento (pump.fun), sem dinheiro.

Fonte: GeckoTerminal (grátis, sem conta): as pools que acabaram de nascer, os números delas e as velas de 5 minutos do
preço. A pump.fun lança dezenas de moedas por minuto; quase todas morrem em minutos (no ensaio de 09/11, das 61 moedas
de uns 3 minutos, nenhuma ainda tinha compradores novos 6 minutos depois).

Duas estratégias, de hora em hora, com o mesmo caixa:
  - No lançamento: das moedas que nasceram nos últimos minutos (ainda na curva de preço da pump.fun, par com SOL),
    compra a mais disputada se tiver pelo menos 10 compradores diferentes, mais compras que vendas e US$ 500 de volume.
  - Depois da 1ª hora: volta nas moedas vistas na rodada anterior (com 1 hora de vida) e compra a mais disputada se ela
    sobreviveu e cresceu: pelo menos 50 compradores na hora, mais compras que vendas, US$ 10 mil de volume e preço 2×
    o de quando nasceu.
Cada compra usa 1 % do patrimônio (no máximo 1 por estratégia por hora e 8 abertas de cada) e paga 3 % de custo (taxa da
pump.fun, do robô de compra e o escorregamento). Vende metade quando dobra (2×) e o resto a 5×; vende tudo se cair 50 %
(depois de dobrar, se voltar ao preço de compra) ou em 24 horas. Cada venda paga 3 % de custo.

As vendas usam as velas de 5 minutos: se a parada e o alvo aparecem na mesma vela, conta a parada (o pior caso). Se o
preço despenca mais de metade além da parada numa vela só (o dono vendeu tudo, por exemplo), a venda sai no fundo.
"""
from __future__ import annotations

from datetime import datetime

VERSAO = 1
CAPITAL = 1000.0
MIN5 = 5 * 60 * 1000
HORA = 3600 * 1000
GT = "https://api.geckoterminal.com/api/v2"
REGRAS = {"parte": 0.01, "por_hora": 1, "max_abertas": 8, "custo": 0.03, "alvo1": 2.0, "fatia1": 0.5, "alvo2": 5.0, "parada": 0.5, "prazo_h": 24}
ESTRATEGIAS = {
    "lancamento": {"nome": "No lançamento", "janela": "m5", "idade_min": 0, "idade_max": 6, "compradores": 10, "volume": 500.0, "subiu": 0.0},
    "hora": {"nome": "Depois da 1ª hora", "janela": "h1", "idade_min": 40, "idade_max": 180, "compradores": 50, "volume": 10000.0, "subiu": 2.0},
}


def num(x) -> float | None:
    try:
        v = float(x)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def iso_ms(s) -> int | None:
    try:
        return int(datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def _id(rel: dict, nome: str) -> str:
    return (((rel or {}).get(nome) or {}).get("data") or {}).get("id") or ""


def candidatos(resp: dict, agora: int) -> list[dict]:
    """Moedas da pump.fun ainda na curva de preço, com par em SOL, de uma página de pools novas do GeckoTerminal.

    Cada uma leva os números de agora em '_a' (para a estratégia do lançamento, que decide na hora)."""
    out = []
    for p in (resp or {}).get("data") or []:
        a, rel = p.get("attributes") or {}, p.get("relationships") or {}
        if _id(rel, "dex") != "pump-fun" or not str(a.get("name", "")).endswith(" / SOL"):
            continue
        token = _id(rel, "base_token").split("_", 1)[-1]
        px, criada = num(a.get("base_token_price_usd")), iso_ms(a.get("pool_created_at"))
        if token and px and criada and a.get("address"):
            out.append({"pool": a["address"], "token": token, "simbolo": a["name"][:-6].strip()[:24], "criada": criada, "px0": px, "visto": agora, "_a": a})
    return out


def tracao(c: dict, a: dict, agora: int, f: dict) -> dict:
    """Os números de uma moeda na janela da estratégia (5 min ou 1 h) e se ela passa no filtro (campo 'passa')."""
    tx = (a.get("transactions") or {}).get(f["janela"]) or {}
    px = num(a.get("base_token_price_usd")) or 0.0
    m = {"compradores": int(tx.get("buyers") or 0), "compras": int(tx.get("buys") or 0), "vendas": int(tx.get("sells") or 0),
         "volume": round(num((a.get("volume_usd") or {}).get(f["janela"])) or 0.0, 2), "subiu": round(px / c["px0"], 3) if px else 0.0,
         "idade_min": round((agora - c["criada"]) / 60000, 1), "px": px, "fdv": num(a.get("fdv_usd"))}
    m["passa"] = bool(px and f["idade_min"] <= m["idade_min"] <= f["idade_max"] and m["compradores"] >= f["compradores"]
                      and m["compras"] > m["vendas"] and m["volume"] >= f["volume"] and m["subiu"] >= f["subiu"])
    return m


def patrimonio(est: dict, r: dict = REGRAS) -> float:
    """Caixa + o que sobrou de cada moeda aberta, vendido no último preço (menos o custo)."""
    return est["caixa"] + sum(p["resto"] * p["ult_px"] * (1 - r["custo"]) for p in est["abertas"])


def _tipo(est: dict, tipo: str) -> dict:
    return est.setdefault("por_tipo", {}).setdefault(tipo, {"compras": 0, "investido": 0.0, "recebido": 0.0})


def comprar(est: dict, c: dict, m: dict, agora: int, tipo: str = "lancamento", r: dict = REGRAS) -> dict | None:
    valor = min(est["caixa"], patrimonio(est, r) * r["parte"])
    if valor < 1 or not m["px"]:
        return None
    qtd = valor / (m["px"] * (1 + r["custo"]))
    est["caixa"] -= valor
    t = _tipo(est, tipo)
    t["compras"] += 1
    t["investido"] += valor
    p = {"tipo": tipo, "token": c["token"], "pool": c["pool"], "simbolo": c["simbolo"], "entrou": agora, "px": m["px"], "valor": round(valor, 4),
         "qtd": qtd, "resto": qtd, "recebido": 0.0, "alvo1": False, "ult_t": agora, "ult_px": m["px"], "max": 1.0, "vendas": [],
         "medidas": {k: m[k] for k in ("compradores", "compras", "vendas", "volume", "subiu", "idade_min", "fdv")}}
    est["abertas"].append(p)
    return p


def _vender(est: dict, p: dict, q: float, px: float, t: int, motivo: str, r: dict) -> None:
    q = min(q, p["resto"])
    if q <= 0:
        return
    v = q * px * (1 - r["custo"])
    p["resto"] -= q
    p["recebido"] += v
    est["caixa"] += v
    _tipo(est, p.get("tipo", "lancamento"))["recebido"] += v
    p["vendas"].append({"t": t, "px": px, "mult": round(px / p["px"], 3), "valor": round(v, 4), "motivo": motivo})


def andar(est: dict, p: dict, velas: list, agora: int, r: dict = REGRAS) -> bool:
    """Passa as velas de 5 minutos fechadas (desde a última vista) pela moeda. Devolve True se ela foi toda vendida.

    velas: [[t (s ou ms), abertura, máxima, mínima, fechamento, volume], ...] em qualquer ordem.
    """
    e, fim = p["px"], p["entrou"] + r["prazo_h"] * HORA
    vs = sorted(([int(v[0] * 1000) if v[0] < 1e12 else int(v[0]), *map(float, v[1:5])] for v in velas), key=lambda v: v[0])
    for t, o, h, lo, c in vs:
        if t < p["ult_t"] or t + MIN5 > agora:
            continue                                  # vela já vista, de antes da compra ou ainda aberta
        parada = e * (1.0 if p["alvo1"] else r["parada"])
        if lo <= parada:                              # a parada vem primeiro (pior caso)
            ref = min(parada, o)
            px = ref if lo >= 0.5 * ref else lo
            _vender(est, p, p["resto"], px, t, "despencou" if px <= 0.2 * e else ("parada" if not p["alvo1"] else "voltou ao preço"), r)
        else:
            if not p["alvo1"] and h >= e * r["alvo1"]:
                _vender(est, p, p["qtd"] * r["fatia1"], e * r["alvo1"], t, "dobrou", r)
                p["alvo1"] = True
            if p["alvo1"] and h >= e * r["alvo2"]:
                _vender(est, p, p["resto"], e * r["alvo2"], t, "5×", r)
        p["max"] = max(p["max"], h / e)
        p["ult_px"], p["ult_t"] = c, t + MIN5
        if p["resto"] > 0 and t + MIN5 >= fim:
            _vender(est, p, p["resto"], c, t, "24 horas", r)
        if p["resto"] <= 1e-12:
            return True
    if p["resto"] > 0 and agora >= fim:               # sem negócio nas últimas velas: sai no último preço
        _vender(est, p, p["resto"], p["ult_px"], agora, "24 horas", r)
        return True
    return p["resto"] <= 1e-12


def resultado(p: dict, r: dict = REGRAS) -> float:
    """Quanto a compra rendeu até agora (vendas + o que sobrou no último preço), sobre o valor que entrou."""
    return (p["recebido"] + p["resto"] * p["ult_px"] * (1 - r["custo"])) / p["valor"] - 1 if p["valor"] else 0.0


def por_estrategia(est: dict, r: dict = REGRAS) -> list[dict]:
    """Resultado de cada estratégia desde o começo: (vendas + o que está aberto) sobre o que foi investido."""
    out = []
    for k, f in ESTRATEGIAS.items():
        t = _tipo(est, k)
        aberto = sum(p["resto"] * p["ult_px"] * (1 - r["custo"]) for p in est["abertas"] if p.get("tipo") == k)
        out.append({"id": k, "nome": f["nome"], "compras": t["compras"], "investido": round(t["investido"], 2),
                    "r": round((t["recebido"] + aberto) / t["investido"] - 1, 4) if t["investido"] else None,
                    "abertas": sum(1 for p in est["abertas"] if p.get("tipo") == k)})
    return out


def resumo_fechada(p: dict, agora: int, r: dict = REGRAS) -> dict:
    return {"tipo": p.get("tipo", "lancamento"), "token": p["token"], "pool": p["pool"], "simbolo": p["simbolo"], "entrou": p["entrou"], "saiu": agora,
            "valor": round(p["valor"], 2), "r": round(resultado(p, r), 4), "max": round(p["max"], 2),
            "motivo": p["vendas"][-1]["motivo"] if p["vendas"] else "", "dobrou": p["alvo1"], "medidas": p.get("medidas"), "vendas": p["vendas"]}
