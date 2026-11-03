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

## Como funciona (fase 1)

A cada 2 horas o GitHub Actions roda dois scripts e guarda o resultado aqui no repositório:

1. **`coletar.py`**
   - Uma vez por dia baixa o leaderboard (dezenas de milhares de carteiras) e aplica o **pré-filtro** (`config.json → filtro`):
     - conta de pelo menos US$ 10 mil e volume relevante no mês;
     - ROI do mês entre 3 % e 300 %: acima disso costuma ser uma aposta só;
     - lucro no total;
     - (o corte por giro alto, de market maker, está desligado desde 03/11: o João decide se copia).
   - As melhores entram na **lista de observação** (até 120, no máximo 25 novas por dia).
   - Para cada carteira observada, baixa os fills (cada execução de ordem) e tira uma foto do saldo e das posições. Na primeira vez, baixa os últimos 90 dias.
2. **`analisar.py`**
   - Monta as **operações** (entrou → saiu) a partir dos fills, já descontando as taxas.
   - Mede acerto, fator de lucro, retorno médio, queda máxima, semanas positivas, tempo segurando a posição e ordens limitadas × a mercado.
   - Faz o **teste de sorte x habilidade**:
     - p-valor por bootstrap: se o ganho real fosse zero, qual a chance de ver um resultado assim?
     - **q** (Benjamini-Hochberg): desconta o fato de olharmos muitas carteiras de uma vez. Quanto menor, melhor; até 0,10 já é forte.
     - Lucro que depende de uma única tacada = sorte.
     - As duas metades do período precisam estar no azul.
     - **O teste que mais vale:** o desempenho **depois** que a carteira entrou no radar, porque esse período não foi usado para escolhê-la.
   - Classifica cada carteira:
     - **Habilidade provável:** números fortes e continuou ganhando depois que entrou no radar.
     - **Promissora:** números fortes, mas ainda falta o período acompanhado.
     - **Em observação:** menos de 30 operações.
     - **Sorte provável.**
     - **Perdendo.**
   - **Dá para copiar?** é só uma informação ao lado (mais de 60 operações por dia, posições de menos de 5 min ou cara de market maker). Não muda a classe nem descarta: o João decide.
   - Descarta só as perdedoras e as sortudas, depois de 21 dias, para liberar vaga.
   - Grava `saida/relatorio.json` (o app Nexus mostra no app **Radar**) e `saida/relatorio.md`.

## Números para copiar (`radar/copia.py`)

Para a aba **Cópia** do Nexus (simulação e projeção, sem dinheiro), cada carteira leva no relatório:
- **resultado de cada dia** (até 150 dias) e o **saldo de referência** (o maior entre o saldo das fotos e o de quando entrou no radar), para virar % da conta;
- **o que sobra com atraso:** o lucro só das operações que duram mais que 5 s, 30 s, 2 min e 10 min;
- **giro por dia e taxa média**, para estimar o custo extra de copiar;
- **alavancagem:** a configurada nas posições e a exposição real (posições abertas ÷ saldo), pelas fotos da conta.

`saida/historico.json` guarda um ponto por rodada (carteiras por classe e o resultado depois de entrar no radar) para o painel "Como está indo".

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
