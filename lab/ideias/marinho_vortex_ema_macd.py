"""Teste da ideia do vídeo "Como Ganhar 3x Mais Operando na Margex com o Indicador Vortex" (Canal do Marinho, 27/11/2026).
Setup do vídeo em velas de 4 horas do BTC: entra comprado quando o Vortex cruza para cima (VI+ acima de VI-), o preço
está acima da média exponencial de 200 e o MACD confirma (linha acima do sinal); vendido no espelho. Stop técnico
(parecido com o Chande Kroll Stop do vídeo: máxima/mínima de 10 velas menos/mais 1 ATR) e alvo de 2 para 1.
Sem alavancagem (o vídeo usa margem isolada com alavancagem; aqui é 1x para medir o setup em si), com taxa e funding."""
NOME = "Vortex + EMA 200 + MACD no BTC (4 h)"
COMO = "Entra comprado ou vendido no BTC quando Vortex, média de 200 e MACD apontam o mesmo lado; stop técnico e alvo 2:1"
CAPITAL = 1000.0
MOEDA = "US$"
INTERVALO_H = 1

RISCO = 3
GANHA = "Quando o BTC engata uma tendência firme e o preço anda o dobro do stop antes de voltar."
PERDE = "Quando o mercado fica de lado: os sinais aparecem, o preço volta, bate o stop e cada ida e volta paga taxa."
REGRAS = [
    ["Vortex", "Vortex de 14 velas de 4 h: VI+ cruzou acima de VI- (compra) ou VI- acima de VI+ (venda) nas últimas 3 velas fechadas."],
    ["EMA 200", "Só compra com o fechamento acima da média exponencial de 200 velas; só vende abaixo dela."],
    ["MACD", "MACD (12, 26, 9) confirmando: linha acima do sinal para comprar, abaixo para vender."],
    ["Stop", "Comprado: máxima das 10 últimas velas menos 1 ATR(10); vendido: mínima mais 1 ATR. Se ficar do lado errado, usa 1,5 ATR."],
    ["Alvo", "Duas vezes a distância do stop (2 para 1). Uma operação por vez, com todo o caixa, sem alavancagem."],
    ["Custos", "Taxa de 0,045 % na entrada e na saída (Hyperliquid) e o funding de cada hora com a posição aberta."],
]
ONDE = ["Hyperliquid (o vídeo usa a Margex, corretora sem regulação no Brasil)"]
PRECISA = ["USDC na Hyperliquid", "Um robô ou alerta que leia as velas de 4 h"]
PASSOS = [
    ["Espere o Placar", "Veja se o setup ganha do CDI por algumas semanas antes de pôr dinheiro."],
    ["Comece pequeno", "Com US$ 10 a 20, sem alavancagem, seguindo as mesmas regras."],
    ["Automatize", "Um alerta no TradingView com as três condições pode mandar a ordem por webhook."],
]
FONTE = "Hyperliquid (velas de 4 h e de 1 h do BTC, funding)"

ATIVO = "BTC"


def _ema(valores, n):
    k = 2 / (n + 1)
    out = []
    e = sum(valores[:n]) / n
    for i, v in enumerate(valores):
        if i < n:
            out.append(None)
            continue
        e = v * k + e * (1 - k)
        out.append(e)
    out[n - 1] = sum(valores[:n]) / n
    return out


def _tr(velas, i):
    v, ant = velas[i], velas[i - 1]
    return max(v["h"] - v["l"], abs(v["h"] - ant["c"]), abs(v["l"] - ant["c"]))


def _vortex(velas, i, n=14):
    vp = sum(abs(velas[j]["h"] - velas[j - 1]["l"]) for j in range(i - n + 1, i + 1))
    vm = sum(abs(velas[j]["l"] - velas[j - 1]["h"]) for j in range(i - n + 1, i + 1))
    tr = sum(_tr(velas, j) for j in range(i - n + 1, i + 1)) or 1e-9
    return vp / tr, vm / tr


def _macd(fech):
    e12, e26 = _ema(fech, 12), _ema(fech, 26)
    linha = [a - b for a, b in zip(e12[25:], e26[25:])]
    sinal = _ema(linha, 9)
    return linha[-1], sinal[-1]


def sinal(fechadas):
    """Recebe só velas FECHADAS (a mais nova por último). Devolve ("compra" | "venda" | None, stop, alvo, texto)."""
    if len(fechadas) < 230:
        return None, None, None, "poucas velas"
    fech = [v["c"] for v in fechadas]
    i = len(fechadas) - 1
    preco = fech[-1]
    ema200 = _ema(fech, 200)[-1]
    linha, sig = _macd(fech)
    vx = [_vortex(fechadas, j) for j in range(i - 3, i + 1)]      # 4 leituras para achar cruzamento nas 3 últimas
    cruzou_cima = any(vx[k - 1][0] <= vx[k - 1][1] and vx[k][0] > vx[k][1] for k in range(1, 4))
    cruzou_baixo = any(vx[k - 1][1] <= vx[k - 1][0] and vx[k][1] > vx[k][0] for k in range(1, 4))
    vp, vm = vx[-1]
    atr = sum(_tr(fechadas, j) for j in range(i - 9, i + 1)) / 10
    texto = f"EMA200 {ema200:,.0f}; VI+ {vp:.2f} / VI- {vm:.2f}; MACD {linha - sig:+.0f}"
    if cruzou_cima and vp > vm and preco > ema200 and linha > sig:
        stop = max(v["h"] for v in fechadas[-10:]) - atr
        if stop >= preco:
            stop = preco - 1.5 * atr
        return "compra", stop, preco + 2 * (preco - stop), texto
    if cruzou_baixo and vm > vp and preco < ema200 and linha < sig:
        stop = min(v["l"] for v in fechadas[-10:]) + atr
        if stop <= preco:
            stop = preco + 1.5 * atr
        return "venda", stop, preco - 2 * (stop - preco), texto
    return None, None, None, texto


def rodar(ctx):
    c = ctx.carteira
    m = ctx.memoria
    pos = c.posicoes.get(ATIVO)
    agora = ctx.hl.precos().get(ATIVO)
    if not agora:
        ctx.nota("sem preço do BTC agora")
        return

    # 1) posição aberta: funding da hora e stop/alvo pela última vela de 1 h fechada
    if pos:
        f = ctx.hl.contextos().get(ATIVO, {}).get("funding_h", 0.0)
        nocional = pos["qtd"] * agora
        horas = max(1, round((ctx.agora - m.get("ultimo_funding", ctx.agora - 3600000)) / 3600000))
        horas = min(horas, 6)
        # comprado paga funding positivo; vendido recebe
        c.creditar((-1 if pos.get("lado") != "venda" else 1) * nocional * f * horas, "funding", ATIVO)
        m["ultimo_funding"] = ctx.agora
        h1 = ctx.hl.velas(ATIVO, "1h", 3)
        ult = h1[-2] if len(h1) >= 2 else {"h": agora, "l": agora}
        stop, alvo = m.get("stop"), m.get("alvo")
        if pos.get("lado") == "venda":
            if ult["h"] >= stop:
                c.fechar_venda(ATIVO, max(stop, ult.get("o", stop)), obs="bateu o stop")
            elif ult["l"] <= alvo:
                c.fechar_venda(ATIVO, alvo, obs="bateu o alvo 2:1")
        else:
            if ult["l"] <= stop:
                c.vender(ATIVO, min(stop, ult.get("o", stop)), obs="bateu o stop")
            elif ult["h"] >= alvo:
                c.vender(ATIVO, alvo, obs="bateu o alvo 2:1")
        pos = c.posicoes.get(ATIVO)
        if pos:
            lado = "vendido" if pos.get("lado") == "venda" else "comprado"
            ctx.nota(f"{lado} em BTC desde US$ {pos['preco_medio']:,.0f}; stop {stop:,.0f}, alvo {alvo:,.0f}")
            return

    # 2) sem posição: procura sinal na última vela de 4 h fechada (uma vez por vela)
    velas = ctx.hl.velas(ATIVO, "4h", 300)
    fechadas = velas[:-1]
    if not fechadas:
        ctx.nota("sem velas")
        return
    if m.get("ultima_vela") == fechadas[-1]["t"]:
        ctx.nota(f"esperando sinal; {m.get('texto', '')}")
        return
    m["ultima_vela"] = fechadas[-1]["t"]
    lado, stop, alvo, texto = sinal(fechadas)
    m["texto"] = texto
    if lado == "compra":
        c.comprar(ATIVO, c.caixa, agora, obs=f"sinal de compra; {texto}")
    elif lado == "venda":
        c.abrir_venda(ATIVO, c.caixa, agora, obs=f"sinal de venda; {texto}")
    if lado and ATIVO in c.posicoes:
        m["stop"], m["alvo"], m["ultimo_funding"] = stop, alvo, ctx.agora
        ctx.nota(f"entrou {'comprado' if lado == 'compra' else 'vendido'} em US$ {agora:,.0f}; stop {stop:,.0f}, alvo {alvo:,.0f}")
    else:
        ctx.nota(f"esperando sinal; {texto}")
