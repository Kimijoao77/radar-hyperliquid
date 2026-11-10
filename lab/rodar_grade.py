"""Roda o laboratório de grade e DCA: teste no passado (~200 dias de velas de 1 h) e ao vivo das escolhidas."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from lab.grade import CONFIGS, HORA, MEDIA_H, nome, nota_honesta, nota_lucro, rodar  # noqa: E402
from radar.api import Hyperliquid  # noqa: E402

MOEDAS = ["BTC", "ETH", "SOL", "HYPE"]
VERSAO = 3          # 3 (10/11/2026): o máximo de lucro (pedido do João), com 2× e 3×; escolhe os 4 de maior lucro ao ano no pior dos dois pedaços do passado
                    # 2 (09/11/2026): só 1×, DCA com pausa na queda, escolha pela pior nota dentro/fora da amostra
REF_INICIO = 1793674800000   # 03/11/2026 00:00 em Brasília: o começo dos testes


def _fechamentos(vs: list[dict]) -> list[float]:
    return [float(v["c"]) for v in vs]


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
        corte = len(velas[m]) * 2 // 3                     # 2/3 para escolher, 1/3 que a escolha não vê
        dentro_v, fora_v = velas[m][:corte], velas[m][corte:]
        for c in CONFIGS:
            r = rodar(c, velas[m])
            dentro = rodar(c, dentro_v)
            fora = rodar(c, fora_v, historico=_fechamentos(dentro_v)[-MEDIA_H:])
            passado.append({"moeda": m, "config": c, "nome": nome(c), **r, "nota": round(nota_lucro(dentro, fora), 3),
                            "nota_risco": round(nota_honesta(dentro, fora), 3),
                            "dentro": {"retorno": dentro["retorno"], "pior_queda": dentro["pior_queda"], "dias": dentro["dias"]},
                            "fora": {"retorno": fora["retorno"], "pior_queda": fora["pior_queda"], "dias": fora["dias"],
                                     "segurar_moeda": fora["segurar_moeda"]}})
    passado.sort(key=lambda r: -r["nota"])
    if est.get("versao") != VERSAO:                     # regras novas: guarda o resultado da versão anterior e recomeça
        anterior = []
        try:
            velho = json.loads((raiz / "saida" / "grade.json").read_text(encoding="utf-8"))
            for a in velho.get("ao_vivo", []):
                r = a.get("resultado") or {}
                anterior.append({"moeda": a["moeda"], "nome": a["nome"], "retorno": r.get("retorno"), "pior_queda": r.get("pior_queda"),
                                 "segurar_moeda": r.get("segurar_moeda"), "de": velho.get("inicio_ao_vivo"), "ate": velho.get("gerado")})
        except (OSError, ValueError):
            pass
        est = {"versao": VERSAO, "anterior": anterior}
    if not est.get("escolhidas") and passado:
        # versão 3: os 4 de maior lucro ao ano (no pior dos dois pedaços do passado), sem liquidação; até 3 na mesma moeda
        out, por_moeda = [], {}
        for r in passado:
            if r["liquidada"] or r["nota"] <= 0 or por_moeda.get(r["moeda"], 0) >= 3:
                continue
            out.append(r)
            por_moeda[r["moeda"]] = por_moeda.get(r["moeda"], 0) + 1
            if len(out) == 4:
                break
        est.update(inicio=agora // HORA * HORA, escolhidas=[{"moeda": r["moeda"], "config": r["config"]} for r in out])
    ao_vivo = []
    for e in est.get("escolhidas", []):
        todas = velas.get(e["moeda"], [])
        vs = [v for v in todas if int(v["t"]) >= est["inicio"]]
        antes = _fechamentos([v for v in todas if int(v["t"]) < est["inicio"]])[-MEDIA_H:]
        ops: list = []
        r = rodar(e["config"], vs, ops, historico=antes) if len(vs) >= 2 else None
        if r is not None:
            r["ops"] = ops[-150:]
        ao_vivo.append({"moeda": e["moeda"], "config": e["config"], "nome": nome(e["config"]), "resultado": r})
    for r in passado:   # o app só precisa da curva das melhores
        if r is not passado[0] and r not in passado[:6]:
            r.pop("curva", None)
    # "só segurar a moeda" desde o começo dos testes (03/11): o app compara cada teste com ela, desde o começo dele
    segurar, desde = {}, min(est.get("inicio") or REF_INICIO, REF_INICIO)
    for m in ("BTC", "ETH"):
        vs = [v for v in velas.get(m, []) if int(v["t"]) >= desde]
        if vs:
            p0 = float(vs[0]["o"])
            segurar[m] = [[desde, 0.0]] + [[int(v["t"]) + HORA, round(float(v["c"]) / p0 - 1, 5)] for v in vs]
    rel = {"gerado": agora, "gerado_txt": datetime.fromtimestamp(agora / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "versao": VERSAO, "inicio_ao_vivo": est.get("inicio"), "moedas": MOEDAS, "capital": 1000, "passado": passado,
           "ao_vivo": ao_vivo, "segurar": segurar, "anterior": est.get("anterior", [])}
    (raiz / "saida").mkdir(exist_ok=True)
    (raiz / "saida" / "grade.json").write_text(json.dumps(rel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding="utf-8")
    m = passado[0] if passado else None
    print(f"grade/DCA: {len(passado)} testes; melhor: {m['moeda']} {m['nome']} {m['retorno']:+.1%}" if m else "grade/DCA: sem velas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
