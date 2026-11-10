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

from lab.cofres import (DIA, HLP, LISTA, PADRAO, RISCO, VERSAO, candidatos, constante, contra_btc, de_risco, depositar, independente, indice,  # noqa: E402
                        medir, nota_risco, reduzir)
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
    if est.get("risco") and est["risco"].get("versao") != RISCO["versao"]:
        est.pop("risco")                                 # regra nova da carteira de risco: escolhe de novo já nesta rodada
    if est.get("versao") == VERSAO and (not est.get("escolhidos") or "risco" not in est):
        pass
    elif saida.exists() and agora - est.get("ultima", 0) < 6 * HORA - 10 * 60 * 1000:
        print("cofres: rodou há menos de 6 h")
        return 0
    p = PADRAO
    api = api or Hyperliquid(1000)
    lista = (baixar_lista or (lambda: requests.get(LISTA, timeout=120).json()))()
    cands = candidatos(lista, agora, p)
    enderecos = {((v.get("summary") or {}).get("vaultAddress") or "").lower() for v in lista} - {""}
    alvo = cands[: p["detalhar"]]
    if not any(c["cofre"] == HLP for c in alvo):
        alvo.append(next((c for c in cands if c["cofre"] == HLP), {"cofre": HLP, "nome": "HLP", "tvl": 0, "idade_dias": 0, "apr": 0}))
    vistos = {c["cofre"] for c in alvo}
    alvo += sorted([c for c in cands if c["cofre"] not in vistos], key=lambda c: -c["apr"])[: RISCO["extras_por_apr"]]
    for e in est.get("escolhidos", []) + (est.get("risco") or {}).get("escolhidos", []):
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
        lider = (c.get("lider") or d.get("leader") or "").lower()
        filho = (d.get("relationship") or {}).get("type") == "child" or lider in enderecos   # o dono é outro cofre (ex.: os do HLP)
        medidos.append({**c, "nome": d.get("name") or c["nome"], "comissao": d.get("leaderCommission"), "seguidores": len(d.get("followers") or []),
                        "aceita_deposito": d.get("allowDeposits"), "medidas": m, "mes": m30.get("total"), **cb,
                        "constante": constante(m), "independente": independente(cb, p), "hlp": c["cofre"] == HLP, "filho": filho,
                        "_ind": ind_t, "_ind_m": ind_m})
    medidos.sort(key=lambda x: (not x["constante"], -((x["medidas"] or {}).get("ao_ano") or -9) / max(0.05, (x["medidas"] or {}).get("pior_queda") or 1)))
    # a carteira em curso (desde 03/11) continua: os cofres dela também passam no filtro novo (não seguem o BTC), e a
    # perda de 03 a 09/11 foi dos próprios gestores. O filtro e os pesos valem quando uma carteira nova for montada.
    if not est.get("escolhidos"):
        boas = [x["cofre"] for x in medidos if x["constante"] and x["independente"] and not x["hlp"]][: p["carteira"]]
        pesos = {b: (1 - p["peso_hlp"]) / len(boas) for b in boas} if boas else {}
        pesos[HLP] = p["peso_hlp"] if boas else 1.0
        est.update({"inicio": agora, "escolhidos": boas + [HLP], "pesos": pesos,
                    "base": {x["cofre"]: x["_ind"][-1][1] for x in medidos if x["cofre"] in boas + [HLP] and x["_ind"]}})
    # carteira de risco: escolhida uma vez (quando alguma passa na regra) e depois fica fixa, como a do HLP
    if not (est.get("risco") or {}).get("escolhidos"):
        boas = sorted([x for x in medidos if de_risco(x)], key=lambda x: -nota_risco(x))[: RISCO["carteira"]]
        est["risco"] = {"versao": RISCO["versao"], "inicio": agora, "tentou": agora, "escolhidos": [x["cofre"] for x in boas],
                        "pesos": {x["cofre"]: 1 / len(boas) for x in boas},
                        "base": {x["cofre"]: x["_ind"][-1][1] for x in boas if x["_ind"]}}
    # depósito simulado: o do HLP (versão 3) e o da carteira de risco, com a comissão de cada cofre
    carteira, total = depositar(est, medidos, p, agora)
    risco = None
    if est["risco"]["escolhidos"]:
        itens_r, total_r = depositar(est["risco"], medidos, p, agora)
        risco = {"inicio": est["risco"]["inicio"], "capital": p["capital"], "saldo": round(total_r, 2), "lucro": round(total_r - p["capital"], 2),
                 "itens": itens_r, "curva": est["risco"]["curva"]}
    for x in medidos:
        x["curva"] = reduzir(x.pop("_ind"))
        x.pop("_ind_m")
    rel = {"gerado": agora, "gerado_txt": datetime.fromtimestamp(agora / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "parametros": p, "total_cofres": len(lista), "candidatos": len(cands),
           "cofres": medidos[:25] + [x for x in medidos[25:] if x["cofre"] in (est["risco"].get("escolhidos") or [])],
           "parametros_risco": RISCO, "risco": risco,
           "hlp": next((x for x in medidos if x["hlp"]), None),
           "versao": VERSAO,
           "carteira": {"inicio": est["inicio"], "capital": p["capital"], "saldo": round(total, 2), "lucro": round(total - p["capital"], 2), "itens": carteira, "curva": est["curva"]}}
    est["ultima"] = agora
    est["versao"] = VERSAO                               # (sem isto, num estado novo a 2ª rodada achava que a versão mudou e recomeçava)
    saida.parent.mkdir(exist_ok=True)
    saida.write_text(json.dumps(rel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"cofres: {len(lista)} na lista, {len(cands)} candidatos, {sum(1 for x in medidos if x['constante'])} constantes, "
          f"{sum(1 for x in medidos if x['constante'] and x['independente'])} sem seguir o BTC; carteira {total - p['capital']:+.2f} US$")
    return 0


if __name__ == "__main__":
    sys.exit(main())
