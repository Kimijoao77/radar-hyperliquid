"""Laboratório 2: robôs de grade (grid) e de DCA, sem dinheiro, com as velas de 1 hora da Hyperliquid.

Grade: divide uma faixa de preço (em volta do preço do começo) em N degraus. Em cada degrau abaixo do preço fica uma
ordem de compra; quando compra, põe a venda no degrau de cima. Ganha a cada sobe e desce dentro da faixa.
Se o preço sai por cima, fica só com dinheiro (perdeu a alta); se sai por baixo, fica com a moeda caindo.

DCA (o dos robôs): compra um pouco; se cair X %, compra mais (cada compra maior que a anterior) até um limite;
vende tudo quando o preço passa Y % acima do preço médio. Quase sempre acerta; numa queda grande e sem volta, prende
todo o dinheiro e (com alavancagem) pode zerar a conta.

Tendência (versão 4): o contrário dos dois acima. Fica comprado quando o preço está em alta e vendido quando está em
queda, sempre no mercado. Dois jeitos: cruzamento de médias (a média curta passa a longa) e rompimento (o preço passa
da máxima, ou da mínima, dos últimos N dias). Perde um pouco nos vai e vens e ganha nas tendências longas, inclusive nas
quedas (a venda ganha quando o preço cai).

Em cada vela, o caminho do preço dentro da hora não é conhecido: a conta é conservadora (nunca compra e vende o mesmo
degrau na mesma hora). Taxas: ordem limitada 0,015 %, a mercado 0,045 % (Hyperliquid).

Funding (versão 4): quem está comprado paga, de hora em hora, a taxa de financiamento do perpétuo (quase sempre
positiva: BTC ~11 % ao ano sobre a posição) e quem está vendido recebe. Com 3× a posição vale 3 vezes o dinheiro, então o
custo sobe junto. Antes da versão 4 a conta ignorava isso; agora usa o histórico real da Hyperliquid (fundingHistory).
"""
from __future__ import annotations

from collections import deque

HORA = 3600 * 1000
ANO_H = 24 * 365
MAKER, TAKER = 0.00015, 0.00045
SLIP = 0.0002                                             # derrapagem de uma ordem a mercado (valores pequenos em moedas grandes)
BANDA = 0.002                                             # cruzamento de médias: só vira quando a curta passa 0,2 % da longa


def _queda(curva: list[float]) -> float:
    pico, pior = 0.0, 0.0
    for v in curva:
        pico = max(pico, v)
        if pico > 0:
            pior = max(pior, (pico - v) / pico)
    return pior


def _pontos(ts: list[int], curva: list[float], n: int = 80) -> list[list]:
    if not curva:
        return []
    passo = max(1, len(curva) // n)
    out = [[ts[i], round(curva[i], 2)] for i in range(0, len(curva), passo)]
    if out[-1][0] != ts[-1]:
        out.append([ts[-1], round(curva[-1], 2)])
    return out


def _taxas(velas: list[dict], funding: dict | None) -> list[float] | None:
    """Taxa de funding paga no fim de cada vela (a Hyperliquid paga de hora em hora), alinhada com as velas.
    funding: {hora_em_ms: taxa por hora}. Hora sem dado repete a última taxa conhecida (0 se ainda não houve nenhuma)."""
    if not funding:
        return None
    out, ult = [], 0.0
    for v in velas:
        ult = funding.get(int(v["t"]) + HORA, ult)
        out.append(float(ult))
    return out


def grade(velas: list[dict], faixa: float, niveis: int, alav: float = 1.0, capital: float = 1000.0, ops: list | None = None,
          funding: dict | None = None) -> dict:
    """Grade "neutra" de compra: faixa ±faixa em volta do preço de abertura da primeira vela."""
    p0 = float(velas[0]["o"])
    baixo, alto = p0 * (1 - faixa), p0 * (1 + faixa)
    L = [baixo + (alto - baixo) * i / niveis for i in range(niveis + 1)]
    qtd = capital * alav / niveis / p0                        # mesma quantidade em cada degrau
    caixa, moeda = capital, 0.0
    segura = []                                               # por degrau i (L[i] → L[i+1]): comprado?
    for i in range(niveis):
        if L[i + 1] > p0:                                     # degraus acima do preço: já compra no começo
            caixa -= qtd * p0 * (1 + TAKER)
            moeda += qtd
            segura.append(True)
        else:
            segura.append(False)
    if ops is not None and any(segura):
        n0 = sum(segura)
        ops.append({"t": int(velas[0]["t"]), "tipo": "compra", "px": p0, "valor": round(qtd * p0 * n0, 2), "obs": f"{n0} degraus de começo"})
    ciclos, lucro_grade, fora, liquidada = 0, 0.0, 0, False
    curva, ts = [], []
    tx, pago = _taxas(velas, funding), 0.0
    for k, v in enumerate(velas):
        lo, hi, c = float(v["l"]), float(v["h"]), float(v["c"])
        vendeu = set()
        for i in range(niveis):                               # vendas primeiro (degraus comprados)
            if segura[i] and hi >= L[i + 1]:
                caixa += qtd * L[i + 1] * (1 - MAKER)
                moeda -= qtd
                segura[i] = False
                vendeu.add(i)
                ciclos += 1
                lucro_grade += qtd * (L[i + 1] - L[i])
                if ops is not None:
                    ops.append({"t": int(v["t"]), "tipo": "venda", "px": L[i + 1], "valor": round(qtd * L[i + 1], 2), "lucro": round(qtd * (L[i + 1] - L[i]) - qtd * (L[i] + L[i + 1]) * MAKER, 2)})
        for i in range(niveis):                               # depois as compras (não no degrau que acabou de vender)
            if not segura[i] and i not in vendeu and lo <= L[i]:
                caixa -= qtd * L[i] * (1 + MAKER)
                moeda += qtd
                segura[i] = True
                if ops is not None:
                    ops.append({"t": int(v["t"]), "tipo": "compra", "px": L[i], "valor": round(qtd * L[i], 2)})
        if c < baixo or c > alto:
            fora += 1
        if tx is not None and moeda > 0:                      # funding: quem está comprado paga (a taxa é sobre o valor da posição)
            pg = moeda * c * tx[k]
            caixa -= pg
            pago += pg
        patrimonio = caixa + moeda * c
        if alav > 1 and patrimonio <= capital * 0.05:          # com alavancagem: a margem acabou
            liquidada, patrimonio = True, 0.0
            curva.append(0.0); ts.append(int(v["t"]))
            break
        curva.append(patrimonio); ts.append(int(v["t"]))
    return _resumo(velas, curva, ts, capital, {"ciclos": ciclos, "lucro_dos_degraus": round(lucro_grade, 2),
                                               "fora_da_faixa": round(fora / max(1, len(curva)), 3), "liquidada": liquidada,
                                               "funding_pago": round(pago, 2)})


def dca(velas: list[dict], passo: float, alvo: float, ordens: int = 5, escala: float = 1.5, alav: float = 1.0, capital: float = 1000.0,
        ops: list | None = None, media_h: int = 0, historico: list[float] | None = None, funding: dict | None = None) -> dict:
    """Robô de DCA comprado: 1 compra base + até `ordens` compras de segurança a cada `passo` de queda; vende com `alvo` de lucro.
    media_h > 0: pausa na tendência de queda — só abre um ciclo novo se o último fechamento estiver acima da média das
    últimas `media_h` horas (o ciclo já aberto segue normal). `historico`: fechamentos de antes, para a média já valer."""
    pesos = [escala ** k for k in range(ordens + 1)]
    base = capital * alav / sum(pesos)
    caixa, qtd, gasto, n_comp = capital, 0.0, 0.0, 0
    p_ent = None
    ciclos, horas_presas, maior_preso, preso_desde = 0, 0, 0, None
    liquidada = False
    curva, ts = [], []
    fechados = list(historico or [])[-media_h:] if media_h else []
    soma, pausadas = sum(fechados), 0
    tx, pago = _taxas(velas, funding), 0.0
    for k, v in enumerate(velas):
        lo, hi, c, t = float(v["l"]), float(v["h"]), float(v["c"]), int(v["t"])
        if qtd == 0 and media_h and len(fechados) >= media_h and fechados[-1] < soma / media_h:
            pausadas += 1                                     # tendência de queda: fica no caixa nesta hora
            curva.append(caixa); ts.append(t)
            fechados.append(c); soma += c - fechados.pop(0)
            continue
        if qtd == 0:                                          # abre um ciclo na abertura da vela
            p_ent = float(v["o"])
            q = base / p_ent
            caixa -= q * p_ent / alav + q * p_ent * TAKER
            qtd, gasto, n_comp = q, q * p_ent, 1
            preso_desde = t
            if ops is not None:
                ops.append({"t": t, "tipo": "compra", "px": p_ent, "valor": round(q * p_ent, 2), "obs": "compra base"})
        # compras de segurança
        while n_comp <= ordens and lo <= p_ent * (1 - passo * n_comp):
            px = p_ent * (1 - passo * n_comp)
            q = base * pesos[n_comp] / px
            caixa -= q * px / alav + q * px * MAKER
            qtd += q; gasto += q * px; n_comp += 1
            if ops is not None:
                ops.append({"t": t, "tipo": "compra", "px": px, "valor": round(q * px, 2), "obs": f"compra de segurança {n_comp - 1}"})
        medio = gasto / qtd
        if hi >= medio * (1 + alvo):                          # alvo: vende tudo
            px = medio * (1 + alvo)
            receita = qtd * px * (1 - MAKER)
            caixa += gasto / alav + (receita - gasto)
            ciclos += 1
            if ops is not None:
                ops.append({"t": t, "tipo": "venda", "px": px, "valor": round(receita, 2), "lucro": round(receita - gasto, 2), "obs": "alvo atingido"})
            maior_preso = max(maior_preso, (t - preso_desde) / HORA)
            qtd = gasto = 0.0
            n_comp = 0
            patrimonio = caixa
        else:
            horas_presas += 1
            if tx is not None:                                # funding: a posição comprada paga a taxa sobre o valor dela
                pg = qtd * c * tx[k]
                caixa -= pg
                pago += pg
            aberto = (qtd * c - gasto)                        # ganho ou perda da posição aberta
            patrimonio = caixa + gasto / alav + aberto
            if alav > 1 and patrimonio <= capital * 0.05:
                liquidada, patrimonio = True, 0.0
                curva.append(0.0); ts.append(t)
                break
        curva.append(patrimonio); ts.append(t)
        if media_h:
            fechados.append(c); soma += c
            if len(fechados) > media_h:
                soma -= fechados.pop(0)
    if qtd and preso_desde:
        maior_preso = max(maior_preso, (ts[-1] - preso_desde) / HORA)
    return _resumo(velas, curva, ts, capital, {"ciclos": ciclos, "horas_com_posicao": round(horas_presas / max(1, len(curva)), 3),
                                               "maior_tempo_preso_h": round(maior_preso), "liquidada": liquidada,
                                               "horas_pausado": round(pausadas / max(1, len(curva)), 3), "funding_pago": round(pago, 2)})


def _ema(valores: list[float], n: int) -> list[float]:
    """Média móvel exponencial de n horas (começa no primeiro valor)."""
    k, out, e = 2 / (n + 1), [], None
    for x in valores:
        e = x if e is None else e + k * (x - e)
        out.append(e)
    return out


def _janela(valores: list[float], n: int, maior: bool) -> list[float | None]:
    """Para cada posição i, o maior (ou o menor) dos n valores ANTES dela; None enquanto não há n valores."""
    out, fila = [], deque()
    for i, x in enumerate(valores):
        while fila and fila[0] < i - n:
            fila.popleft()
        out.append(valores[fila[0]] if fila and i >= n else None)
        while fila and (valores[fila[-1]] <= x if maior else valores[fila[-1]] >= x):
            fila.pop()
        fila.append(i)
    return out


def tendencia(velas: list[dict], modo: str, a: int, b: int | None = None, alav: float = 1.0, capital: float = 1000.0,
              ops: list | None = None, antes: list[dict] | None = None, funding: dict | None = None) -> dict:
    """Robô de tendência, comprado ou vendido, sempre no mercado.
    modo "medias": comprado se a média de `a` horas está acima da de `b` horas (vendido se abaixo), com uma faixa de 0,2 %.
    modo "rompe": comprado quando o fechamento passa da máxima das últimas `a` horas; vendido quando passa da mínima.
    A decisão sai no fechamento de uma vela e vale na abertura da próxima. `antes`: velas de antes do começo, para as
    médias e os canais já valerem. Liquidada se, no pior ponto da vela, sobrar menos de 5 % do capital."""
    antes = list(antes or [])
    todas = antes + list(velas)
    n0 = len(antes)
    fech = [float(v["c"]) for v in todas]
    if modo == "medias":
        rapida, lenta = _ema(fech, a), _ema(fech, b)
        pronto = b                                            # as médias precisam de ~b horas para fazer sentido
    else:
        topo, fundo = _janela([float(v["h"]) for v in todas], a, True), _janela([float(v["l"]) for v in todas], a, False)
        pronto = a
    tx, pago = _taxas(velas, funding), 0.0
    real, q, pe, pos, alvo = capital, 0.0, 0.0, 0, 0          # real = dinheiro sem a posição aberta; q = unidades (negativo = vendido)
    trocas, horas_pos, horas_comp, liquidada = 0, 0, 0, False
    curva, ts = [], []
    for k, v in enumerate(velas):
        i = n0 + k
        o, hi, lo, c, t = float(v["o"]), float(v["h"]), float(v["l"]), float(v["c"]), int(v["t"])
        if alvo != pos:                                       # a decisão do fechamento anterior vale na abertura desta vela
            if pos:
                lucro = q * (o - pe) - abs(q) * o * (TAKER + SLIP)
                real += lucro
                if ops is not None:
                    ops.append({"t": t, "tipo": "venda" if q > 0 else "compra", "px": o, "valor": round(abs(q) * o, 2),
                                "lucro": round(lucro, 2), "obs": "fecha a posição comprada" if q > 0 else "fecha a posição vendida"})
                q, pos = 0.0, 0
            if alvo:
                q = alvo * real * alav / o
                real -= abs(q) * o * (TAKER + SLIP)
                pe, pos = o, alvo
                if ops is not None:
                    ops.append({"t": t, "tipo": "compra" if alvo > 0 else "venda", "px": o, "valor": round(abs(q) * o, 2),
                                "obs": "abre comprado: preço em alta" if alvo > 0 else "abre vendido: preço em queda"})
            trocas += 1
        if pos and real + q * ((lo if pos > 0 else hi) - pe) <= capital * 0.05:   # margem acabou no pior ponto da hora
            liquidada = True
            curva.append(0.0); ts.append(t)
            break
        if pos and tx is not None:                            # funding: comprado paga, vendido recebe (taxa positiva)
            pg = q * c * tx[k]
            real -= pg
            pago += pg
        curva.append(real + (q * (c - pe) if pos else 0.0)); ts.append(t)
        if pos:
            horas_pos += 1
            horas_comp += pos > 0
        if i >= pronto:                                       # decide para a próxima vela
            if modo == "medias":
                alvo = 1 if rapida[i] > lenta[i] * (1 + BANDA) else -1 if rapida[i] < lenta[i] * (1 - BANDA) else alvo
            else:
                alvo = 1 if topo[i] is not None and c > topo[i] else -1 if fundo[i] is not None and c < fundo[i] else alvo
    return _resumo(velas, curva, ts, capital, {"ciclos": trocas, "horas_com_posicao": round(horas_pos / max(1, len(curva)), 3),
                                               "horas_comprado": round(horas_comp / max(1, horas_pos), 3), "liquidada": liquidada,
                                               "funding_pago": round(pago, 2)})


def _resumo(velas, curva, ts, capital, extra) -> dict:
    final = curva[-1] if curva else capital
    horas = max(1, len(curva))
    p0, p1 = float(velas[0]["o"]), float(velas[min(len(velas), len(curva)) - 1]["c"])
    return {"final": round(final, 2), "retorno": round(final / capital - 1, 4),
            "ao_ano": round((final / capital - 1) * ANO_H / horas, 4) if horas >= 24 * 7 else None,
            "pior_queda": round(_queda(curva), 4), "segurar_moeda": round(p1 / p0 - 1, 4),
            "dias": round(horas / 24, 1), "curva": _pontos(ts, curva), **extra}


MEDIA_H = 168                                             # pausa do DCA: média de 7 dias

# Versão 2 (09/11/2026): só 1×. Na versão 1 as escolhidas eram todas 3× e, numa semana de queda, a grade de HYPE
# perdeu 36 %. O DCA ganhou a pausa na tendência de queda (com e sem, para comparar).
CONFIGS = (
    [{"tipo": "grade", "faixa": f, "niveis": n, "alav": a} for f in (0.10, 0.20) for n in (10, 20) for a in (1, 2)]
    + [{"tipo": "dca", "passo": s, "alvo": g, "alav": a, "pausa": pz} for s in (0.02, 0.03) for g in (0.015, 0.03) for pz in (False, True)
       for a in (1, 2, 3)]
)


# Versão 4 (10/11): robôs de tendência (comprado e vendido), o contrário da grade e do DCA, que perdem em queda forte.
TENDENCIA = (
    [{"tipo": "tendencia", "modo": "medias", "a": a, "b": b, "alav": al} for a, b in ((12, 48), (24, 96), (48, 168), (72, 336)) for al in (1, 2, 3)]
    + [{"tipo": "tendencia", "modo": "rompe", "a": n, "alav": al} for n in (48, 120, 240) for al in (1, 2, 3)]
)
TODAS = CONFIGS + TENDENCIA


def nome(c: dict) -> str:
    if c["tipo"] == "grade":
        return f"Grade ±{round(c['faixa'] * 100)} %, {c['niveis']} degraus{'' if c['alav'] == 1 else f', {c['alav']}×'}"
    if c["tipo"] == "tendencia":
        base = f"Tendência: médias de {c['a']} h e {c['b']} h" if c["modo"] == "medias" else f"Tendência: rompimento de {c['a'] // 24} dias"
        return base + ("" if c["alav"] == 1 else f", {c['alav']}×")
    return (f"DCA a cada −{round(c['passo'] * 100)} %, alvo +{c['alvo'] * 100:g} %{'' if c['alav'] == 1 else f', {c['alav']}×'}"
            + (", pausa na queda" if c.get("pausa") else ""))


def rodar(c: dict, velas: list[dict], ops: list | None = None, historico: list[float] | None = None, antes: list[dict] | None = None,
          funding: dict | None = None) -> dict:
    """ops: se for uma lista, recebe cada compra e venda (só no ao vivo; no passado seriam milhares).
    historico: fechamentos de antes das velas (a média da pausa já vale desde a primeira hora).
    antes: as velas de antes (a tendência usa para as médias e os canais já valerem). funding: {hora: taxa} da moeda."""
    if c["tipo"] == "grade":
        return grade(velas, c["faixa"], c["niveis"], c["alav"], ops=ops, funding=funding)
    if c["tipo"] == "tendencia":
        return tendencia(velas, c["modo"], c["a"], c.get("b"), alav=c["alav"], ops=ops, antes=antes, funding=funding)
    return dca(velas, c["passo"], c["alvo"], alav=c["alav"], ops=ops, media_h=MEDIA_H if c.get("pausa") else 0, historico=historico, funding=funding)


def nota(r: dict) -> float:
    """Retorno por risco (liquidada = fora)."""
    if r.get("liquidada"):
        return -9
    return r["retorno"] / max(0.05, r["pior_queda"])


def ao_ano(r: dict) -> float:
    if r.get("liquidada"):
        return -1.0
    return (1 + r["retorno"]) ** (365 / max(1.0, r["dias"])) - 1


def nota_lucro(dentro: dict, fora: dict) -> float:
    """Versão 3 (10/11, pedido do João: o máximo de lucro, risco aceito): o pior retorno ao ano entre os 2/3 do passado
    onde a regra foi escolhida e o 1/3 que ela não viu; liquidada em qualquer um dos dois = fora."""
    if dentro.get("liquidada") or fora.get("liquidada"):
        return -9
    return min(ao_ano(dentro), ao_ano(fora))


def nota_honesta(dentro: dict, fora: dict) -> float:
    """Para escolher as que vão para o ao vivo sem escolher a dedo: a pior das duas notas — a dos primeiros 2/3 do
    passado (onde a regra foi escolhida) e a do último 1/3 (que a escolha não viu)."""
    return min(nota(dentro), nota(fora))


FAMILIAS = {"reverter": ("grade", "dca"), "tendencia": ("tendencia",)}


def _sinal(r: dict) -> tuple:
    """A mesma estratégia na mesma moeda com outra alavancagem é o mesmo robô: só conta uma vez (o de maior nota)."""
    return (r["moeda"], tuple(sorted((k, v) for k, v in r["config"].items() if k != "alav")))


def escolher(passado: list[dict], por_familia: int = 3, por_moeda: int = 2) -> list[dict]:
    """Quem vai para o ao vivo (versão 5): 3 de grade/DCA e 3 de tendência, já ordenados por nota (maior lucro ao ano no pior
    dos dois pedaços do passado). Nunca liquidado; até 2 na mesma moeda em cada família; a mesma estratégia na mesma moeda
    entra uma vez só (2× e 3× do mesmo sinal seriam o mesmo palpite). Grade/DCA só entra com nota > 0; a tendência entra
    mesmo no vermelho, porque o teste serve justamente para saber se ela funciona."""
    out = []
    for fam, tipos in FAMILIAS.items():
        n, cont, vistos = 0, {}, set()
        for r in passado:
            if r["config"]["tipo"] not in tipos or r.get("liquidada") or (fam == "reverter" and r["nota"] <= 0):
                continue
            if cont.get(r["moeda"], 0) >= por_moeda or _sinal(r) in vistos:
                continue
            vistos.add(_sinal(r))
            out.append(r)
            cont[r["moeda"]] = cont.get(r["moeda"], 0) + 1
            n += 1
            if n == por_familia:
                break
    return out
