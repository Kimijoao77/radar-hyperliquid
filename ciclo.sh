#!/usr/bin/env bash
# Roda o radar (carteiras do copytrading) e o laboratório de hora em hora, guarda tudo no repositório e, perto do
# limite de 6 h do GitHub, chama o fluxo de novo para continuar sem parar. Cofres (6 h) e pools (12 h) têm o próprio
# intervalo dentro de lab/rodar.py: nas outras horas eles só pulam.
set -u
git config user.name "radar-bot"
git config user.email "radar-bot@users.noreply.github.com"
fim=$(( $(date +%s) + 5 * 3600 + 30 * 60 ))
while :; do
  inicio=$(date +%s)
  git pull -q --rebase || true
  echo "::group::Radar $(date -u +%H:%M)"; { python coletar.py 25 && python analisar.py; } || echo "::warning::o radar falhou nesta hora"; echo "::endgroup::"
  echo "::group::Laboratório"; python lab/rodar.py || echo "::warning::o laboratório falhou nesta hora"; echo "::endgroup::"
  git add dados saida lab/dados
  if ! git diff --cached --quiet; then
    git commit -q -m "Robôs: $(date -u +'%Y-%m-%d %H:%M') UTC"
    for i in 1 2 3 4 5; do git push -q && break; sleep 5; git pull -q --rebase; done
  fi
  prox=$(( inicio + 3600 ))
  [ "$prox" -ge "$fim" ] && break
  espera=$(( prox - $(date +%s) ))
  [ "$espera" -gt 0 ] && sleep "$espera"
done
gh workflow run robos.yml --ref main && echo "chamei a próxima rodada"
