"""Roda o laboratório de opções (de hora em hora): vende puts semanais de BTC e ETH, sem dinheiro."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from lab.opcoes import API, CAPITAL, ESTRATEGIAS, VERSAO, novo, passo  # noqa: E402

S = requests.Session()
S.headers["User-Agent"] = "laboratorio-investimentos/1.0"


def _get(metodo: str, **params):
    r = S.get(API + metodo, params=params, timeout=60)
    r.raise_for_status()
    return r.json()["result"]


def main(raiz: Path = RAIZ, get=_get, agora: int | None = None) -> int:
    agora = agora or int(time.time() * 1000)
    arq = raiz / "lab" / "dados" / "opcoes_estado.json"
    est = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    # versão nova: o que saiu das estratégias vai para "anterior" (com o resultado do dia em que parou)
    ids = {s["id"] for s in ESTRATEGIAS}
    anterior = est.pop("_anterior", [])
    for k in [k for k in est if k not in ids]:
        e = est.pop(k)
        if isinstance(e, dict) and "patrimonio" in e:
            anterior.append({"moeda": e.get("moeda"), "nome": f"{'Call coberta' if e.get('tipo') == 'call' else 'Put'} {e.get('moeda')}",
                             "retorno": round(e["patrimonio"] / CAPITAL - 1, 4), "segurar_moeda": round((e.get("segurar") or CAPITAL) / CAPITAL - 1, 4),
                             "de": e.get("inicio"), "ate": agora})
    est["_anterior"] = anterior
    dados = {}
    for m in ("BTC", "ETH"):
        livro = get("get_book_summary_by_currency", currency=m, kind="option")
        indice = float(get("get_index_price", index_name=f"{m.lower()}_usd")["index_price"])
        entregas = {d["date"]: float(d["delivery_price"]) for d in get("get_delivery_prices", index_name=f"{m.lower()}_usd", count=20)["data"]}
        dados[m] = (livro, indice, entregas)
    for s in ESTRATEGIAS:
        livro, indice, entregas = dados[s["moeda"]]
        e = est.get(s["id"]) or novo(s, indice, agora)
        passo(e, livro, indice, entregas, agora)
        est[s["id"]] = e
    rel = {"gerado": agora, "gerado_txt": datetime.fromtimestamp(agora / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "capital": CAPITAL, "versao": VERSAO, "indices": {m: dados[m][1] for m in dados}, "anterior": anterior,
           "estrategias": [{k: v for k, v in est[s["id"]].items()} | {"historico": est[s["id"]]["historico"][-12:]} for s in ESTRATEGIAS]}
    (raiz / "saida").mkdir(exist_ok=True)
    (raiz / "saida" / "opcoes.json").write_text(json.dumps(rel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(est, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("opções: " + "; ".join(f"{s['id']} {est[s['id']]['patrimonio'] - CAPITAL:+.2f} US$" for s in ESTRATEGIAS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
