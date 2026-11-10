"""Laboratório 10: vender moeda recém-listada na Hyperliquid (desde 10/11/2026, pedido do João), sem dinheiro.

A ideia: muita moeda nova cai nas semanas depois de estrear (quem ganhou de airdrop vende, e o preço de estreia costuma
vir inflado). A regra é fixa, sem ajuste escolhido no passado (para não escolher a dedo o que só deu certo antes):
  - entra vendida (short) 24 h depois da estreia da moeda no perpétuo da Hyperliquid (a estreia é a hora do primeiro
    funding), na abertura da primeira vela depois disso, a mercado;
  - cada moeda leva 10 % do patrimônio como margem: com 1× a posição vale 10 % do patrimônio; com 2×, 20 % (dois testes
    lado a lado). No máximo 10 moedas ao mesmo tempo (a 11ª fica de fora);
  - sai se o preço subir 30 % acima da entrada (parada, a mercado; se a vela já abre acima, sai na abertura) ou depois
    de 14 dias (a mercado). Moeda que sai da Hyperliquid fecha no último preço;
  - custos: 0,045 % de taxa e 0,1 % de derrapagem em cada ponta (o livro de moeda nova é mais fino) e o funding real de
    cada hora (vendido recebe quando ele é positivo e paga quando é negativo). Se a vela abre acima do ponto de
    liquidação (a parada não pega um salto de preço), perde a margem inteira daquela moeda.
No passado: as moedas que estrearam nos últimos ~15 meses, com velas de 1 h (até ~200 dias atrás) ou de 4 h (antes
disso; na vela em que a parada cabe, conta a parada). Ao vivo: as moedas que estrearem daqui para frente.
"""
from __future__ import annotations

HORA = 3600 * 1000
VERSAO = 1
CAPITAL = 1000.0
PARTE = 0.10            # margem de cada moeda: 10 % do patrimônio (dinheiro + margens abertas)
MAXIMO = 10             # moedas ao mesmo tempo
ESPERA_H = 24           # entra 24 h depois da estreia
PRAZO_H = 14 * 24       # sai em 14 dias
PARADA = 0.30           # sai se subir 30 %
TAXA = 0.00045 + 0.001  # taxa a mercado + derrapagem, em cada ponta
ALAVS = (1, 2)
PONTOS = 90             # pontos guardados do caminho de cada operação (o gráfico não precisa de mais)


def estreia_de(funding: list[dict]) -> int | None:
    """A hora da estreia: o primeiro funding é pago no fim da primeira hora cheia de negociação."""
    ts = [int(f["time"]) for f in funding or [] if f.get("time") is not None]
    return (min(ts) // HORA - 1) * HORA if ts else None


def manutencao(alav_max: float) -> float:
    """Margem de manutenção da Hyperliquid (fração do valor da posição): metade da margem inicial na alavancagem máxima."""
    return 1 / (2 * max(1.0, float(alav_max or 3)))


def simular(moeda: str, estreia: int, velas: list[dict], funding: dict[int, float], iv: int, fora: bool = False,
            alav_max: float = 3) -> dict | None:
    """Uma operação vendida na moeda (com 1×; a alavancagem entra na carteira). velas: {t, o, h, l, c} de `iv` ms;
    funding: {hora_em_ms: taxa por hora}. Devolve None se ainda não deu a hora de entrar (ou não há preço)."""
    vs = sorted((v for v in velas if int(v["t"]) >= estreia + ESPERA_H * HORA), key=lambda v: int(v["t"]))
    if not vs:
        return None
    t_e, px_e = int(vs[0]["t"]), float(vs[0]["o"])
    if px_e <= 0:
        return None
    parada, fim = px_e * (1 + PARADA), t_e + PRAZO_H * HORA
    horas = sorted(h for h in funding if h > t_e)
    j, fund, maior = 0, 0.0, 1.0
    caminho, saida = [], None
    for v in vs:
        t, o, hi, c = int(v["t"]), float(v["o"]), float(v["h"]), float(v["c"])
        if hi >= parada:                                  # a parada vem antes de tudo na vela (o pior caso)
            px = max(o, parada)
            maior = max(maior, px / px_e)
            caminho.append([t, round(px / px_e, 5), round(fund, 6)])
            saida = {"t": t, "px": px, "motivo": "parada: subiu 30 %"}
            break
        while j < len(horas) and horas[j] <= t + iv:     # funding de cada hora desta vela (vendido recebe a taxa)
            fund += funding[horas[j]] * (c / px_e)
            j += 1
        maior = max(maior, hi / px_e)
        caminho.append([t + iv, round(c / px_e, 5), round(fund, 6)])
        if t + iv >= fim:
            saida = {"t": t + iv, "px": c, "motivo": "14 dias"}
            break
    if saida is None and fora:                            # a moeda saiu da Hyperliquid antes dos 14 dias
        ult = vs[-1]
        saida = {"t": int(ult["t"]) + iv, "px": float(ult["c"]), "motivo": "saiu da Hyperliquid"}
    if len(caminho) > PONTOS:                             # guarda menos pontos (o último fica sempre)
        passo = len(caminho) / PONTOS
        caminho = [caminho[int(k * passo)] for k in range(PONTOS - 1)] + [caminho[-1]]
    rel = caminho[-1][1]
    return {"moeda": moeda, "estreia": estreia, "entrada": t_e, "px_e": px_e, "saida": saida["t"] if saida else None,
            "px_s": saida["px"] if saida else None, "motivo": saida["motivo"] if saida else None, "manut": manutencao(alav_max),
            "fund": round(fund, 6), "subiu_max": round(maior - 1, 4), "r1": round(r1(rel, fund), 5), "caminho": caminho}


def r1(rel: float, fund: float) -> float:
    """Resultado da venda com 1× sobre a margem, como se fechasse agora: a queda do preço, as duas taxas e o funding."""
    return (1 - rel) - TAXA - TAXA * rel + fund


def com_alav(op: dict, rel: float, fund: float, alav: float) -> float:
    """Resultado sobre a margem com `alav`×. Preço no ponto de liquidação (ou acima) = perde a margem inteira."""
    if rel >= 1 + 1 / alav - op.get("manut", manutencao(3)):
        return -1.0
    return max(-1.0, alav * r1(rel, fund))


def carteira(ops: list[dict], alav: float, inicio: int | None = None, capital: float = CAPITAL) -> dict:
    """Patrimônio de quem segue a regra: cada operação leva PARTE do patrimônio (dinheiro + margens) como margem, no
    máximo MAXIMO abertas. A curva marca as abertas pelo último preço (como se fechasse ali)."""
    ops = sorted(ops, key=lambda o: o["entrada"])
    entradas: dict[int, list] = {}
    for o in ops:
        entradas.setdefault(o["entrada"], []).append(o)
    tempos = sorted({o["entrada"] for o in ops} | {p[0] for o in ops for p in o["caminho"]} | ({inicio} if inicio else set()))
    dinheiro, abertas, feitas, puladas, curva = capital, [], [], 0, []
    for T in tempos:
        for o in entradas.get(T, []):
            if len(abertas) >= MAXIMO:
                puladas += 1
                continue
            m = PARTE * (dinheiro + sum(a["m"] for a in abertas))
            dinheiro -= m
            abertas.append({"o": o, "m": m, "k": -1})
        aberto = 0.0
        for a in list(abertas):
            cam = a["o"]["caminho"]
            while a["k"] + 1 < len(cam) and cam[a["k"] + 1][0] <= T:
                a["k"] += 1
            r = com_alav(a["o"], cam[a["k"]][1], cam[a["k"]][2], alav) if a["k"] >= 0 else -alav * TAXA
            if a["o"]["saida"] is not None and a["k"] == len(cam) - 1:      # chegou ao fim: fecha
                dinheiro += a["m"] * (1 + r)
                abertas.remove(a)
                feitas.append(r)
            else:
                aberto += a["m"] * (1 + r)
        curva.append([T, dinheiro + aberto])
    final = curva[-1][1] if curva else capital
    pico, pior = capital, 0.0
    for _, v in curva:
        pico = max(pico, v)
        pior = max(pior, (pico - v) / pico if pico > 0 else 0)
    dias = (curva[-1][0] - curva[0][0]) / (24 * HORA) if len(curva) > 1 else 0
    passo = max(1, len(curva) // 120)
    pontos = [[t, round(v / capital - 1, 5)] for t, v in curva[::passo]]
    if curva and pontos[-1][0] != curva[-1][0]:
        pontos.append([curva[-1][0], round(final / capital - 1, 5)])
    return {"patrimonio": round(final, 2), "retorno": round(final / capital - 1, 4),
            "ao_ano": round((final / capital) ** (365 / dias) - 1, 4) if dias >= 30 and final > 0 else None, "dias": round(dias, 1),
            "pior_queda": round(pior, 4), "operacoes": len(feitas), "acertos": sum(r > 0 for r in feitas), "abertas": len(abertas),
            "puladas": puladas, "curva": pontos}


def resumo_op(o: dict) -> dict:
    """A operação para o app (sem o caminho)."""
    rel, fund = (o["caminho"][-1][1], o["caminho"][-1][2]) if o["caminho"] else (1.0, 0.0)
    return {"moeda": o["moeda"], "estreia": o["estreia"], "entrada": o["entrada"], "px_e": o["px_e"], "saida": o["saida"], "px_s": o["px_s"],
            "motivo": o["motivo"], "aberta": o["saida"] is None, "subiu_max": o["subiu_max"], "funding": o["fund"],
            "preco": round(rel - 1, 4), "r": {str(a): round(com_alav(o, rel, fund, a), 4) for a in ALAVS}}
