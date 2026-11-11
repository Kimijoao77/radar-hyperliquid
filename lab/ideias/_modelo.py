"""Modelo de teste (não está no índice; serve de exemplo e para conferir as peças): compra BTC quando o preço fecha
acima da média de 50 horas e vende quando fecha abaixo. Copie este arquivo para lab/ideias/<id>.py e troque a regra."""
NOME = "Modelo: média de 50 h no BTC"
COMO = "Compra BTC acima da média de 50 horas e vende abaixo"
CAPITAL = 1000.0
INTERVALO_H = 1


def rodar(ctx):
    velas = ctx.hl.velas("BTC", "1h", 60)
    if len(velas) < 51:
        ctx.nota("ainda sem velas suficientes")
        return
    media = sum(v["c"] for v in velas[-51:-1]) / 50
    preco = velas[-1]["c"]
    comprado = "BTC" in ctx.carteira.posicoes
    if preco > media and not comprado:
        ctx.carteira.comprar("BTC", ctx.carteira.caixa, preco, obs=f"fechou acima da média ({media:,.0f})")
    elif preco < media and comprado:
        ctx.carteira.vender("BTC", preco, obs=f"fechou abaixo da média ({media:,.0f})")
    ctx.memoria["ultima_media"] = media
    ctx.nota(f"{'comprado' if 'BTC' in ctx.carteira.posicoes else 'em dólar'}; média de 50 h em US$ {media:,.0f}")
