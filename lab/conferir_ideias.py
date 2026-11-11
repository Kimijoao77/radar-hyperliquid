"""Confere os testes novos das ideias dos vídeos (marcados com "conferir": true em lab/ideias/indice.json): roda cada um
uma vez com os dados de verdade, sem gravar nada. Deu certo → liga ("ativo": true). Deu erro → fica desligado e o erro
vai para "erro_conferencia" (o Claude corrige na próxima leitura). Roda no GitHub (fluxo "Ideias: conferir")."""
from __future__ import annotations

import contextlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from lab import rodar_ideias  # noqa: E402

indice = json.loads(rodar_ideias.INDICE.read_text(encoding="utf-8"))
mudou = False
for item in indice:
    if not item.get("conferir"):
        continue
    saida = io.StringIO()
    with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(saida):
        try:
            cod = rodar_ideias.main(["--so", item["id"], "--seco"])
        except Exception as ex:  # noqa: BLE001
            print(f"{type(ex).__name__}: {ex}")
            cod = 1
    txt = saida.getvalue()
    print(f"== {item['id']} ==\n{txt}")
    item["conferir"] = False
    item["conferido_em"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if cod == 0:
        item["ativo"] = True
        item.pop("erro_conferencia", None)
    else:
        item["ativo"] = False
        item["erro_conferencia"] = txt.strip()[-800:]
    mudou = True
if mudou:
    rodar_ideias.INDICE.write_text(json.dumps(indice, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
