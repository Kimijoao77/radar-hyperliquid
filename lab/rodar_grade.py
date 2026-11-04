"""Roda o laboratório de grade e DCA: teste no passado (~200 dias de velas de 1 h) e ao vivo das escolhidas."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from lab.grade import CONFIGS, HORA, nome, nota, rodar  # noqa: E402
from radar.api import Hyperliquid  # noqa: E402

MOEDAS = ["BTC", "ETH", "SOL", "HYPE"]


def main(raiz: Path = RAIZ, api=None) -> int:
    api = api or Hyperliquid(1000)
    agora = int(time.time() * 1000)
    arq = raiz / "lab" / "dados" / "grade_estado.json"
    est = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    velas = {}
    for m in MOEDAS:
        vs = api.velas(m, "1h", agora - 5000 * HORA, agora)
        velas[m] = [v for v in vs if int(v["T"] if "T" in v else v["t"]) <= agora]   # só velas fechadas
        if velas[m] and int(velas[m][-1].get("T", velas[m][-1]["t"] + HORA)) > agora:
            velas[m] = velas[m][:-1]
    passado = []
    for m in MOEDAS:
        if len(velas[m]) < 24 * 14:
            continue
        for c in CONFIGS:
            r = rodar(c, velas[m])
            passado.append({"moeda": m, "config": c, "nome": nome(c), **r, "nota": round(nota(r), 3)})
    passado.sort(key=lambda r: -r["nota"])
    if not est.get("escolhidas") and passado:
        def duas(tipo):   # as 2 melhores, em moedas diferentes
            out = []
            for r in passado:
                if r["config"]["tipo"] == tipo and not r["liquidada"] and r["moeda"] not in {x["moeda"] for x in out}:
                    out.append(r)
            return out[:2]
        g, d = duas("grade"), duas("dca")
        est = {"inicio": agora // HORA * HORA, "escolhidas": [{"moeda": r["moeda"], "config": r["config"]} for r in g + d]}
    ao_vivo = []
    for e in est.get("escolhidas", []):
        vs = [v for v in velas.get(e["moeda"], []) if int(v["t"]) >= est["inicio"]]
        ops: list = []
        r = rodar(e["config"], vs, ops) if len(vs) >= 2 else None
        if r is not None:
            r["ops"] = ops[-150:]
        ao_vivo.append({"moeda": e["moeda"], "config": e["config"], "nome": nome(e["config"]), "resultado": r})
    for r in passado:   # o app só precisa da curva das melhores
        if r is not passado[0] and r not in passado[:6]:
            r.pop("curva", None)
    segurar = {}
    if est.get("inicio"):
        for m in ("BTC", "ETH"):
            vs = [v for v in velas.get(m, []) if int(v["t"]) >= est["inicio"]]
            if vs:
                p0 = float(vs[0]["o"])
                segurar[m] = [[est["inicio"], 0.0]] + [[int(v["t"]) + HORA, round(float(v["c"]) / p0 - 1, 5)] for v in vs]
    rel = {"gerado": agora, "gerado_txt": datetime.fromtimestamp(agora / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "inicio_ao_vivo": est.get("inicio"), "moedas": MOEDAS, "capital": 1000, "passado": passado, "ao_vivo": ao_vivo, "segurar": segurar}
    (raiz / "saida").mkdir(exist_ok=True)
    (raiz / "saida" / "grade.json").write_text(json.dumps(rel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding="utf-8")
    m = passado[0] if passado else None
    print(f"grade/DCA: {len(passado)} testes; melhor: {m['moeda']} {m['nome']} {m['retorno']:+.1%}" if m else "grade/DCA: sem velas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
