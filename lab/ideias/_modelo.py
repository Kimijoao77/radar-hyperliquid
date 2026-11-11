"""Modelo de teste (não está no índice; serve de exemplo e para conferir as peças): compra BTC quando a última vela de
1 hora fecha acima da média de 50 horas e vende quando fecha abaixo. Copie este arquivo para lab/ideias/<id>.py e troque
a regra (guia: lab/ideias/COMO.md)."""
NOME = "Modelo: média de 50 h no BTC"
COMO = "Compra BTC quando fecha acima da média de 50 horas e vende quando fecha abaixo"
CAPITAL = 1000.0
INTERVALO_H = 1
RISCO = 3
GANHA = "Quando o BTC engata uma subida longa: o robô fica comprado o caminho todo."
PERDE = "Quando o preço fica indo e voltando em volta da média: cada vai e vem paga taxa e sai um pouco pior."
REGRAS = [["Entrada", "Compra com todo o caixa quando a última vela de 1 h fecha acima da média das 50 anteriores."],
          ["Saída", "Vende tudo quando uma vela fecha abaixo da média."],
          ["Custos", "Taxa de 0,045% em cada compra e venda (Hyperliquid)."]]
ONDE = ["Hyperliquid"]
PRECISA = ["USDC na Hyperliquid"]
PASSOS = [["Deposite USDC", "Na Hyperliquid, pela rede Arbitrum."], ["Siga a regra", "Uma vez por hora, ou com um robô."]]
FONTE = "Hyperliquid (velas de 1 hora do BTC)"


def rodar(ctx):
    velas = ctx.hl.velas("BTC", "1h", 60)          # a última ainda está aberta
    if len(velas) < 53:
        ctx.nota("ainda sem velas suficientes")
        return
    media = sum(v["c"] for v in velas[-52:-2]) / 50
    fechou = velas[-2]["c"]                         # a última vela fechada
    agora = velas[-1]["c"]                          # o preço de agora (é nele que compra ou vende)
    comprado = "BTC" in ctx.carteira.posicoes
    if fechou > media and not comprado:
        ctx.carteira.comprar("BTC", ctx.carteira.caixa, agora, obs=f"fechou acima da média ({media:,.0f})")
    elif fechou < media and comprado:
        ctx.carteira.vender("BTC", agora, obs=f"fechou abaixo da média ({media:,.0f})")
    ctx.memoria["ultima_media"] = media
    ctx.nota(f"{'comprado' if 'BTC' in ctx.carteira.posicoes else 'em dólar'}; média de 50 h em US$ {media:,.0f}")
