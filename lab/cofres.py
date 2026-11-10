"""Laboratório 3: cofres (vaults) da Hyperliquid, sem dinheiro.

Num cofre você deposita e o dono opera com o dinheiro de todos; ele fica com 10 % do lucro. O HLP é o cofre do próprio
protocolo (faz mercado e liquidações). Aqui o robô:
1. lê a lista pública de cofres (milhares) e fica com os abertos, com dinheiro e com histórico;
2. para os maiores, baixa o histórico (saldo e lucro) e monta um índice de rendimento que ignora depósitos e saques;
3. mede constância (semanas no azul), pior queda e o teste de sorte (bootstrap), igual ao Radar;
4. faz um "depósito" simulado de US$ 1.000, já tirando os 10 % do dono.

Desde 09/11/2026 o laboratório também mede se cada cofre acompanha o BTC: a "beta" (quanto ele anda quando o BTC anda)
e o rendimento médio nos períodos em que o BTC caiu 5 % ou mais. Os cofres da carteira em curso passam nesse filtro
(beta perto de zero): a perda deles de 03 a 09/11 foi dos gestores, não do BTC. Numa carteira nova, um cofre de trader
só entra se passar no filtro; o HLP fica com 40 % e os escolhidos dividem o resto.
"""
from __future__ import annotations

import math

import numpy as np

DIA = 86400000
LISTA = "https://stats-data.hyperliquid.xyz/Mainnet/vaults"
HLP = "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"
# versão 3 (10/11, pedido do João: o máximo de lucro): só o HLP (55 % ao ano em 3,5 anos, pior queda 5,8 %); os outros 3
# cofres da versão 2 estavam negativos. A lista dos demais continua medida e aparece no app.
PADRAO = {"tvl_minimo": 100_000, "idade_minima_dias": 60, "detalhar": 40, "carteira": 0, "capital": 1000.0, "comissao": 0.10,
          "peso_hlp": 1.0, "beta_maxima": 0.30, "queda_btc": -0.05, "nas_quedas_minimo": -0.01}
VERSAO = 3


def preco_em(velas: list[list[float]], t: int) -> float | None:
    """Fechamento do BTC no último dia até t."""
    antes = None
    for tv, c in velas:
        if tv > t:
            break
        antes = c
    return antes


def contra_btc(ind: list[list[float]], velas: list[list[float]], p: dict) -> dict:
    """Quanto o cofre anda junto com o BTC: beta (por trechos de ~1 semana) e o rendimento médio nos trechos em que o BTC
    caiu 5 % ou mais. velas = [[t, fechamento]] diárias do BTC, em ordem."""
    pts, ult = [], None
    for t, x in ind:
        if ult is None or t - ult[0] >= 5 * DIA:
            pts.append((t, x))
            ult = (t, x)
    rv, rb = [], []
    for (t0, x0), (t1, x1) in zip(pts, pts[1:]):
        b0, b1 = preco_em(velas, t0), preco_em(velas, t1)
        if b0 and b1 and x0 > 0:
            rv.append(x1 / x0 - 1)
            rb.append(b1 / b0 - 1)
    if len(rv) < 6:
        return {"beta": None, "nas_quedas": None, "trechos": len(rv), "trechos_queda": 0}
    v, b = np.array(rv), np.array(rb)
    var = float(np.var(b))
    beta = float(np.cov(v, b, bias=True)[0, 1] / var) if var > 0 else 0.0
    quedas = v[b <= p["queda_btc"]]
    return {"beta": round(beta, 3), "nas_quedas": round(float(quedas.mean()), 4) if len(quedas) else None,
            "trechos": len(rv), "trechos_queda": int(len(quedas))}


def independente(c: dict, p: dict) -> bool:
    """Não acompanhou o BTC: beta baixa e, se houve quedas do BTC no histórico, sem perda média nelas."""
    if c.get("beta") is None or abs(c["beta"]) > p["beta_maxima"]:
        return False
    return c.get("nas_quedas") is None or c["nas_quedas"] >= p["nas_quedas_minimo"]


def candidatos(lista: list[dict], agora: int, p: dict) -> list[dict]:
    out = []
    for v in lista:
        s = v.get("summary") or {}
        if s.get("isClosed"):
            continue
        tvl = float(s.get("tvl") or 0)
        ct = s.get("createTimeMillis")
        idade = (agora - int(agora if ct is None else ct)) / DIA
        if tvl < p["tvl_minimo"] or idade < p["idade_minima_dias"]:
            continue
        out.append({"cofre": s["vaultAddress"].lower(), "nome": s.get("name") or "", "lider": s.get("leader"), "tvl": round(tvl),
                    "idade_dias": round(idade), "apr": float(v.get("apr") or 0)})
    out.sort(key=lambda x: -x["tvl"])
    return out


def indice(portfolio: list, janela: str = "allTime") -> list[list[float]]:
    """[[t, índice]] a partir do histórico de saldo e de lucro: o índice só anda com o lucro (depósito e saque não contam)."""
    jan = dict((k, v) for k, v in portfolio) if portfolio and isinstance(portfolio[0], list) else {}
    d = jan.get(janela) or {}
    av = [(int(t), float(x)) for t, x in d.get("accountValueHistory", [])]
    pnl = [(int(t), float(x)) for t, x in d.get("pnlHistory", [])]
    if len(av) < 3 or len(pnl) != len(av):
        return []
    out, idx = [[av[0][0], 1.0]], 1.0
    for i in range(1, len(av)):
        base = av[i - 1][1]
        if base > 0:
            idx *= 1 + max(-0.99, (pnl[i][1] - pnl[i - 1][1]) / base)
        out.append([av[i][0], idx])
    return out


def medir(ind: list[list[float]]) -> dict:
    if len(ind) < 5:
        return {}
    ts = np.array([t for t, _ in ind], dtype=float)
    v = np.array([x for _, x in ind])
    r = v[1:] / v[:-1] - 1
    dias = float((ts[-1] - ts[0]) / DIA)
    pico = np.maximum.accumulate(v)
    queda = float(np.max(1 - v / pico))
    # semanas: o índice no fim de cada semana
    sem, ult, ini = [], None, ts[0]
    for t, x in ind:
        if t - ini >= 7 * DIA:
            sem.append(x / (ult or ind[0][1]) - 1)
            ult, ini = x, t
    # bootstrap simples: a média dos retornos poderia ser zero?
    rng = np.random.default_rng(7)
    c = r - r.mean()
    medias = rng.choice(c, size=(3000, len(c))).mean(axis=1) if len(c) > 4 else np.array([0.0])
    p = float((medias >= r.mean()).mean()) if len(c) > 4 else 1.0
    total = float(v[-1] / v[0] - 1)
    return {"total": round(total, 4), "dias": round(dias), "ao_ano": round((1 + total) ** (365 / max(dias, 1)) - 1, 4) if dias >= 30 and total > -1 else None,
            "pior_queda": round(queda, 4), "semanas_positivas": round(sum(1 for x in sem if x > 0) / len(sem), 3) if sem else None,
            "p": round(p, 4)}


def constante(m: dict) -> bool:
    return bool(m) and m["p"] <= 0.05 and m["pior_queda"] <= 0.20 and (m["semanas_positivas"] or 0) >= 0.6 and (m["ao_ano"] or 0) > 0


def desde(ind: list[list[float]], t0: int) -> float | None:
    """Rendimento do índice desde t0 (o ponto mais próximo antes de t0)."""
    antes = [x for t, x in ind if t <= t0]
    if not antes or not ind:
        return None
    return ind[-1][1] / antes[-1] - 1


def reduzir(ind, n=60):
    if len(ind) <= n:
        return [[t, round(x, 5)] for t, x in ind]
    passo = len(ind) / n
    return [[ind[int(i * passo)][0], round(ind[int(i * passo)][1], 5)] for i in range(n - 1)] + [[ind[-1][0], round(ind[-1][1], 5)]]


def amostra_apr(apr: float) -> float:
    return round(apr, 4) if math.isfinite(apr) else 0.0
