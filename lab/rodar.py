"""Roda todos os laboratórios; se um falhar, os outros continuam."""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lab import (rodar_apostas, rodar_cofres, rodar_concentradas, rodar_copia, rodar_funding, rodar_grade, rodar_ideias,  # noqa: E402
                 rodar_listagens, rodar_memecoins, rodar_opcoes, rodar_pools)

falhas = 0
# 10/11 (pedido do João: só o que pode bater o ping pong, 45 % ao ano): saíram memecoins (−5 % em 2 dias), funding
# (a melhor moeda paga ~11 % ao ano), pools estáveis (~5 a 15 % ao ano) e opções (~20 a 30 % ao ano). O código fica.
# 10/11 (à noite): entrou "listagens" (vender moeda recém-listada na Hyperliquid)
# 11/11: entrou "ideias" (os testes que o Claude cria a partir das ideias dos vídeos; lab/ideias/COMO.md)
LABS = (("copia", rodar_copia), ("grade", rodar_grade), ("cofres", rodar_cofres), ("apostas", rodar_apostas),
        ("concentradas", rodar_concentradas), ("listagens", rodar_listagens), ("ideias", rodar_ideias))
_DESLIGADOS = (rodar_funding, rodar_pools, rodar_opcoes, rodar_memecoins)
for nome, mod in LABS:
    try:
        mod.main()
    except Exception:  # noqa: BLE001
        falhas += 1
        print(f"--- {nome} falhou ---")
        traceback.print_exc()
sys.exit(0 if falhas < len(LABS) else 1)
