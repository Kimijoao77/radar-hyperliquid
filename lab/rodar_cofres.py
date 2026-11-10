"""Roda o laboratório de cofres (a cada 6 horas): ranking dos cofres constantes e o depósito simulado."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from lab.cofres import DIA, HLP, LISTA, PADRAO, VERSAO, candidatos, constante, contra_btc, independente, indice, medir, reduzir  # noqa: E402
from radar.api import Hyperliquid  # noqa: E402

HORA = 3600 * 1000


def main(raiz: Path = RAIZ, api=None, baixar_lista=None) -> int:
    agora = int(time.time() * 1000)
    saida = raiz / "saida" / "cofres.json"
    arq = raiz / "lab" / "dados" / "cofres_estado.json"
    est = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    if est and est.get("versao") != VERSAO:             # regras novas: guarda o resultado da versão anterior e recomeça
        anterior = list(est.get("anterior") or [])
        try:
            velho = json.loads(saida.read_text(encoding="utf-8")).get("carteira") or {}
            anterior.append({"nome": "Versão " + str(est.get("versao", 2)) + ": " + ", ".join(i.get("nome", "") for i in velho.get("itens", [])),
                             "retorno": round(velho.get("saldo", 1000) / 1000 - 1, 5), "de": velho.get("inicio"), "ate": agora})
        except (OSError, ValueError):
            pass
        est = {"versao": VERSAO, "anterior": anterior}
    if est.get("versao") == VERSAO and not est.get("escolhidos"):
        pass
    elif saida.exists() and agora - est.get("ultima", 0) < 6 * HORA - 10 * 60 * 1000:
        print("cofres: rodou há menos de 6 h")
        return 0
    p = PADRAO
    api = api or Hyperliquid(1000)
    lista = (baixar_lista or (lambda: requests.get(LISTA, timeout=120).json()))()
    cands = candidatos(lista, agora, p)
    alvo = cands[: p["detalhar"]]
    if not any(c["cofre"] == HLP for c in alvo):
        alvo.append(next((c for c in cands if c["cofre"] == HLP), {"cofre": HLP, "nome": "HLP", "tvl": 0, "idade_dias": 0, "apr": 0}))
    for e in est.get("escolhidos", []):
        if not any(c["cofre"] == e for c in alvo):
            alvo.append(next((c for c in cands if c["cofre"] == e), {"cofre": e, "nome": "", "tvl": 0, "idade_dias": 0, "apr": 0}))
    try:
        velas = [[int(v["t"]), float(v["c"])] for v in api.velas("BTC", "1d", agora - 800 * DIA, agora)]
    except Exception as ex:  # noqa: BLE001
        print("cofres: sem velas do BTC", str(ex)[:80])
        velas = []
    medidos = []
    for c in alvo:
        try:
            d = api._post({"type": "vaultDetails", "vaultAddress": c["cofre"]}, 20) or {}
        except Exception as ex:  # noqa: BLE001
            print("cofres: falhou", c["cofre"][:10], str(ex)[:80])
            continue
        port = d.get("portfolio") or []
        ind_t, ind_m = indice(port, "allTime"), indice(port, "month")
        m = medir(ind_t)
        m30 = medir(ind_m) if len(ind_m) >= 5 else {}
        cb = contra_btc(ind_t, velas, p) if velas else {"beta": None, "nas_quedas": None, "trechos": 0, "trechos_queda": 0}
        medidos.append({**c, "nome": d.get("name") or c["nome"], "comissao": d.get("leaderCommission"), "seguidores": len(d.get("followers") or []),
                        "aceita_deposito": d.get("allowDeposits"), "medidas": m, "mes": m30.get("total"), **cb,
                        "constante": constante(m), "independente": independente(cb, p), "hlp": c["cofre"] == HLP, "_ind": ind_t, "_ind_m": ind_m})
    medidos.sort(key=lambda x: (not x["constante"], -((x["medidas"] or {}).get("ao_ano") or -9) / max(0.05, (x["medidas"] or {}).get("pior_queda") or 1)))
    # a carteira em curso (desde 03/11) continua: os cofres dela também passam no filtro novo (não seguem o BTC), e a
    # perda de 03 a 09/11 foi dos próprios gestores. O filtro e os pesos valem quando uma carteira nova for montada.
    if not est.get("escolhidos"):
        boas = [x["cofre"] for x in medidos if x["constante"] and x["independente"] and not x["hlp"]][: p["carteira"]]
        pesos = {b: (1 - p["peso_hlp"]) / len(boas) for b in boas} if boas else {}
        pesos[HLP] = p["peso_hlp"] if boas else 1.0
        est.update({"inicio": agora, "escolhidos": boas + [HLP], "pesos": pesos,
                    "base": {x["cofre"]: x["_ind"][-1][1] for x in medidos if x["cofre"] in boas + [HLP] and x["_ind"]}})
    # depósito simulado: HLP com 40 % e o resto dividido, 10 % do lucro para o dono
    carteira, total = [], 0.0
    for e in est["escolhidos"]:
        parte = p["capital"] * (est.get("pesos") or {}).get(e, 1 / max(1, len(est["escolhidos"])))
        x = next((m for m in medidos if m["cofre"] == e), None)
        r = None
        if x and x["_ind"]:
            b = est.get("base", {}).get(e)
            if b is None:                                    # entrou depois: começa a contar agora
                est.setdefault("base", {})[e] = b = x["_ind"][-1][1]
            r = x["_ind"][-1][1] / b - 1
        ganho = 0.0 if r is None else parte * r
        if ganho > 0:
            ganho *= 1 - p["comissao"]
        total += parte + ganho
        carteira.append({"cofre": e, "nome": x["nome"] if x else "", "hlp": e == HLP, "parte": parte, "rendeu": None if r is None else round(r, 5), "ganho": round(ganho, 2)})
    for x in medidos:
        x["curva"] = reduzir(x.pop("_ind"))
        x.pop("_ind_m")
    # guarda um ponto por rodada (resultado da carteira) para o app desenhar a linha; acumula o teste inteiro
    est.setdefault("curva", []).append([agora, round(total, 2)])
    est["curva"] = est["curva"][-1500:]
    rel = {"gerado": agora, "gerado_txt": datetime.fromtimestamp(agora / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "parametros": p, "total_cofres": len(lista), "candidatos": len(cands), "cofres": medidos[:25],
           "hlp": next((x for x in medidos if x["hlp"]), None),
           "versao": VERSAO,
           "carteira": {"inicio": est["inicio"], "capital": p["capital"], "saldo": round(total, 2), "lucro": round(total - p["capital"], 2), "itens": carteira, "curva": est["curva"]}}
    est["ultima"] = agora
    saida.parent.mkdir(exist_ok=True)
    saida.write_text(json.dumps(rel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"cofres: {len(lista)} na lista, {len(cands)} candidatos, {sum(1 for x in medidos if x['constante'])} constantes, "
          f"{sum(1 for x in medidos if x['constante'] and x['independente'])} sem seguir o BTC; carteira {total - p['capital']:+.2f} US$")
    return 0


if __name__ == "__main__":
    sys.exit(main())
