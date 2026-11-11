# Testes das ideias dos vídeos

Quando o Claude acha uma ideia de dinheiro boa num vídeo (os canais estão em `ideias/youtube/canais.json`, no Engfy) e ela
dá para testar com dados públicos, ele mesmo escreve um teste aqui. O teste roda de hora em hora junto com o laboratório,
com dinheiro de mentira, e o resultado aparece no Placar (Nexus › Investimentos e site). O João é avisado de cada teste novo.

**Regras que não mudam**

- Só simulação. Nada aqui manda ordem, entra em conta, usa chave de API, senha ou carteira de verdade.
- Só dados públicos e sem chave (Hyperliquid, DefiLlama, Banco Central, Yahoo Finance, CoinGecko e parecidos).
- Nada de olhar o futuro: a decisão de cada rodada usa só o que já tinha acontecido naquela hora.
- Custos sempre: taxa de cada compra e venda, funding de quem fica vendido, custo de entrar e sair de pool.

## Quando uma ideia vira teste

Vira teste se tiver as três coisas:

1. **Uma regra objetiva**: dá para escrever "se acontecer X, faz Y" sem depender de opinião na hora.
2. **Dados públicos que mostram X e o preço de Y** (veja "Peças" abaixo).
3. **Uma simulação honesta**: o resultado de mentira fica perto do que aconteceria de verdade, com custos.

Se falta uma delas (precisa de conta, de KYC, de gente fazendo à mão, de dado fechado, ou é dica genérica tipo "invista no
longo prazo"), a ideia **não** vira teste: vai para o João como "apresentar" (veja `ideias/youtube/LEIAME.md`).

## Passo a passo

1. **Escolha o id**: letras minúsculas, números e `_`, começando pelo canal. Ex.: `sardinha_fii_papel`, `defi_pool_usdc_base`.
   O id é o nome do arquivo e do módulo Python, então nada de hífen nem acento.
2. **Copie** `lab/ideias/_modelo.py` para `lab/ideias/<id>.py` e escreva a regra em `rodar(ctx)`. No topo:

   ```python
   NOME = "Nome curto para o app"
   COMO = "Uma linha: o que o robô faz"
   CAPITAL = 1000.0          # dinheiro de mentira
   MOEDA = "US$"             # ou "R$" para ideias da bolsa brasileira
   INTERVALO_H = 1           # 1 = toda hora; 24 = uma vez por dia (bom para bolsa e juros)

   # a página do teste no app (escreva para o João, em português simples):
   RISCO = 3                 # 1 baixo, 2 médio, 3 alto, 4 muito alto
   GANHA = "Quando ... (uma frase)"
   PERDE = "Quando ... (uma frase)"
   REGRAS = [["Título curto", "a regra em uma frase"], ...]          # as regras do teste, com custos
   ONDE = ["Hyperliquid"]                                           # onde daria para fazer de verdade
   PRECISA = ["USDC na Hyperliquid"]                                # o que precisaria ter
   PASSOS = [["Passo", "como fazer"], ...]                          # como fazer de verdade com pouco dinheiro
   FONTE = "Hyperliquid (velas de 1 h)"                             # de onde vêm os dados
   ```

3. **Registre** em `lab/ideias/indice.json` (uma lista):

   ```json
   {"id": "sardinha_fii_papel", "nome": "FIIs de papel x CDI", "como": "Compra os 5 FIIs de papel...",
    "capital": 5000, "moeda": "R$", "criado": "2026-11-12", "ativo": false, "conferir": true,
    "origem": {"canal": "Investidor Sardinha", "video_id": "abc123", "titulo": "Título do vídeo",
               "url": "https://youtu.be/abc123", "minuto": "12:30"}}
   ```

   Comece sempre com `"ativo": false, "conferir": true`.
4. **Confira aqui** se der: `python lab/rodar_ideias.py --so <id> --seco` (roda uma vez sem gravar nada). Na sessão do
   Claude o proxy costuma bloquear as APIs; aí teste a lógica com dados falsos e deixe a conferência para o GitHub.
5. **Envie** (`git push`). O fluxo **Ideias: conferir teste novo** (`.github/workflows/ideias-conferir.yml`) roda o teste
   uma vez com os dados de verdade:
   - funcionou: põe `"ativo": true` e o laboratório passa a rodar de hora em hora;
   - deu erro: deixa desligado e guarda o erro em `"erro_conferencia"`.
6. **Na próxima leitura**, olhe o `indice.json`: teste com `erro_conferencia` é para corrigir e marcar `"conferir": true`
   de novo. Teste rodando com `"erro"` em `saida/ideias.json` também é para corrigir.

Para **parar** um teste: `"ativo": false` e `"motivo_parada": "frase curta"`. Ele continua aparecendo no app como parado,
com o resultado até ali. Não apague o arquivo de quem já rodou.

## Peças (`ctx`)

| Peça | O que é |
|---|---|
| `ctx.carteira.caixa` / `.posicoes` | Dinheiro parado e posições (`{ativo: {qtd, preco_medio, lado, margem}}`) |
| `ctx.carteira.comprar(ativo, usd, preco, taxa=TAXA_HL, obs="")` | Gasta `usd` (na moeda do teste, mesmo se for R$) e a taxa sai daí |
| `ctx.carteira.vender(ativo, preco, qtd=None, taxa=..., obs="")` | Vende tudo (ou `qtd`) |
| `ctx.carteira.abrir_venda(...)` / `fechar_venda(...)` | Venda a descoberto sem alavancagem (a margem é o valor) |
| `ctx.carteira.creditar(valor, motivo, ativo="")` | Rendimento (+) ou custo (−) direto no caixa: juros, taxa de pool, funding, gás |
| `ctx.memoria` | Dicionário livre que fica guardado entre as rodadas |
| `ctx.nota("frase")` | A frase que aparece no app (o que o robô está fazendo agora) |
| `ctx.precos_extras[ativo] = preco` | Preço de ativo de fora da Hyperliquid, para avaliar a carteira |
| `ctx.hl.precos()` / `.velas(moeda, "1h", n)` / `.contextos()` / `.funding_historico(moeda, desde_ms)` | Hyperliquid (cripto, perpétuos) |
| `ctx.llama.pools()` / `.historico(pool_id)` | DefiLlama: rendimento e tamanho de pools, empréstimos e cofres |
| `ctx.br.juros("cdi" \| "selic" \| "ipca", n)` | Banco Central: CDI e Selic em % ao dia útil, IPCA em % no mês |
| `ctx.br.b3("HGLG11", n)` / `.preco("PETR4")` | B3: os últimos n pregões de ação, FII ou ETF (`[{dia, o, h, l, c, volume}]`), do arquivo público da série histórica |
| `ctx.br.pregao(date)` | Todas as cotações à vista de um dia da B3 (`{ticker: {o, h, l, c, volume}}`): bom para ranking e carteira |
| `ctx.br.velas("AAPL", "1y")` / `.proventos(t)` | Yahoo Finance (velas longas, proventos, ações de fora, `BRL=X`). **Recusou o GitHub em 11/11 (429)**: use só se a conferência passar; para a B3, prefira `b3()` e guarde o histórico em `ctx.memoria` |
| `ctx.buscar(url, navegador=False)` | Qualquer API pública em JSON |

Cada rodada tem até 2 minutos. Peça só os dados que vai usar (as respostas de `precos`, `contextos`, `pools` e `velas` do
Yahoo ficam guardadas na rodada, então chamar duas vezes não custa nada).

## Como deixar a simulação honesta

- **Velas**: a última vela de `velas()` ainda está aberta; use `[-2]` para a última fechada quando a regra for "fechou acima".
- **Taxas**: Hyperliquid 0,045 % (o padrão). Bolsa brasileira: use `taxa=0.0003` (emolumentos) e lembre do imposto na
  venda se a ideia for de giro. Corretora de cripto à vista: 0,1 %. DEX: 0,3 % mais o gás com `creditar(-gas, "gás")`.
- **Rendimento de pool ou empréstimo**: credite por hora, `creditar(valor * apy / 100 * horas / 8760, "rendimento")`,
  usando o APY daquela hora (`ctx.llama.pools()`), não um número fixo do vídeo.
- **Funding**: quem está vendido em perpétuo recebe (ou paga) `funding_h` por hora sobre o valor da posição; credite.
- **Juros do caixa**: se a ideia diz "deixa o resto no CDI", credite o CDI do dia no caixa (`INTERVALO_H = 24`).
- **Proventos**: para FIIs e ações, credite os proventos na data com e guarde em `ctx.memoria` quais já entraram, para
  não creditar duas vezes. Sem o Yahoo, use o rendimento anunciado pelo fundo (confira na web ao criar o teste) e
  confira de novo a cada leitura.
- **B3**: o arquivo de um pregão sai à noite; rode com `INTERVALO_H = 24` e compre ou venda no fechamento do último
  pregão (`ctx.br.b3(t)[-1]["c"]`), pondo o preço em `ctx.precos_extras[t]` para avaliar a carteira.
- **Capital**: use o valor que a ideia sugere (R$ 5.000 para bolsa, US$ 1.000 para cripto, se ela não disser).

## Exemplos

- `lab/ideias/_modelo.py`: compra BTC acima da média de 50 horas (não está no índice; serve de modelo).
- Os laboratórios antigos (`lab/rodar_cofres.py`, `rodar_pools.py`, `rodar_funding.py`, `rodar_grade.py`) mostram
  rendimento de pool, funding e grade com custo; dá para copiar a conta de lá.
