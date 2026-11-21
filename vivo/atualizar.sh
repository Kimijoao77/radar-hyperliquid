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
#
# 21/11/2026 (depois da reinstalação): o conserto acima ficou pronto às 08:41 e nunca chegou, porque a máquina só recebia
# código novo pelo git, que era justamente o que estava travado, e reiniciar não resolveu (o travamento ficou gravado no
# disco). Agora:
#   - este arquivo se atualiza sozinho pelo endereço público do GitHub (raw), sem depender do git: um conserto futuro
#     chega em até 5 minutos mesmo com o git quebrado;
#   - travas velhas do git (index.lock e outras, que sobram quando um git morre no meio) são apagadas;
#   - se a máquina passar 30 minutos sem conseguir publicar, com o GitHub aceitando a chave, ela baixa o repositório de novo
#     do zero e troca a cópia quebrada, guardando os dados do robô.
set -u
DIR="${RADAR_DIR:-/opt/radar}"
REPO="${RADAR_REPO:-Kimijoao77/radar-hyperliquid}"
ESTADO="${RADAR_ESTADO:-/var/lib/radar}"
R="${RADAR_R-runuser -u radar --}"
G="timeout -k 10 120 $R git -C $DIR"
SC="${RADAR_SYSTEMCTL:-systemctl}"
mkdir -p "$ESTADO"
exec 9> "${RADAR_TRAVA:-/run/radar-atualiza.lock}"; flock -n 9 || exit 0     # uma rodada por vez

# 1. este arquivo se atualiza pelo endereço público, antes de qualquer coisa (só troca se o novo for um script válido)
EU="$DIR/vivo/atualizar.sh"
if [ -z "${RADAR_JA_ATUALIZOU:-}" ] && [ -z "${RADAR_SEM_RAW:-}" ]; then
  novo="$ESTADO/atualizar.novo"
  if timeout 40 curl -fsSL -o "$novo" "https://raw.githubusercontent.com/$REPO/main/vivo/atualizar.sh?t=$(date +%s)" \
     && [ -s "$novo" ] && head -1 "$novo" | grep -q '^#!/usr/bin/env bash' && bash -n "$novo" && ! cmp -s "$novo" "$EU"; then
    cat "$novo" > "$EU"                       # mesmo arquivo (mesmo dono e permissões); o git vê como mudança local
    echo "atualizar.sh novo (pelo endereço público): rodando de novo"
    exec 9>&-
    RADAR_JA_ATUALIZOU=1 exec /bin/bash "$EU"
  fi
fi
cd "$DIR" || exit 1

# 2. travas velhas do git: só quando nenhum git está rodando e a trava tem mais de 10 minutos
if ! pgrep -x git >/dev/null 2>&1; then
  find "$DIR/.git" -maxdepth 4 -name '*.lock' -mmin +10 -print -delete 2>/dev/null | sed 's/^/trava velha do git apagada: /'
fi

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
  if [ "$mudou" = 1 ]; then $SC daemon-reload; $SC restart radar-vivo.service; fi
}
[ -z "${RADAR_TESTE:-}" ] && limites

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
    if [ -s /run/radar-envio.log ]; then
      echo; echo "== último envio ao GitHub que falhou =="
      tail -n 25 /run/radar-envio.log
      echo; echo "== git =="
      $G status -sb 2>&1 | head -15
      $G log --oneline -5 2>&1
      $G log --oneline origin/main -3 2>&1
    fi
    if [ "$(cut -d. -f1 /proc/uptime)" -lt 1800 ]; then
      echo; echo "== antes de ligar desta vez (fim da vez anterior) =="
      journalctl -b -1 --no-pager -n 60 -p warning 2>/dev/null
    fi
  } 2>&1 | sed -E 's#x-access-token:[^@]*@#x-access-token:***@#g; s#(github_pat_|gh[pousr]_)[A-Za-z0-9_]+#\1***#g' | cut -c1-300 > vivo/diagnostico.txt
  chown radar: vivo/diagnostico.txt 2>/dev/null
}

# baixa o repositório de novo do zero e troca a cópia quebrada. Guarda o ambiente Python, os dados do robô e o que o
# motor publicou; a cópia antiga fica em $DIR.anterior até a próxima troca (para olhar o que deu errado).
reclonar() {
  local url novo="$DIR.novo"
  url=$(git -C "$DIR" config --get remote.origin.url 2>/dev/null) || return 1
  [ -n "$url" ] || return 1
  rm -rf "$novo"
  echo "cópia do repositório quebrada há mais de 30 min: baixando de novo"
  timeout -k 10 600 git clone -q "$url" "$novo" || { rm -rf "$novo"; echo "não consegui baixar de novo"; return 1; }
  $SC stop radar-vivo.service 2>/dev/null
  for p in .venv vivo/dados vivo/gemeo saida/maquina.json vivo/diagnostico.txt; do
    if [ -e "$DIR/$p" ]; then rm -rf "${novo:?}/$p"; mkdir -p "$(dirname "$novo/$p")"; cp -a "$DIR/$p" "$novo/$p"; fi
  done
  git -C "$novo" config user.name "radar-maquina"
  git -C "$novo" config user.email "radar-maquina@users.noreply.github.com"
  git -C "$novo" config pull.rebase true
  [ -n "${RADAR_TESTE:-}" ] || chown -R radar:radar "$novo"
  chmod 600 "$novo/.git/config"
  rm -rf "$DIR.anterior"
  mv "$DIR" "$DIR.anterior" && mv "$novo" "$DIR"
  cd "$DIR" || return 1
  $SC start radar-vivo.service 2>/dev/null
  echo "cópia nova no lugar; a antiga ficou em $DIR.anterior"
  return 0
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
enviou=0
for i in 1 2 3 4; do
  if $G pull -q --rebase --autostash > /run/radar-envio.log 2>&1 && $G push -q >> /run/radar-envio.log 2>&1; then enviou=1; break; fi
  sleep $((i * 5))
done
depois=$($G rev-parse HEAD)
if [ "$enviou" = 1 ]; then
  : > /run/radar-envio.log
  date +%s > "$ESTADO/ultimo-envio-ok"
else
  # 30 minutos sem publicar, com o GitHub respondendo: a cópia do repositório está quebrada. Baixa de novo e troca.
  ok=$(cat "$ESTADO/ultimo-envio-ok" 2>/dev/null || echo 0)
  [ "$ok" = 0 ] && { date +%s > "$ESTADO/ultimo-envio-ok"; ok=$(date +%s); }      # primeira vez: começa a contar agora
  # só refaz se o GitHub responde e aceita a chave (git ls-remote): aí o defeito é na cópia local, não na rede nem na chave
  if [ $(( $(date +%s) - ok )) -gt 1800 ] \
     && timeout -k 5 60 git ls-remote -q "$(git -C "$DIR" config --get remote.origin.url 2>/dev/null)" HEAD >/dev/null 2>&1; then
    if reclonar; then
      date +%s > "$ESTADO/ultimo-envio-ok"
      exit 0                                  # a próxima rodada (em 5 min) já publica com a cópia nova
    fi
  fi
  # não conseguiu publicar na main: manda o diagnóstico num ramo à parte, só com esse arquivo (assim dá para ver o
  # motivo mesmo se o problema for um commit que o GitHub recusa)
  diagnostico
  blob=$($G hash-object -w vivo/diagnostico.txt)
  arvore=$(printf '100644 blob %s\tdiagnostico.txt\n' "$blob" | $G mktree)
  c=$($G commit-tree "$arvore" -m "Diagnóstico da máquina: $(date -u +'%Y-%m-%d %H:%M') UTC")
  $G push -q -f origin "$c:refs/heads/maquina-diagnostico" >> /run/radar-envio.log 2>&1
fi

if [ "$antes" != "$depois" ]; then
  mudou=$($G diff --name-only "$antes" "$depois" -- vivo lab radar requirements.txt | grep -v '^vivo/dados/' | grep -v '^vivo/gemeo/' | grep -v '^lab/dados/' || true)
  if [ -n "$mudou" ]; then
    echo "$mudou" | grep -q '^requirements.txt$' && $R "$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"
    $SC restart radar-vivo.service
    echo "código novo: motor reiniciado"
  fi
fi
exit 0
