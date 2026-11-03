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
