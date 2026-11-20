#!/usr/bin/env bash
# Prepara a máquina 24 h (VPS com Ubuntu) para rodar o motor em tempo real, em simulação.
# Roda uma vez, como root, na criação da máquina (o texto colado no painel da Vultr chama este arquivo):
#
#   TOKEN="..." bash instalar.sh
#
# TOKEN = token do GitHub com escrita só neste repositório: a máquina publica aqui o sinal de vida e os resultados.
# Ele fica guardado só na máquina (em /opt/radar/.git/config, legível só pelo usuário radar). Nada de chave de
# corretora nem de carteira: nesta fase não existe nenhuma.
set -uo pipefail
REPO="Kimijoao77/radar-hyperliquid"
DIR=/opt/radar
LOG=/var/log/radar-instalar.log
exec > >(tee -a "$LOG") 2>&1
echo "== instalação do motor: $(date -u +'%Y-%m-%d %H:%M UTC')"
export DEBIAN_FRONTEND=noninteractive
export HOME="${HOME:-/root}"            # na criação da máquina o HOME pode vir vazio, e o git precisa dele

falhou() {   # deixa o motivo no repositório (dá para ver de fora o que aconteceu) e sai
  echo "!! a instalação parou: $1"
  if [ -d "$DIR/.git" ]; then
    tail -n 60 "$LOG" > "$DIR/vivo/instalacao.log" 2>/dev/null
    git -C "$DIR" add vivo/instalacao.log && git -C "$DIR" -c user.name=radar-maquina -c user.email=radar-maquina@users.noreply.github.com commit -q -m "Máquina: a instalação parou" && git -C "$DIR" push -q
  fi
  exit 1
}

[ -n "${TOKEN:-}" ] && [ "$TOKEN" != "COLE_O_TOKEN_AQUI" ] || { echo "!! faltou o TOKEN"; exit 1; }

# o Ubuntu recém-criado costuma estar ocupando o apt nos primeiros minutos: espera a vez
apt_() { apt-get -o DPkg::Lock::Timeout=600 "$@"; }
for _ in 1 2 3 4 5; do apt_ update -y && break; sleep 20; done
apt_ install -y git python3-venv python3-pip ca-certificates || { sleep 30; apt_ install -y git python3-venv python3-pip ca-certificates; } || { echo "!! o apt não instalou os pacotes"; exit 1; }

if [ ! -d "$DIR/.git" ]; then
  git clone -q "https://x-access-token:${TOKEN}@github.com/${REPO}.git" "$DIR" || { echo "!! não consegui baixar o repositório (token?)"; exit 1; }
fi
git config --global --add safe.directory "$DIR"
git -C "$DIR" remote set-url origin "https://x-access-token:${TOKEN}@github.com/${REPO}.git"

# 1 GB de memória: um arquivo de troca de 1 GB evita que uma rodada pesada derrube o motor
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap -q /swapfile && swapon /swapfile && echo "/swapfile none swap sw 0 0" >> /etc/fstab || echo "(sem arquivo de troca; segue)"
fi

id radar >/dev/null 2>&1 || useradd -r -m -d /home/radar -s /usr/sbin/nologin radar
chown -R radar:radar "$DIR"
chmod 600 "$DIR/.git/config"
R="runuser -u radar --"
$R git -C "$DIR" config user.name "radar-maquina"
$R git -C "$DIR" config user.email "radar-maquina@users.noreply.github.com"
$R git -C "$DIR" config pull.rebase true
$R python3 -m venv "$DIR/.venv" || falhou "o python não criou o ambiente"
$R "$DIR/.venv/bin/pip" install -q --upgrade pip
$R "$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt" || falhou "o pip não instalou as dependências"

cat > /etc/systemd/system/radar-vivo.service <<UNIT
[Unit]
Description=Radar: motor em tempo real (simulacao)
After=network-online.target
Wants=network-online.target

[Service]
User=radar
WorkingDirectory=$DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$DIR/.venv/bin/python -m vivo.motor
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

cat > /etc/systemd/system/radar-atualiza.service <<UNIT
[Unit]
Description=Radar: baixa o codigo novo e publica os resultados
After=network-online.target

[Service]
Type=oneshot
ExecStart=/bin/bash $DIR/vivo/atualizar.sh
UNIT

cat > /etc/systemd/system/radar-atualiza.timer <<UNIT
[Unit]
Description=Radar: atualiza e publica a cada 5 minutos

[Timer]
OnBootSec=2min
OnActiveSec=1min
OnUnitActiveSec=5min
AccuracySec=15s

[Install]
WantedBy=timers.target
UNIT

systemctl daemon-reload
systemctl enable -q --now radar-vivo.service || falhou "o serviço do motor não ligou"
systemctl enable -q --now radar-atualiza.timer || falhou "o agendamento não ligou"

# primeira batida publicada na hora: é o sinal de que a máquina está de pé
sleep 20
PUBLICAR=1 /bin/bash "$DIR/vivo/atualizar.sh" || true
systemctl is-active -q radar-vivo.service || falhou "o motor ligou e caiu (journalctl -u radar-vivo)"
echo "== pronto: motor ligado, atualização a cada 5 min, publicação a cada 15 min"
