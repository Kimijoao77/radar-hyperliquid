#!/usr/bin/env bash
# Diagnóstico rápido da máquina, para rodar no console da Vultr (como root):
#   curl -sL https://raw.githubusercontent.com/Kimijoao77/radar-hyperliquid/main/vivo/ver.sh | bash
# Mostra numa tela só por que a máquina não está publicando. Nunca mostra a chave do GitHub (ela é trocada por ***).
DIR=/opt/radar
esconde() { sed -E 's#x-access-token:[^@]*@#x-access-token:***@#g; s#(github_pat_|gh[pousr]_)[A-Za-z0-9_]+#\1***#g' | cut -c1-150; }
{
echo "== $(date -u +'%d/%m %H:%M UTC') | ligada: $(uptime -p) | carga: $(cut -d' ' -f1-3 /proc/loadavg)"
free -m | awk 'NR==2{print "memória: "$3" de "$2" MB em uso"} NR==3{print "swap: "$3" MB em uso"}'
echo "disco: $(df -h / | awk 'NR==2{print $5" usado"}')"
echo "motor: $(systemctl is-active radar-vivo) | agendador: $(systemctl is-active radar-atualiza.timer) | atualização: $(systemctl is-active radar-atualiza.service)"
echo "-- internet:"
getent hosts github.com >/dev/null && echo "  nome do github: ok" || echo "  nome do github: FALHOU (DNS)"
curl -s -o /dev/null -m 10 -w "  github.com responde: HTTP %{http_code}\n" https://github.com || echo "  github.com: SEM RESPOSTA"
echo "-- chave do GitHub (teste de leitura):"
timeout 30 runuser -u radar -- git -C $DIR ls-remote origin -h refs/heads/main 2>&1 | head -3 | sed 's/^/  /'
echo "-- git:"
runuser -u radar -- git -C $DIR status -sb 2>&1 | head -4 | sed 's/^/  /'
[ -d $DIR/.git/rebase-merge ] || [ -d $DIR/.git/rebase-apply ] && echo "  REBASE PRESO"
echo "  último commit local: $(runuser -u radar -- git -C $DIR log -1 --format='%h %ad %s' --date=format:'%d/%m %H:%M' 2>&1)"
echo "-- atualização (últimas linhas):"
journalctl -u radar-atualiza.service --no-pager -n 12 -o cat 2>&1 | sed 's/^/  /'
echo "-- envio que falhou:"
tail -n 6 /run/radar-envio.log 2>/dev/null | sed 's/^/  /'
} 2>&1 | esconde
