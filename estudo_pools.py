"""Estudo das pools concentradas: simula entradas de 24 h nas pools coletadas e compara regras de escolha.

Uso: python estudo_pools.py pools.json
"""
import json, math, statistics as st, sys
from collections import defaultdict

ESC = 0.002          # escorregamento + rede em cada troca
REDE = 0.0005        # só a taxa da rede (depósito sem troca)
HORA = 3600


def efic(r):
    return 1 / (1 - ((1 - r) / (1 + r)) ** 0.25)


def fator(r):
    return efic(r) / efic(0.30)


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def L_de(valor, p0, a, b):
    sp, sa, sb = math.sqrt(p0), math.sqrt(a), math.sqrt(b)
    if p0 <= a:
        por = (1 / sa - 1 / sb) * p0
    elif p0 >= b:
        por = sb - sa
    else:
        por = (1 / sp - 1 / sb) * p0 + (sp - sa)
    return valor / por


def val(L, p, a, b):
    sa, sb = math.sqrt(a), math.sqrt(b)
    if p <= a:
        return L * (1 / sa - 1 / sb) * p
    if p >= b:
        return L * (sb - sa)
    sp = math.sqrt(p)
    return L * (1 / sp - 1 / sb) * p + L * (sp - sa)


def parte_moeda(L, p, a, b):
    """Fração do valor que está na moeda (o resto está em SOL/USDC)."""
    v = val(L, p, a, b)
    if v <= 0:
        return 0
    if p <= a:
        return 1.0
    if p >= b:
        return 0.0
    sp, sb = math.sqrt(p), math.sqrt(b)
    return L * (1 / sp - 1 / sb) * p / v


def carregar(arq):
    d = json.load(open(arq))
    sol = {int(v[0]) // HORA * HORA: num(v[4]) for v in d["sol"]}
    out = []
    for item in d["pools"]:
        p, vs = item["p"], item["velas"]
        if len(vs) < 60:
            continue
        y = p["token_y"]["symbol"].upper()
        tvl, vol24 = num(p.get("tvl")), num((p.get("volume") or {}).get("24h"))
        ftvl = num((p.get("fee_tvl_ratio") or {}).get("24h"))
        if tvl <= 0 or vol24 <= 0:
            continue
        taxa = min(0.1, max(0.0001, ftvl / 100 * tvl / vol24))
        base = num((p.get("pool_config") or {}).get("base_fee_pct")) / 100 or taxa
        serie = {}
        for v in vs:
            t = int(v[0]) // HORA * HORA
            c, volu = num(v[4]), num(v[5])
            if c <= 0:
                continue
            if y == "SOL":
                s = sol.get(t)
                if not s:
                    continue
                c = c / s
            serie[t] = (c, volu)
        ts = sorted(serie)
        if len(ts) < 60:
            continue
        out.append({"nome": p.get("name"), "addr": p["address"], "y": y, "tvl": tvl, "taxa": taxa, "base": base,
                    "ts": ts, "c": [serie[t][0] for t in ts], "v": [serie[t][1] for t in ts], "idx": {t: i for i, t in enumerate(ts)}})
    return out


def medidas(P, i):
    """O que se sabia na hora i (só velas até i)."""
    if i < 24:
        return None
    c, v = P["c"], P["v"]
    fee24 = sum(v[i - 23:i + 1]) * P["taxa"] / P["tvl"]
    rets = [math.log(c[k] / c[k - 1]) for k in range(i - 23, i + 1) if c[k - 1] > 0 and c[k] > 0]
    vol = st.pstdev(rets) if len(rets) > 5 else 1
    r6 = c[i] / c[i - 6] - 1
    r24 = c[i] / c[i - 24] - 1
    mx = max(c[max(0, i - 72):i + 1])
    return {"fee24": fee24, "vol": vol, "r6": r6, "r24": r24, "idade": i, "do_topo": c[i] / mx - 1,
            "v_estavel": (min(v[i - 23:i + 1]) + 1) / (max(v[i - 23:i + 1]) + 1)}


def simular(P, i, r, modo, saida, horas=24):
    """Uma posição de 1 unidade (em SOL/USDC) aberta no fechamento da hora i. Devolve o retorno."""
    c, v = P["c"], P["v"]
    p0 = c[i]
    if modo == "sim":
        a, b = p0 * (1 - r), p0 * (1 + r)
        custo_ent = 0.5 * P["taxa"] + ESC
    else:                                   # só SOL/USDC, numa faixa abaixo do preço (largura 2r)
        a, b = p0 * (1 - 2 * r), p0
        custo_ent = REDE
    L = L_de(1 - custo_ent, p0, a, b)
    f = fator(r)
    taxas, fim = 0.0, min(len(c) - 1, i + horas)
    k = i
    for k in range(i + 1, fim + 1):
        p = c[k]
        dentro = a <= p <= b
        if dentro:
            taxas += val(L, p, a, b) * v[k] * P["taxa"] / P["tvl"] * f
        elif saida == "sai":
            break
    p = c[k]
    vv = val(L, p, a, b)
    custo_sai = parte_moeda(L, p, a, b) * (P["taxa"] + ESC) * vv if modo == "solo" else (0.5 * P["taxa"] + ESC) * vv
    return vv + taxas - custo_sai - 1


REGRAS = {
    "maior taxa (atual)": (lambda m: True, lambda m: m["fee24"]),
    "taxa / balanço": (lambda m: True, lambda m: m["fee24"] / (m["vol"] + 0.005)),
    "maior taxa, sem queda": (lambda m: m["r24"] > -0.05 and m["r6"] > -0.02, lambda m: m["fee24"]),
    "taxa / balanço, sem queda": (lambda m: m["r24"] > -0.05 and m["r6"] > -0.02, lambda m: m["fee24"] / (m["vol"] + 0.005)),
    "balanço baixo (<2%/h)": (lambda m: m["vol"] < 0.02, lambda m: m["fee24"]),
    "balanço baixo, sem queda": (lambda m: m["vol"] < 0.02 and m["r24"] > -0.05, lambda m: m["fee24"]),
    "perto do topo (<10%)": (lambda m: m["do_topo"] > -0.10, lambda m: m["fee24"] / (m["vol"] + 0.005)),
    "taxa > balanço²×24": (lambda m: m["fee24"] > 0.5 * m["vol"] ** 2 * 24, lambda m: m["fee24"] - 0.5 * m["vol"] ** 2 * 24),
}


def main(arq):
    pools = carregar(arq)
    print(f"{len(pools)} pools com velas suficientes ({sum(p['y'] == 'USDC' for p in pools)} com USDC)")
    todas = sorted({t for p in pools for t in p["ts"]})
    t_ini, t_fim = todas[0] + 48 * HORA, todas[-1] - 24 * HORA
    entradas = [t for t in range(t_ini - t_ini % (6 * HORA), t_fim, 6 * HORA) if t >= t_ini]
    meio = entradas[len(entradas) // 2]
    print(f"{len(entradas)} momentos de entrada (de 6 em 6 h); metade A antes, metade B depois")
    res = defaultdict(lambda: {"A": [], "B": []})
    for t in entradas:
        cand = []
        for P in pools:
            i = P["idx"].get(t)
            if i is None or i + 6 >= len(P["c"]):
                continue
            m = medidas(P, i)
            if m:
                cand.append((P, i, m))
        lado = "A" if t < meio else "B"
        for nome, (ok, nota) in REGRAS.items():
            esc = sorted([x for x in cand if ok(x[2])], key=lambda x: -nota(x[2]))[:3]
            for modo in ("sim", "solo"):
                for r in (0.05, 0.15, 0.30):
                    for saida in ("sai", "segura"):
                        for P, i, m in esc:
                            res[(nome, modo, r, saida)][lado].append(simular(P, i, r, modo, saida))
    linhas = []
    for k, d in res.items():
        a, b = d["A"], d["B"]
        if len(a) < 10 or len(b) < 10:
            continue
        linhas.append((k, st.mean(a), st.mean(b), sum(x > 0 for x in a) / len(a), sum(x > 0 for x in b) / len(b), len(a), len(b),
                       st.median(a), st.median(b)))
    linhas.sort(key=lambda x: -min(x[1], x[2]))
    print("\nregra | modo | faixa | saída || média A | média B | ganhou A | ganhou B | n A | n B | mediana A | mediana B")
    for k, ma, mb, ga, gb, na, nb, da, db in linhas[:40]:
        print(f"{k[0]} | {k[1]} | ±{int(k[2]*100)}% | {k[3]} || {ma:+.2%} | {mb:+.2%} | {ga:.0%} | {gb:.0%} | {na} | {nb} | {da:+.2%} | {db:+.2%}")
    print("\n(atual = maior taxa | sim | todas as faixas | sai)")
    for k, ma, mb, ga, gb, na, nb, da, db in linhas:
        if k[0] == "maior taxa (atual)" and k[1] == "sim" and k[3] == "sai":
            print(f"{k} {ma:+.2%} {mb:+.2%} {ga:.0%} {gb:.0%}")


if __name__ == "__main__":
    main(sys.argv[1])
