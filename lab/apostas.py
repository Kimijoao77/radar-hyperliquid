"""Laboratório 7: apostas esportivas na bolsa de apostas (Betfair Exchange), sem dinheiro.

Fonte: football-data.co.uk (grátis). Para cada jogo das ligas europeias (e de outras, como o Brasileirão) vem a odd da
bolsa e a média das casas, pegas na sexta à tarde (jogos do fim de semana) e na terça à tarde (jogos do meio da
semana), e depois o resultado e as odds de fechamento (as últimas antes do jogo).

A regra: a média das casas, sem a margem delas, dá a chance "justa" de cada resultado (método da potência, que tira mais
margem das zebras, como as casas fazem). Quando a odd da bolsa, já sem a comissão de 5 % sobre o ganho, paga pelo menos
`limiar` acima do justo, o robô aposta naquele resultado: um por jogo (o de maior vantagem), valor fixo de 1 % do capital
inicial. A Pinnacle, a referência mais afiada, saiu dos dados em 2025: por isso a média das casas.

Medidas: o resultado (lucro sobre o valor apostado, o ROI) e se a odd pega bateu a odd de fechamento da própria bolsa
(CLV): quem bate o fechamento com frequência tem vantagem de verdade, mesmo quando a sorte ainda não apareceu.

Escolha honesta: os ajustes (limiar, faixa de odds, com ou sem empate) são escolhidos numa temporada (2024/25) e
conferidos nas seguintes, que a escolha não viu.

Versão 2 (10/11/2026, à noite): a regra da versão 1 deu +10 % por aposta em 2024/25, onde foi escolhida, +2,7 % em
2025/26 e −8,4 % nesta temporada (114 apostas), pegando odd melhor que a final em menos da metade das vezes: a vantagem
era aparente. O ajuste foi refeito com dois jeitos e dois mercados:
  - "bolsa": o de antes (aposta na Betfair Exchange quando ela paga acima da média das casas sem a margem);
  - "casa": o contrário, que é o jeito conhecido de achar valor: a bolsa (o preço mais afiado que sobrou nos dados) dá a
    chance justa, e aposta na Bet365 (que tem licença no Brasil) quando a odd dela paga acima. Sem comissão; o risco é a
    casa limitar quem ganha;
  - mercados: resultado (vitória, empate, derrota) e gols (mais ou menos de 2,5).
A escolha usa as duas temporadas completas: maior lucro por aposta em 2025/26, com lucro também em 2024/25. Esta
temporada, que a escolha não viu, confere. Se nenhum ajuste der lucro nas duas, ou se o escolhido perder nesta temporada
(com 30 apostas ou mais), o teste desliga e sai do Placar.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

VERSAO = 2
CAPITAL = 1000.0
APOSTA = 10.0                 # 1 % do capital inicial por aposta
COMISSAO = 0.05               # da bolsa, sobre o ganho de cada mercado
RES = ("H", "D", "A")
MERCADOS = {"1x2": RES, "gols": (">2.5", "<2.5")}   # as colunas do football-data são o prefixo + a chave (AvgH, BFE>2.5, B365<2.5...)
LONDRES = ZoneInfo("Europe/London")

LIGAS = {"E0": "Inglaterra 1", "E1": "Inglaterra 2", "E2": "Inglaterra 3", "E3": "Inglaterra 4", "EC": "Inglaterra 5",
         "SC0": "Escócia 1", "SC1": "Escócia 2", "SC2": "Escócia 3", "SC3": "Escócia 4", "D1": "Alemanha 1", "D2": "Alemanha 2",
         "I1": "Itália 1", "I2": "Itália 2", "SP1": "Espanha 1", "SP2": "Espanha 2", "F1": "França 1", "F2": "França 2",
         "N1": "Holanda 1", "B1": "Bélgica 1", "P1": "Portugal 1", "T1": "Turquia 1", "G1": "Grécia 1"}
# ligas "novas" do football-data: o arquivo de jogos tem as odds de antes; o de resultados, só as de fechamento
EXTRAS = {"Argentina": ("ARG", "Argentina"), "Austria": ("AUT", "Áustria"), "Brazil": ("BRA", "Brasil"), "China": ("CHN", "China"),
          "Denmark": ("DNK", "Dinamarca"), "Finland": ("FIN", "Finlândia"), "Ireland": ("IRL", "Irlanda"), "Japan": ("JPN", "Japão"),
          "Mexico": ("MEX", "México"), "Norway": ("NOR", "Noruega"), "Poland": ("POL", "Polônia"), "Romania": ("ROU", "Romênia"),
          "Russia": ("RUS", "Rússia"), "Sweden": ("SWE", "Suécia"), "Switzerland": ("SWZ", "Suíça"), "USA": ("USA", "Estados Unidos")}
NOME_LIGA = {**LIGAS, **{cod: nome for cod, nome in EXTRAS.values()}}

SITE = "https://www.football-data.co.uk"
JOGOS = SITE + "/fixtures.csv"
JOGOS_EXTRAS = SITE + "/new_league_fixtures.csv"
TEMPORADA = SITE + "/mmz4281/{t}/{liga}.csv"
RESULTADOS_EXTRAS = SITE + "/new/{cod}.csv"

# ajustes testados no passado (escolha numa temporada, conferência nas seguintes)
CONFIGS = ([{"onde": o, "mercado": "1x2", "limiar": l, "odd_min": a, "odd_max": b, "empate": e}
            for o in ("bolsa", "casa") for l in (0.0, 0.02, 0.04, 0.06) for (a, b) in ((1.3, 4.0), (1.3, 8.0)) for e in (True, False)]
           + [{"onde": o, "mercado": "gols", "limiar": l, "odd_min": 1.3, "odd_max": 4.0, "empate": False}
              for o in ("bolsa", "casa") for l in (0.0, 0.02, 0.04, 0.06)])
MINIMO_APOSTAS = 150          # um ajuste só concorre se apostou pelo menos isso na temporada da escolha


def num(x) -> float | None:
    try:
        v = float(str(x).strip())
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def ler_csv(texto: str) -> list[dict]:
    linhas = list(csv.reader(io.StringIO(texto.lstrip("﻿"))))
    if not linhas:
        return []
    cab = linhas[0]
    return [dict(zip(cab, l)) for l in linhas[1:] if any(c.strip() for c in l)]


def justas(odds: list) -> list[float] | None:
    """Chances sem a margem (método da potência): acha k com soma (1/odd)^k = 1."""
    if not odds or any(o is None or o <= 1 for o in odds):
        return None
    inv = [1 / o for o in odds]
    s = sum(inv)
    if s <= 1:                                   # sem margem (raro): só normaliza
        return [x / s for x in inv]
    lo, hi = 1.0, 8.0
    for _ in range(60):
        k = (lo + hi) / 2
        if sum(x ** k for x in inv) > 1:
            lo = k
        else:
            hi = k
    k = (lo + hi) / 2
    return [x ** k for x in inv]


def efetiva(odd: float, comissao: float = COMISSAO) -> float:
    """Odd que sobra depois da comissão da bolsa sobre o ganho."""
    return 1 + (odd - 1) * (1 - comissao)


def avaliar(jogo: dict, cfg: dict) -> dict | None:
    """A aposta da regra num jogo (ou None): o resultado de maior vantagem que passa no limiar e na faixa de odds.
    onde "bolsa": a chance justa vem da média das casas e a aposta é na bolsa (com a comissão);
    onde "casa": a chance justa vem da bolsa e a aposta é na Bet365 (sem comissão)."""
    onde, mercado = cfg.get("onde", "bolsa"), cfg.get("mercado", "1x2")
    chaves = MERCADOS[mercado]
    ref, onde_aposta, com = ("Avg", "BFE", COMISSAO) if onde == "bolsa" else ("BFE", "B365", 0.0)
    p = justas([num(jogo.get(f"{ref}{k}")) for k in chaves])
    odds = [num(jogo.get(f"{onde_aposta}{k}")) for k in chaves]
    if p is None or any(o is None or o <= 1 for o in odds):
        return None
    melhor = None
    for i, k in enumerate(chaves):
        if k == "D" and not cfg.get("empate", True):
            continue
        o = odds[i]
        if not cfg["odd_min"] <= o <= cfg["odd_max"]:
            continue
        v = p[i] * efetiva(o, com) - 1
        if v >= cfg["limiar"] and (melhor is None or v > melhor["vantagem"]):
            melhor = {"aposta": k, "odd": o, "justa": round(1 / p[i], 3), "vantagem": round(v, 4), "onde": onde, "mercado": mercado}
    return melhor


def desfecho(linha: dict) -> dict | None:
    """O resultado de um jogo terminado (arquivo de resultados): {res: H/D/A, gols: total}."""
    res = (linha.get("FTR") or linha.get("Res") or "").strip()
    if res not in RES:
        return None
    try:
        gols = int(float(linha.get("FTHG") if linha.get("FTHG") not in (None, "") else linha.get("HG"))) + \
               int(float(linha.get("FTAG") if linha.get("FTAG") not in (None, "") else linha.get("AG")))
    except (TypeError, ValueError):
        gols = None
    return {"res": res, "gols": gols}


def venceu(aposta: dict, d: dict | None) -> bool | None:
    """Se a aposta ganhou (None: sem como saber)."""
    if not d:
        return None
    k = aposta["aposta"]
    if k in RES:
        return d["res"] == k
    if d.get("gols") is None:
        return None
    return d["gols"] > 2.5 if k == ">2.5" else d["gols"] < 2.5


def resultado(aposta: dict, res, valor: float = APOSTA, comissao: float | None = None) -> float:
    """Ganho (ou perda) de uma aposta a favor: ganhou leva (odd − 1) × valor (na bolsa, menos a comissão); perdeu, perde o
    valor. `res`: True/False (ganhou?) ou o resultado do jogo (H, D, A)."""
    ganhou = res if isinstance(res, bool) else res == aposta["aposta"]
    if comissao is None:
        comissao = COMISSAO if aposta.get("onde", "bolsa") == "bolsa" else 0.0
    return valor * (aposta["odd"] - 1) * (1 - comissao) if ganhou else -valor


def clv(aposta: dict, jogo: dict) -> float | None:
    """Quanto a odd pega ficou acima (+) ou abaixo (−) da odd de fechamento da bolsa."""
    f = num(jogo.get(f"BFEC{aposta['aposta']}"))
    return aposta["odd"] / f - 1 if f and f > 1 else None


def medir(jogos: list[dict], cfg: dict, valor: float = APOSTA) -> dict:
    """A regra em jogos que já aconteceram (com a odd de antes e o resultado)."""
    n = acertos = 0
    lucro = 0.0
    cs, bateu, por_liga = [], 0, {}
    for j in jogos:
        d = desfecho(j)
        if not d:
            continue
        a = avaliar(j, cfg)
        if not a:
            continue
        ok = venceu(a, d)
        if ok is None:
            continue
        g = resultado(a, ok, valor)
        n += 1
        lucro += g
        acertos += g > 0
        lg = por_liga.setdefault(j.get("Div", "?"), [0, 0.0])
        lg[0] += 1
        lg[1] += g
        c = clv(a, j)
        if c is not None:
            cs.append(c)
            bateu += c > 0
    return {"apostas": n, "lucro": round(lucro, 2), "roi": round(lucro / (n * valor), 4) if n else 0.0,
            "acerto": round(acertos / n, 3) if n else 0.0, "clv": round(sum(cs) / len(cs), 4) if cs else None,
            "bateu": round(bateu / len(cs), 3) if cs else None, "por_liga": {k: [v[0], round(v[1], 2)] for k, v in por_liga.items()}}


def nome(c: dict) -> str:
    v = "qualquer vantagem" if c["limiar"] <= 0 else f"vantagem de {c['limiar']:.0%} ou mais"
    onde = "na bolsa, contra a média das casas" if c.get("onde", "bolsa") == "bolsa" else "na Bet365, contra a bolsa"
    if c.get("mercado", "1x2") == "gols":
        return f"Gols (mais ou menos de 2.5) {onde}: {v}".replace(".", ",")
    return (f"Resultado {onde}: {v}, odds de {c['odd_min']:g} a {c['odd_max']:g}" + ("" if c["empate"] else ", sem empate")).replace(".", ",")


def escolher(medidas: list[dict], exigida: list[dict] | None = None, minimo: int = MINIMO_APOSTAS) -> int | None:
    """Índice do ajuste com o maior ROI na temporada da escolha (com apostas suficientes). Versão 2: com `exigida`, só
    concorre quem também deu lucro nela (com pelo menos metade do mínimo de apostas)."""
    ok = [i for i, m in enumerate(medidas) if m["apostas"] >= minimo
          and (exigida is None or (exigida[i]["apostas"] >= minimo // 2 and exigida[i]["roi"] > 0))]
    return max(ok, key=lambda i: (medidas[i]["roi"], medidas[i]["apostas"])) if ok else None


def temporada(ms: int) -> str:
    """Temporada europeia de uma data: agosto de 2026 a julho de 2027 = '2627'."""
    d = datetime.fromtimestamp(ms / 1000, timezone.utc)
    a = d.year if d.month >= 7 else d.year - 1
    return f"{a % 100:02d}{(a + 1) % 100:02d}"


def inicio_jogo(data: str, hora: str) -> int | None:
    """Data (dd/mm/aa ou dd/mm/aaaa) e hora do football-data (horário de Londres) em ms UTC."""
    try:
        d, m, a = (int(x) for x in data.strip().split("/"))
        a = a + 2000 if a < 100 else a
        h, mi = (int(x) for x in (hora or "15:00").strip().split(":")[:2])
        return int(datetime(a, m, d, h, mi, tzinfo=LONDRES).timestamp() * 1000)
    except (ValueError, AttributeError):
        return None


def jogos_da_lista(principal: list[dict], extras: list[dict]) -> list[dict]:
    """Junta as duas listas de jogos num formato só: liga, casa, fora, início e as odds."""
    out = []
    for j in principal:
        if j.get("Div") in LIGAS:
            out.append({**{k: j.get(k) for k in j if k[:3] in ("Avg", "BFE", "B36")}, "liga": j["Div"], "casa": j.get("HomeTeam", "").strip(),
                        "fora": j.get("AwayTeam", "").strip(), "data": j.get("Date", ""), "inicio": inicio_jogo(j.get("Date", ""), j.get("Time", ""))})
    for j in extras:
        cod = EXTRAS.get((j.get("Country") or "").strip())
        if cod:
            out.append({**{k: j.get(k) for k in j if k[:3] in ("Avg", "BFE", "B36")}, "liga": cod[0], "casa": j.get("Home", "").strip(),
                        "fora": j.get("Away", "").strip(), "data": j.get("Date", ""), "inicio": inicio_jogo(j.get("Date", ""), j.get("Time", ""))})
    return [j for j in out if j["casa"] and j["fora"] and j["inicio"]]


def chave(j: dict) -> str:
    return f"{j['liga']}|{j['casa']}|{j['fora']}|{j['data']}"


def achar_resultado(aposta: dict, linhas: list[dict]) -> dict | None:
    """A linha do resultado de um jogo apostado: mesmos times, data até 4 dias de diferença (jogo remarcado)."""
    extra = aposta["liga"] not in LIGAS
    for l in linhas:
        casa = (l.get("Home") if extra else l.get("HomeTeam")) or ""
        fora = (l.get("Away") if extra else l.get("AwayTeam")) or ""
        if casa.strip() != aposta["casa"] or fora.strip() != aposta["fora"]:
            continue
        t = inicio_jogo(l.get("Date", ""), l.get("Time", ""))
        res = ((l.get("Res") if extra else l.get("FTR")) or "").strip()
        if t and abs(t - aposta["inicio"]) <= 4 * 86400000 and res in RES:
            gols = (l.get("HG"), l.get("AG")) if extra else (l.get("FTHG"), l.get("FTAG"))
            return {"res": res, "placar": f"{gols[0]}–{gols[1]}", "linha": l}
    return None


def descrever(aposta: dict) -> str:
    txt = {"H": f"{aposta['casa']} vence", "D": "Empate", "A": f"{aposta['fora']} vence", ">2.5": "Mais de 2,5 gols",
           "<2.5": "Menos de 2,5 gols"}[aposta["aposta"]]
    return txt + (" (Bet365)" if aposta.get("onde") == "casa" else "")
