"""Roda todos os laboratórios; se um falhar, os outros continuam."""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lab import rodar_funding, rodar_grade  # noqa: E402

falhas = 0
for nome, mod in (("funding", rodar_funding), ("grade", rodar_grade)):
    try:
        mod.main()
    except Exception:  # noqa: BLE001
        falhas += 1
        print(f"--- {nome} falhou ---")
        traceback.print_exc()
sys.exit(0 if falhas < 2 else 1)
