#!/usr/bin/env bash
# Roda na máquina 24 h, a cada 5 minutos (radar-atualiza.timer), como root:
#   1. a cada 15 minutos, publica no repositório o que o motor produziu (sinal de vida e resultados ao vivo);
#      o estado dos robôs vai uma vez por hora;
#   2. baixa o código novo; se mudou algo do motor, reinstala as dependências (se preciso) e reinicia o motor.
# Assim a máquina se atualiza sozinha: basta mandar o código para o repositório.
#
# 21/11/2026: a máquina ficou ligada mas parou de publicar às 06:46. O mais provável é um git que travou na rede: sem
# limite de tempo, a rodada nunca terminava e as seguintes nem começavam. Agora cada comando do git tem 2 minutos, a
# rodada inteira tem 6, o git se conserta sozinho se ficar no meio de um rebase, o motor tem um teto de memória e, de
# hora em hora (e logo depois de ligar), vai junto um diagnóstico (vivo/diagnostico.txt) sem nada secreto.
set -u
DIR=/opt/radar
R="runuser -u radar --"
G="timeout -k 10 120 $R git -C $DIR"
cd "$DIR" || exit 1
exec 9> /run/radar-atualiza.lock; flock -n 9 || exit 0     # uma rodada por vez

# limites do systemd (só escreve e recarrega quando mudam)
limites() {
  local mudou=0
  mkdir -p /etc/systemd/system/radar-atualiza.service.d /etc/systemd/system/radar-vivo.service.d
  local a="[Service]
TimeoutStartSec=6min"
  local v="[Service]
MemoryHigh=650M
MemoryMax=800M
MemorySwapMax=600M"
  [ "$(cat /etc/systemd/system/radar-atualiza.service.d/limite.conf 2>/dev/null)" = "$a" ] || { echo "$a" > /etc/systemd/system/radar-atualiza.service.d/limite.conf; mudou=1; }
  [ "$(cat /etc/systemd/system/radar-vivo.service.d/memoria.conf 2>/dev/null)" = "$v" ] || { echo "$v" > /etc/systemd/system/radar-vivo.service.d/memoria.conf; mudou=1; }
  if [ "$mudou" = 1 ]; then systemctl daemon-reload; systemctl restart radar-vivo.service; fi
}
limites

# git preso no meio de um rebase ou com arquivo em conflito: volta para um estado limpo (perde no máximo a última hora
# do estado dos robôs, que é refeito)
if [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]; then $G rebase --abort 2>/dev/null; fi
presos=$($G diff --name-only --diff-filter=U 2>/dev/null)
if [ -n "$presos" ]; then
  $G reset -q
  echo "$presos" | while read -r f; do [ -n "$f" ] && $G checkout -q HEAD -- "$f" 2>/dev/null; done
fi

# diagnóstico: o que a máquina sabe dela mesma, sem segredo nenhum (o repositório é público)
diagnostico() {
  {
    echo "gerado: $(date -u +'%Y-%m-%d %H:%M UTC')"
    echo "ligada há: $(uptime -p)"; uptime
    echo; free -m; echo; df -h / | tail -1
    echo; echo "motor: $(systemctl is-active radar-vivo.service) desde $(systemctl show -p ActiveEnterTimestamp --value radar-vivo.service)"
    echo "reinícios do motor: $(systemctl show -p NRestarts --value radar-vivo.service)"
    echo; echo "== memória e travamentos (kernel, últimas 24 h) =="
    journalctl -k --since -24h --no-pager 2>/dev/null | grep -iE "out of memory|oom|killed process|hung task|blocked for" | tail -20
    echo; echo "== motor (últimas linhas) =="
    journalctl -u radar-vivo.service --since -3h --no-pager -n 25 2>/dev/null
    echo; echo "== atualização (últimas linhas) =="
    journalctl -u radar-atualiza.service --since -3h --no-pager -n 25 2>/dev/null
    if [ "$(cut -d. -f1 /proc/uptime)" -lt 1800 ]; then
      echo; echo "== antes de ligar desta vez (fim da vez anterior) =="
      journalctl -b -1 --no-pager -n 60 -p warning 2>/dev/null
    fi
  } 2>&1 | sed -E 's#x-access-token:[^@]*@#x-access-token:***@#g; s#(github_pat_|gh[pousr]_)[A-Za-z0-9_]+#\1***#g' | cut -c1-300 > vivo/diagnostico.txt
  chown radar: vivo/diagnostico.txt 2>/dev/null
}

min=$((10#$(date +%M)))
if [ "${PUBLICAR:-0}" = "1" ] || [ "$min" -lt 5 ] || [ "$(cut -d. -f1 /proc/uptime)" -lt 900 ]; then
  diagnostico
  $G add -A vivo/diagnostico.txt 2>/dev/null
fi
if [ "${PUBLICAR:-0}" = "1" ] || [ $((min % 15)) -lt 5 ] || [ "$(cut -d. -f1 /proc/uptime)" -lt 900 ]; then
  # um por vez: se um caminho ainda não existe, o git recusa o comando inteiro
  for alvo in saida/maquina.json vivo/gemeo/saida vivo/gemeo/gemeos.json; do
    [ -e "$alvo" ] && $G add -A "$alvo" 2>/dev/null
  done
  # o estado dos robôs (para a máquina poder ser refeita sem perder o teste) vai uma vez por hora: é maior e muda sempre
  if [ "${PUBLICAR:-0}" = "1" ] || [ "$min" -lt 5 ]; then
    for alvo in vivo/dados vivo/gemeo/lab; do
      [ -e "$alvo" ] && $G add -A "$alvo" 2>/dev/null
    done
  fi
  if ! $G diff --cached --quiet; then
    $G commit -q -m "Máquina: $(date -u +'%Y-%m-%d %H:%M') UTC"
  fi
fi

# arquivo da primeira versão do copy ao vivo, que o motor não escreve mais: sem mudança local, pode ser apagado do repositório
$G checkout -q -- saida/copia_ao_vivo.json 2>/dev/null

antes=$($G rev-parse HEAD)
for i in 1 2 3 4; do
  $G pull -q --rebase --autostash && $G push -q && break
  sleep $((i * 5))
done
depois=$($G rev-parse HEAD)

if [ "$antes" != "$depois" ]; then
  mudou=$($G diff --name-only "$antes" "$depois" -- vivo lab radar requirements.txt | grep -v '^vivo/dados/' | grep -v '^vivo/gemeo/' | grep -v '^lab/dados/' || true)
  if [ -n "$mudou" ]; then
    echo "$mudou" | grep -q '^requirements.txt$' && $R "$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"
    systemctl restart radar-vivo.service
    echo "código novo: motor reiniciado"
  fi
fi
exit 0
