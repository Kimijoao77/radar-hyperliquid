# A máquina 24 h (motor em tempo real)

Pedido do João (20/11/2026): operar os investimentos com o mínimo de atraso. Os testes de hora em hora continuam no
GitHub; aqui fica o que precisa de alguém acordado o tempo todo. **Tudo em simulação**: nesta pasta não existe chave
de corretora nem de carteira, e nenhuma ordem de verdade é enviada.

- **Onde**: uma VPS pequena em Tóquio (os servidores da Hyperliquid ficam lá), Ubuntu 24.04.
- `motor.py`: o processo que não para. Dá o sinal de vida (`saida/maquina.json`, com o tempo de resposta da
  Hyperliquid medido da máquina) e chama os robôs em tempo real (lista `ROBOS`) várias vezes por segundo.
- **Gêmeos** (pedido do João em 20/11: "com todos os investimentos" e "as mesmas ordens que faz no normal, para poder
  comparar"): cada teste de hora em hora (o "normal") tem um gêmeo na máquina, que parte do mesmo estado, usa o mesmo
  código e as mesmas regras, e guarda tudo em `vivo/gemeo/` (`saida/*.json` no mesmo formato do normal). O Nexus põe os
  dois lado a lado desde a partida.
- `copia.py`: o gêmeo do copy trading, em tempo real. Parte das subcontas do laboratório; a cada poucos segundos olha
  a conta de cada carteira do radar e, quando a posição dela muda, cada cópia ajusta a sua subconta na mesma volta, no
  preço do livro de ofertas daquele instante (ao vivo não existe a espera de 60 s ou 10 s que o laboratório supõe).
  Mede o atraso de detecção e o custo do atraso. Resultado em `vivo/gemeo/saida/copia_fiel.json`; estado em
  `vivo/dados/copia_estado.json`.
- **Diário das medidas** (`vivo/dados/medidas.json`, desde 20/11/2026): o estado só guarda as últimas 400 mudanças
  (meio dia), e essas medidas não dá para refazer depois. O diário guarda um resumo por dia (UTC), para sempre:
  mudanças vistas, atraso de detecção e custo do atraso (n, mediana, média, p90 e pior) e o tamanho médio da ordem.
  Fica fora do estado do robô, então não é zerado quando as regras mudam de versão. É com ele que o "ambiente" da
  evolução (evolucao-hyperliquid: hoje 60 s e 0,05 %, números supostos) vai ser acertado com números medidos.
  **Pendente (decidido com o João em 20/11):** a evolução não muda por enquanto. Com umas 2 semanas de diário, se a
  máquina se mostrar melhor que o normal, nasce uma segunda população na evolução, ao lado da atual (que não é
  tocada), já com o atraso e o custo medidos aqui. Primeiras horas (56 medidas): atraso mediano de 1,5 s; custo
  mediano de 0,02 %, médio de 0,06 %, e 10 % das ordens saíram 0,29 % ou mais piores que as da carteira.
- `gemeos.py`: os gêmeos dos outros laboratórios (grade/tendência/reversão, cofres, pools concentradas, listagens,
  previsões), um por vez, cada um num processo separado e no ritmo da máquina. Os que decidem em velas de 1 hora
  (grade, tendência, reversão, listagens) dão o mesmo resultado do normal por construção; onde o ritmo importa
  (pools a cada 10 min, cofres de hora em hora) o gêmeo age mais cedo. `vivo/gemeo/gemeos.json` diz quando cada um
  partiu e como foi a última rodada.
- `instalar.sh`: prepara a máquina (roda uma vez, na criação). Cria o usuário `radar`, o ambiente Python e dois
  serviços: `radar-vivo` (o motor) e `radar-atualiza` (a cada 5 minutos).
- `atualizar.sh`: publica os resultados no repositório a cada 15 minutos (o estado, uma vez por hora) e baixa o
  código novo; se o motor mudou, reinicia. Para atualizar a máquina basta mandar o código para o repositório.
- O texto que o João cola no painel da Vultr ("Cloud-Init User Data") são três linhas: o token e a chamada do
  `instalar.sh`. O token (escrita só neste repositório) fica só na máquina.
- O fluxo "Teste da máquina" instala tudo num Ubuntu limpo do GitHub, igual à VPS.

Este repositório é público: nada secreto pode ser guardado aqui, nunca.
