#!/usr/bin/env bash
# Roda na máquina 24 h, a cada 5 minutos (radar-atualiza.timer), como root:
#   1. a cada 15 minutos, publica no repositório o que o motor produziu (sinal de vida e resultados ao vivo);
#      o estado dos robôs vai uma vez por hora;
#   2. baixa o código novo; se mudou algo do motor, reinstala as dependências (se preciso) e reinicia o motor.
# Assim a máquina se atualiza sozinha: basta mandar o código para o repositório.
set -u
DIR=/opt/radar
R="runuser -u radar --"
G="$R git -C $DIR"
cd "$DIR" || exit 1
exec 9> /run/radar-atualiza.lock; flock -n 9 || exit 0     # uma rodada por vez

min=$((10#$(date +%M)))
if [ "${PUBLICAR:-0}" = "1" ] || [ $((min % 15)) -lt 5 ]; then
  # um por vez: se um caminho ainda não existe, o git recusa o comando inteiro
  for alvo in saida/maquina.json saida/*_ao_vivo.json; do
    [ -e "$alvo" ] && $G add -A "$alvo" 2>/dev/null
  done
  # o estado dos robôs (para a máquina poder ser refeita sem perder o teste) vai uma vez por hora: é maior e muda sempre
  if [ "${PUBLICAR:-0}" = "1" ] || [ "$min" -lt 5 ]; then
    [ -e vivo/dados ] && $G add -A vivo/dados 2>/dev/null
  fi
  if ! $G diff --cached --quiet; then
    $G commit -q -m "Máquina: $(date -u +'%Y-%m-%d %H:%M') UTC"
  fi
fi

antes=$($G rev-parse HEAD)
for i in 1 2 3 4; do
  $G pull -q --rebase --autostash && $G push -q && break
  sleep $((i * 5))
done
depois=$($G rev-parse HEAD)

if [ "$antes" != "$depois" ]; then
  mudou=$($G diff --name-only "$antes" "$depois" -- vivo lab radar requirements.txt | grep -v '^vivo/dados/' | grep -v '^lab/dados/' || true)
  if [ -n "$mudou" ]; then
    echo "$mudou" | grep -q '^requirements.txt$' && $R "$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"
    systemctl restart radar-vivo.service
    echo "código novo: motor reiniciado"
  fi
fi
exit 0
