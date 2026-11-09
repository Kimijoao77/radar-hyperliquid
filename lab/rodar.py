"""Roda todos os laboratórios; se um falhar, os outros continuam."""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lab import rodar_cofres, rodar_copia, rodar_funding, rodar_grade, rodar_opcoes, rodar_pools  # noqa: E402

falhas = 0
LABS = (("copia", rodar_copia), ("funding", rodar_funding), ("grade", rodar_grade), ("cofres", rodar_cofres), ("pools", rodar_pools),
        ("opcoes", rodar_opcoes))
for nome, mod in LABS:
    try:
        mod.main()
    except Exception:  # noqa: BLE001
        falhas += 1
        print(f"--- {nome} falhou ---")
        traceback.print_exc()
sys.exit(0 if falhas < len(LABS) else 1)
