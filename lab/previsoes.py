"""Teste de mercados de previsão (Polymarket, desde 18/11/2026; pedido do João: "apostas em geral, as famosas
previsões"). Só dinheiro de mentira: lê os preços públicos do Polymarket e anota apostas de US$ 20, sem conta e sem
ordem de verdade.

Três jeitos de apostar, lado a lado, cada um com US$ 1.000 de mentira:
  - quase_certas: o lado favorito a 88–97¢, em mercados que acabam em até 48 h (ganha pouco, quase sempre);
  - favoritas: o lado favorito a 65–88¢, em mercados que acabam em até 7 dias;
  - azaroes: o lado azarão a 3–15¢, em mercados que acabam em até 7 dias (perde quase sempre, ganha muito quando acerta).
O mesmo filtro roda no passado (mercados que já fecharam, com o preço de cada hora), e a calibração mostra se o preço
acerta a chance de verdade: se o "90¢" ganha mais de 90% das vezes, comprar favorito tem vantagem.

Custos de verdade: compra pelo preço de venda do livro (ask) e paga a taxa do Polymarket (taxa × p × (1 − p) por cota,
só de quem pega a oferta; geopolítica não paga). Na resolução, cada cota vale US$ 1 (acertou), 0 ou 0,50 (empate)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

VERSAO = 1
CAPITAL = 1000.0
APOSTA = 20.0
HORA = 3600 * 1000
DIA = 24 * HORA

# id: (nome, lado, preço mínimo, preço máximo, horas até acabar, explicação curta)
VARIANTES = {
    "quase_certas": {"nome": "Quase certas", "lado": "favorito", "min": 0.88, "max": 0.97, "horas": 48,
                     "curta": "O favorito a 88–97¢, em mercados que acabam em até 48 horas."},
    "favoritas": {"nome": "Favoritas da semana", "lado": "favorito", "min": 0.65, "max": 0.88, "horas": 7 * 24,
                  "curta": "O favorito a 65–88¢, em mercados que acabam em até 7 dias."},
    "azaroes": {"nome": "Azarões", "lado": "azarao", "min": 0.03, "max": 0.15, "horas": 7 * 24,
                "curta": "O azarão a 3–15¢, em mercados que acabam em até 7 dias."},
}
NOVAS_POR_HORA = 8            # no máximo 8 apostas novas por jeito em cada rodada (espalha no tempo)
POR_EVENTO = 2                # no máximo 2 apostas por evento (ex.: vários candidatos da mesma eleição)
SPREAD_MAX = 0.04             # livro com diferença de até 4¢ entre compra e venda
LIQUIDEZ_MIN = 2000.0
VOLUME_24H_MIN = 500.0

# taxa de quem pega a oferta, por categoria (docs.polymarket.com/trading/fees, 18/11/2026); vale a do mercado se vier
TAXA_CATEGORIA = {"Cripto": 0.07, "Esportes": 0.05, "Economia": 0.05, "Política": 0.04, "Cultura": 0.05,
                  "Tecnologia": 0.04, "Clima": 0.05, "Geopolítica": 0.0, "Outros": 0.05}

# categoria em português a partir das etiquetas (tags) do mercado
CATEGORIAS = [
    ("Esportes", {"sports", "nba", "nfl", "nhl", "mlb", "soccer", "football", "tennis", "esports", "ufc", "mma", "boxing",
                  "golf", "f1", "formula-1", "cricket", "basketball", "baseball", "hockey", "ncaa", "epl", "champions-league",
                  "dota-2", "counter-strike", "league-of-legends", "valorant", "games"}),
    ("Cripto", {"crypto", "bitcoin", "ethereum", "solana", "xrp", "crypto-prices", "memecoins", "airdrops", "stablecoins"}),
    ("Geopolítica", {"geopolitics", "world", "middle-east", "ukraine", "russia", "israel", "iran", "china", "war", "gaza",
                     "ceasefire", "nato", "venezuela"}),
    ("Política", {"politics", "elections", "us-politics", "trump", "us-elections", "global-elections", "congress", "senate",
                  "brazil", "presidential-election", "courts", "scotus"}),
    ("Economia", {"economy", "economics", "finance", "fed", "fed-rates", "inflation", "business", "stocks", "ipos",
                  "interest-rates", "commodities", "gdp", "earnings", "tariffs"}),
    ("Tecnologia", {"tech", "ai", "science", "openai", "spacex", "space", "elon-musk", "big-tech"}),
    ("Cultura", {"pop-culture", "culture", "entertainment", "movies", "music", "awards", "celebrities", "tv", "box-office",
                 "mentions", "tweet-markets", "youtube", "twitch"}),
    ("Clima", {"weather", "climate", "temperature", "hurricanes"}),
]
CURTISSIMOS = re.compile(r"\bup or down\b", re.I)    # moedas "sobe ou desce" de 5/15 min/1 h: entram e saem sem parar


def ms_de(texto) -> int | None:
    """'2026-11-18T03:00:00Z' ou '2026-11-18 03:13:18.09+00' → milissegundos (UTC)."""
    if not texto:
        return None
    s = str(texto).strip().replace(" ", "T", 1)
    s = re.sub(r"\.\d+", "", s)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    if re.search(r"[+-]\d\d$", s):
        s += ":00"
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return int(d.timestamp() * 1000)


def lista(x) -> list:
    """outcomes, outcomePrices e clobTokenIds vêm como texto JSON."""
    if isinstance(x, list):
        return x
    try:
        v = json.loads(x or "[]")
        return v if isinstance(v, list) else []
    except (TypeError, ValueError):
        return []


def categoria(m: dict) -> str:
    slugs = {str(t.get("slug") or "").lower() for t in (m.get("tags") or []) if isinstance(t, dict)}
    for ev in m.get("events") or []:
        slugs |= {str(t.get("slug") or "").lower() for t in (ev.get("tags") or []) if isinstance(t, dict)}
    if m.get("sportsMarketType") or m.get("gameStartTime"):
        return "Esportes"
    for nome, chaves in CATEGORIAS:
        if slugs & chaves:
            return nome
    return "Outros"


def taxa(m: dict, cat: str) -> float:
    if m.get("feesEnabled") is False:
        return 0.0
    fs = m.get("feeSchedule") or {}
    if isinstance(fs, dict) and fs.get("rate") is not None:
        try:
            return float(fs["rate"])
        except (TypeError, ValueError):
            pass
    return TAXA_CATEGORIA.get(cat, 0.05)


def fim_esperado(m: dict) -> int | None:
    """Quando o mercado deve acabar: nos esportes, o começo do jogo + 3 h (o endDate deles vem dias depois)."""
    jogo = ms_de(m.get("gameStartTime"))
    if jogo:
        return jogo + 3 * HORA
    return ms_de(m.get("endDate"))


def evento(m: dict) -> str:
    evs = m.get("events") or []
    return str(evs[0].get("id")) if evs and isinstance(evs[0], dict) else str(m.get("id"))


def precos_compra(m: dict) -> list[float | None]:
    """Preço para comprar cada lado: o lado 0 pelo bestAsk; o lado 1 por 1 − bestBid (o livro é um só)."""
    a, b = m.get("bestAsk"), m.get("bestBid")
    p0 = float(a) if a not in (None, "") else None
    p1 = round(1 - float(b), 4) if b not in (None, "") else None
    return [p0, p1]


def cotas_por(valor: float, p: float, tx: float) -> tuple[float, float]:
    """Com `valor` dólares (taxa incluída), quantas cotas compra a `p` e quanto paga de taxa."""
    por_cota = p + tx * p * (1 - p)
    cotas = valor / por_cota
    return cotas, cotas * tx * p * (1 - p)


def elegivel(m: dict, agora: int) -> bool:
    if m.get("closed") or m.get("acceptingOrders") is False or m.get("enableOrderBook") is False:
        return False
    if len(lista(m.get("outcomes"))) != 2 or len(lista(m.get("clobTokenIds"))) != 2:
        return False
    if CURTISSIMOS.search(str(m.get("question") or "")):
        return False
    if float(m.get("liquidityNum") or 0) < LIQUIDEZ_MIN or float(m.get("volume24hr") or 0) < VOLUME_24H_MIN:
        return False
    sp = m.get("spread")
    if sp is not None and float(sp) > SPREAD_MAX:
        return False
    fim = fim_esperado(m)
    return bool(fim and fim > agora)


def candidatos(mercados: list[dict], var: dict, agora: int) -> list[dict]:
    """As apostas que um jeito faria agora, da maior liquidez do dia para a menor."""
    out = []
    for m in mercados:
        if not elegivel(m, agora):
            continue
        fim = fim_esperado(m)
        if fim - agora > var["horas"] * HORA:
            continue
        ps = precos_compra(m)
        if None in ps:
            continue
        fav = 0 if ps[0] >= ps[1] else 1
        lado = fav if var["lado"] == "favorito" else 1 - fav
        p = ps[lado]
        if not (var["min"] <= p <= var["max"]):
            continue
        out.append({"m": m, "lado": lado, "preco": p, "fim": fim})
    out.sort(key=lambda c: -float(c["m"].get("volume24hr") or 0))
    return out


def resolucao(m: dict) -> list[float] | None:
    """Quanto vale cada cota de cada lado depois de resolvido (1/0, ou 0,5/0,5), ou None se ainda não resolveu."""
    if not m.get("closed"):
        return None
    ps = [float(x) for x in lista(m.get("outcomePrices"))]
    if len(ps) != 2:
        return None
    if str(m.get("umaResolutionStatus") or "").lower() not in ("resolved", "") and not m.get("automaticallyResolved"):
        return None
    if all(abs(p - round(p * 2) / 2) < 0.011 for p in ps) and abs(sum(ps) - 1) < 0.02:
        return [round(p * 2) / 2 for p in ps]
    return None


# ---------------- no passado ----------------
def preco_em(hist: list[tuple[int, float]], t: int) -> float | None:
    """Preço da última hora até `t` (histórico em ms, do mais velho para o mais novo)."""
    ult = None
    for ts, p in hist:
        if ts > t:
            break
        ult = p
    return ult


def no_passado(m: dict, hist0: list[tuple[int, float]], tick: float = 0.01) -> dict | None:
    """Resume um mercado fechado: o preço do lado 0 24 h antes do fim (calibração) e, para cada jeito, a aposta que o
    filtro faria na primeira hora em que o mercado passasse (com 1 tick de diferença para pagar o ask) e o resultado."""
    res = resolucao(m)
    fech = ms_de(m.get("closedTime")) or ms_de(m.get("endDate"))
    fim = fim_esperado(m)
    if not res or not fech or not fim or not hist0:
        return None
    cat = categoria(m)
    tx = taxa(m, cat)
    out = {"id": str(m.get("id")), "q": str(m.get("question") or "")[:120], "cat": cat, "fech": fech, "venceu": res}
    p24 = preco_em(hist0, min(fech, fim) - DIA)
    if p24 is not None:
        out["p24"] = round(p24, 4)
    apostas = {}
    for vid, var in VARIANTES.items():
        for ts, p0 in hist0:
            if ts >= fech or ts >= fim:
                break
            if fim - ts > var["horas"] * HORA:
                continue
            ps = [min(0.999, p0 + tick), min(0.999, 1 - p0 + tick)]          # comprar paga 1 tick acima do meio
            fav = 0 if p0 >= 0.5 else 1
            lado = fav if var["lado"] == "favorito" else 1 - fav
            p = ps[lado]
            if var["min"] <= p <= var["max"]:
                cotas, _ = cotas_por(APOSTA, p, tx)
                apostas[vid] = {"t": ts, "lado": lado, "p": round(p, 4), "r": round(cotas * res[lado] / APOSTA - 1, 4)}
                break
    out["apostas"] = apostas
    return out


def resumo_passado(itens: list[dict]) -> dict:
    """Por jeito: quantas apostas, quantas ganharam e o lucro médio por aposta. E a calibração em faixas de 10¢."""
    por = {}
    for vid in VARIANTES:
        rs = [i["apostas"][vid] for i in itens if vid in i.get("apostas", {})]
        n = len(rs)
        por[vid] = {"apostas": n, "acertos": sum(1 for a in rs if a["r"] > 0),
                    "roi": round(sum(a["r"] for a in rs) / n, 4) if n else None,
                    "preco_medio": round(sum(a["p"] for a in rs) / n, 4) if n else None,
                    "por_categoria": _por_cat([(i["cat"], i["apostas"][vid]["r"]) for i in itens if vid in i.get("apostas", {})])}
    faixas = [{"de": k / 10, "ate": (k + 1) / 10, "n": 0, "ganhou": 0, "soma_p": 0.0} for k in range(10)]
    for i in itens:
        p = i.get("p24")
        if p is None:
            continue
        for lado, pl in ((0, p), (1, 1 - p)):                          # os dois lados de cada mercado
            f = faixas[min(9, max(0, int(round(pl * 10, 6))))]
            f["n"] += 1
            f["soma_p"] += pl
            f["ganhou"] += i["venceu"][lado]
    cal = [{"faixa": f"{int(f['de'] * 100)}–{int(f['ate'] * 100)}¢", "n": f["n"],
            "preco": round(f["soma_p"] / f["n"], 4) if f["n"] else None,
            "real": round(f["ganhou"] / f["n"], 4) if f["n"] else None} for f in faixas]
    return {"mercados": len(itens), "variantes": por, "calibracao": cal}


def _por_cat(pares):
    d = {}
    for c, r in pares:
        x = d.setdefault(c, {"apostas": 0, "soma": 0.0})
        x["apostas"] += 1
        x["soma"] += r
    return {c: {"apostas": x["apostas"], "roi": round(x["soma"] / x["apostas"], 4)} for c, x in d.items()}
