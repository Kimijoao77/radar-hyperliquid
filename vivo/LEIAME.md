# A máquina 24 h (motor em tempo real)

Pedido do João (20/11/2026): operar os investimentos com o mínimo de atraso. Os testes de hora em hora continuam no
GitHub; aqui fica o que precisa de alguém acordado o tempo todo. **Tudo em simulação**: nesta pasta não existe chave
de corretora nem de carteira, e nenhuma ordem de verdade é enviada.

- **Onde**: uma VPS pequena em Tóquio (os servidores da Hyperliquid ficam lá), Ubuntu 24.04.
- `motor.py`: o processo que não para. Versão 1: sinal de vida (`saida/maquina.json`, com o tempo de resposta da
  Hyperliquid medido da máquina). Os robôs em tempo real entram na lista `ROBOS`.
- `instalar.sh`: prepara a máquina (roda uma vez, na criação). Cria o usuário `radar`, o ambiente Python e dois
  serviços: `radar-vivo` (o motor) e `radar-atualiza` (a cada 5 minutos).
- `atualizar.sh`: publica os resultados no repositório a cada 15 minutos e baixa o código novo; se o motor mudou,
  reinicia. Para atualizar a máquina basta mandar o código para o repositório.
- O texto que o João cola no painel da Vultr ("Cloud-Init User Data") são três linhas: o token e a chamada do
  `instalar.sh`. O token (escrita só neste repositório) fica só na máquina.
- O fluxo "Teste da máquina" instala tudo num Ubuntu limpo do GitHub, igual à VPS.

Este repositório é público: nada secreto pode ser guardado aqui, nunca.
