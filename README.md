# Radar Hyperliquid

Robô que acompanha carteiras de traders da Hyperliquid para separar quem **ganha por habilidade**
de quem **teve sorte**, e começar a descobrir **como cada um opera** (o "robô" por trás).
Inspirado no vídeo do Craft Gold sobre copytrading (17 mil carteiras → poucas para copiar).

Tudo usa a API pública e gratuita da Hyperliquid (sem conta e sem chave). **Nada aqui compra ou vende.**

## Fases

| Fase | O que faz | Situação |
|---|---|---|
| 1. Radar | Escolhe carteiras no leaderboard, coleta todas as operações, mede e classifica (sorte x habilidade), descreve o estilo | **pronta** |
| 2. Engenharia reversa | Cruza cada entrada com as velas (RSI, médias, rompimentos, funding, horário) e testa regras por tentativa e erro até achar a que mais se parece com as escolhas do trader | próxima |
| 3. Cópia simulada | Copia as melhores com atraso real e ordens de US$ 10, sem dinheiro, para ver o que sobra depois do atraso e das taxas | depois |
| 4. Cópia real | Liga no Cérebro (ou executa direto na Hyperliquid) com limites de risco | só se a 3 provar |

## O plano (desde 03/11)

- **Avaliação de 2 meses** (`dias_de_avaliacao: 60`) para cada carteira que entra.
- **Só promissoras ficam.** Quem deixa de ser promissora é descartada na hora e não aparece mais no app.
- **Carteiras novas uma vez por semana**, por triagem: as melhores do leaderboard são medidas com 90 dias de histórico
  e só entram as que já são promissoras (`triagem_por_semana: 60`). As recusadas podem ser testadas de novo depois de 30 dias.
- **Análise de hora em hora** das carteiras no radar.
- No fim dos 2 meses: com **habilidade confirmada**, vira **aprovada** e continua sendo acompanhada; sem confirmar, é descartada.

## Como funciona

A cada hora o GitHub Actions roda dois scripts e guarda o resultado aqui no repositório:

1. **`coletar.py`**
   - Uma vez por semana baixa o leaderboard (dezenas de milhares de carteiras) e aplica o **pré-filtro** (`config.json → filtro`):
     conta de pelo menos US$ 10 mil e volume relevante no mês; ROI do mês entre 3 % e 300 %; lucro no total.
     As melhores vão para a **fila de triagem**.
   - Para cada carteira no radar, baixa os fills (cada execução de ordem) novos e tira uma foto do saldo e das posições.
   - Com o tempo que sobra, faz a **triagem** da fila (continua na próxima rodada se não terminar).
2. **`analisar.py`**
   - Monta as **operações** (entrou → saiu) a partir dos fills, já descontando as taxas.
   - Mede acerto, fator de lucro, retorno médio, queda máxima, semanas positivas, tempo segurando a posição.
   - **Sorte x habilidade:** p-valor por bootstrap e **q** (Benjamini-Hochberg, desconta o fato de olharmos muitas
     carteiras); lucro de uma tacada só = sorte; as duas metades do período no azul; e o teste que mais vale,
     o desempenho **depois** que a carteira entrou no radar.
   - Classes: **Habilidade provável** (números fortes e continuou ganhando depois de entrar) e **Promissora**
     (números fortes, falta o período acompanhado). As outras (sorte, perdendo) saem.
   - **Dá para copiar?** é só informação: não muda a classe nem descarta.
   - Grava `saida/relatorio.json` (o app Nexus mostra no app **Radar**; só as carteiras no radar) e `saida/relatorio.md`.

## Projeção de lucro (`radar/copia.py`)

Para a aba **Copiando** do Nexus: o resultado de cada dia de cada carteira (até 150 dias), o saldo de referência
(para virar % da conta), quanto do lucro sobra copiando com atraso (só operações mais longas que o atraso),
o giro por dia e a taxa média (custo extra da cópia) e a alavancagem vista nas fotos da conta.

## Humano ou robô (`radar/operador.py`)

Nota de 0 (humano) a 100 (robô), começando em 50, somando sinais tirados das ordens:
- **Horário de dormir:** um bloco de 5 h ou mais sempre parado = humano.
- **Horas ativas:** ordens espalhadas pelas 24 h = robô.
- **Fechamento de vela:** muitas ordens nos segundos 0–2 do minuto = robô. O acaso dá uns 5 %.
- **Rajadas:** moedas diferentes no mesmo segundo, ou 20 ou mais ordens por minuto.
- **Tamanho redondo:** 0,5 · 100 · 1.000 = humano; quantidades quebradas = robô.
- **Intervalos regulares:** pausas sempre do mesmo tamanho.
- **ID próprio nas ordens (cloid):** coletado a partir de 03/11.

65 ou mais = Robô provável; 35 ou menos = Humano provável. A lista exata com os pesos está em `CRITERIOS`.

## Laboratório (`lab/`): estratégias de alto risco, sem dinheiro

Roda de hora em hora num workflow separado (`Laboratório`). Tudo é simulação com dados públicos.

**0. Cópia fiel (`lab/copia.py`, desde 09/11)** — a cópia como ela seria de verdade. A projeção do radar
(`radar/copia.py`) só estima: pega o resultado do dia da carteira e desconta uma fração pelo atraso, sem saber em que
preço o copiador entraria. Aqui cada mudança de posição da carteira vira uma ordem do copiador **1 minuto depois**, no
**preço daquele minuto** (velas de 1 min da Hyperliquid; de 5 min para o que tem mais de 3 dias), com taxa de 0,045 % e
0,05 % de escorregamento. O copiador segue a carteira **em proporção da conta** (mesma fração do saldo). Cada carteira
ganha uma subconta de US$ 1.000; o teste é a soma. Começa sem posição e entra na primeira mudança de cada moeda.
- Um copy trading só (desde 09/11, versão 3): o **seletivo**. A regra "todas" (todas as carteiras, na alavancagem delas,
  até 10×) ficou só nos testes, para comparar.
- **seletiva**: só as copiáveis (mediana de 30 min ou mais com a posição aberta e o radar diz que dá), com a exposição
  levada a 2× da típica dela (no máximo 3×) e **parada de proteção**: caiu 25 % do pico, para de copiar aquela carteira.
- Funding fica de fora. Spot e pares de terceiros também. → `saida/copia_fiel.json`, estado em `lab/dados/copia_estado.json`.
- Versão 2 (09/11), que refez tudo desde 03/11: fills do mesmo instante seguem a cadeia "posição antes → depois" (a API
  manda em qualquer ordem, e a cópia ficava com restos de posições que a carteira já tinha fechado); posição que some da
  foto da conta sem fill (mercado encerrado) zera na cópia também; mercados de terceiros (HIP-3, `xyz:GOLD`) ficam de
  fora, porque têm saldo separado que a foto não vê, e quem opera mais de 80 % neles não entra; a curva tem um ponto
  por hora cheia, inclusive na rodada que refaz os dias passados.

**1. Funding (`lab/funding.py`)** — comprar à vista e vender o mesmo valor no perpétuo da Hyperliquid: o preço se anula e
sobra o funding (pago de hora em hora; positivo = quem está vendido recebe). Carteira simulada de US$ 1.000:
- só moedas líquidas (US$ 5 mi negociados no dia e US$ 2 mi em posições abertas);
- entra nas que pagam mais na média de 72 h (acima de 20 % ao ano), até 5 posições;
- sai quando a média de 24 h cai abaixo de 5 % ao ano ou o funding fica negativo 6 horas seguidas;
- troca uma posição só se a nova pagar 15 pontos ao ano a mais;
- paga 0,045 % no perpétuo + 0,10 % à vista + 0,03 % de escorregamento em cada ponta, ao entrar e ao sair;
- perpétuo com 2×: avisa quando uma alta de 40 % teria exigido reforçar a margem;
- versão 2 (09/11): só moedas com mercado à vista de verdade (`COM_SPOT`: BTC, ETH, SOL, HYPE e outras grandes). A
  versão 1 escolhia moedas pequenas (USELESS, PONS, CASHCAT) que pagavam bem, mas que não dá para comprar à vista
  numa corretora comum: o teste não era repetível.

Mostra o "teste no passado" (últimos 30 dias, refeito a cada hora) e o "ao vivo" (desde 03/11/2026).
Grava `saida/funding.json`. Os números ficam em `config.json → lab.funding` (se não estiver lá, vale o padrão do código).

**2. Grade e DCA (`lab/grade.py`)** — velas de 1 h da Hyperliquid (~200 dias) de BTC, ETH, SOL e HYPE.
12 configurações por moeda (grade ±10/±20 %, 10/20 degraus; DCA a cada −2/−3 %, alvo +1,5/+3 %, com e sem pausa na queda).
Taxas: limitada 0,015 %, a mercado 0,045 %. Conservador: nunca compra e vende o mesmo degrau na mesma hora. → `saida/grade.json`
Versão 2 (09/11): **só 1×** (na versão 1 as escolhidas eram 3× e, na semana de queda, a grade de HYPE perdeu 36 %); o DCA
ganhou a **pausa na queda** (só abre ciclo novo com o preço acima da média de 7 dias); e a escolha das 2 grades e dos 2 DCA
que vão ao vivo usa a **pior nota** entre os primeiros 2/3 do passado e o último 1/3, que a escolha não vê (para não
escolher a dedo a regra que só deu certo no passado). O resultado da versão 1 fica em `anterior`.

**3. Cofres (`lab/cofres.py`)** — a cada 6 h: lista pública de cofres; os 40 maiores (abertos, US$ 100 mil+, 60 dias+)
com histórico; índice de rendimento que ignora depósitos e saques; constante = p ≤ 0,05, pior queda ≤ 20 %,
60 % das semanas no azul. Depósito simulado de US$ 1.000 nos 5 mais constantes + HLP, menos 10 % do lucro para o dono. → `saida/cofres.json`

**4. Pools e looping (`lab/pools.py`)** — a cada 12 h, DefiLlama: pools de estáveis e de duas moedas voláteis
(US$ 5 mi+, 30 dias de dados), só o rendimento de taxas (o de prêmio fica à parte), perda impermanente de 30 dias com
o preço das moedas; looping de wstETH/weETH/rETH/cbETH contra ETH nos protocolos de empréstimo (2×, 3×, 4×) e o
descolamento que liquida. Carteira simulada: 3 estáveis + 3 voláteis + o melhor looping. → `saida/pools.json`

**5. Opções (`lab/opcoes.py`)** — de hora em hora, dados públicos da Deribit: vende put semanal ~10 % abaixo e call
coberta ~10 % acima, em BTC e ETH, US$ 1.000 cada; vende pelo bid, paga a taxa e liquida no preço de entrega. → `saida/opcoes.json`

**6. Apostas esportivas (`lab/apostas.py`, desde 09/11)** — a cada 3 h, football-data.co.uk (grátis): odds da bolsa
(Betfair Exchange) e a média das casas, pegas na sexta e na terça à tarde, e os resultados. Aposta US$ 10 na bolsa quando
a odd, já sem a comissão de 5 %, paga acima da justa (média das casas sem a margem, método da potência). O ajuste (limiar,
faixa de odds, com ou sem empate) é escolhido na temporada de 2 anos atrás e conferido nas seguintes; cada aposta é
comparada com a odd de fechamento da bolsa (CLV). A Pinnacle saiu dos dados em 2025. → `saida/apostas.json`

**7. Memecoins (`lab/memecoins.py`, desde 09/11)** — de hora em hora, GeckoTerminal (grátis, poucas chamadas por minuto):
moedas novas da pump.fun. Duas estratégias com o mesmo caixa: a mais disputada no lançamento e a que sobreviveu e
dobrou na 1ª hora. 1 % do patrimônio por compra, 3 % de custo em cada lado, metade a 2×, o resto a 5×, parada em −50 %
e prazo de 24 h, com as velas de 5 min (o pior caso quando a parada e o alvo caem na mesma vela). → `saida/memecoins.json`

**8. Pools concentradas (`lab/concentradas.py`, desde 09/11; versão 2 desde 09/11 às 17h)** — de hora em hora, API da
Meteora (DLMM, Solana) e velas do GeckoTerminal. Versão 2, depois do estudo de ~150 pools em 8 dias (ensaio
`coleta_pools.py` + `estudo_pools.py`): depósito **só em SOL/USDC numa faixa logo abaixo do preço** (sem troca na
entrada; se o preço sobe, fica todo em SOL e sai sem perda) e **só pools com o preço calmo** (desvio das variações de
1 h nas últimas 24 h abaixo de 2 %), a maior taxa sobre a liquidez em 24 h entre elas (US$ 10 mil+ de liquidez, US$ 50
mil+ de volume). Três faixas abaixo do preço (até −10 %, −30 %, −60 %), US$ 1.000 cada, até 3 pools por faixa; recebe a
taxa da última hora só enquanto o preço está na faixa, sai quando uma vela de 5 min fecha fora ou em 24 h; na saída
paga a venda só da parte que virou moeda. No estudo: −0,06 % por posição na metade ruim do período e +1,3 % na boa
(faixa estreita); a versão 1 (troca de metade na entrada, só a maior taxa) perdeu ~2 % na metade ruim. → `saida/concentradas.json`

## Arquivos

- `config.json`: todos os números do filtro e da classificação. Mudou aqui, a próxima rodada já usa.
- `dados/carteiras.json`: a lista de observação (quando entrou, como estava na entrada, situação).
- `dados/fills/<carteira>/AAAA-MM.jsonl`: as execuções, uma por linha.
- `dados/contas/AAAA-MM.jsonl`: as fotos do saldo e das posições.
- `radar/`: o código (`api.py`, `selecao.py`, `trades.py`, `metricas.py`, `estilo.py`, `armazenamento.py`).
- `testes/`: testes com uma Hyperliquid de mentira. Para rodar: `python -m pytest -q`.

## Rodar no PC (opcional)

```bash
pip install -r requirements.txt
python coletar.py      # coleta (pode demorar alguns minutos na primeira vez)
python analisar.py     # gera saida/relatorio.md
```

## Limites

A API aceita 1200 de "peso" por minuto e o radar usa no máximo 1000. A Hyperliquid só guarda os
10 mil fills mais recentes de cada conta, então carteiras muito ativas têm menos histórico.

**Aviso:** resultado passado não garante resultado futuro. Copiar tem atraso, taxas e escorregamento,
e alavancagem aumenta as perdas tanto quanto os ganhos.
