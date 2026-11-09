"""Roda o laboratório de pools concentradas (de hora em hora): DLMM da Meteora em três faixas, com dinheiro de mentira."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from lab.concentradas import (API, BALANCO_MAX, CAPITAL, FAIXAS, NOMES, POR_FAIXA, TVL_MIN, VERSAO, VOLUME_MIN, abrir,  # noqa: E402
                              andar, balanco, escolher, fechar, num, valor_usd)
from lab.rodar_memecoins import Gecko  # noqa: E402

S = requests.Session()
S.headers["User-Agent"] = "laboratorio-investimentos/1.0"
HORA_MS = 3600 * 1000
FILTRO = f"is_blacklisted=false && tvl>={TVL_MIN} && volume_24h>={VOLUME_MIN}"
MAX_CONSULTAS = 25      # velas de 1 h por rodada para medir o balanço das candidatas


def _meteora(caminho: str, **params):
    r = S.get(API + caminho, params=params, timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def main(raiz: Path = RAIZ, meteora=_meteora, gecko=None, agora: int | None = None) -> int:
    agora = agora or int(time.time() * 1000)
    arq = raiz / "lab" / "dados" / "concentradas_estado.json"
    saida = raiz / "saida" / "concentradas.json"
    est = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    if est.get("versao") != VERSAO:
        est = {"versao": VERSAO, "inicio": agora, "faixas": {k: {"caixa": CAPITAL, "abertas": [], "fechadas": [], "curva": []} for k in FAIXAS}}
    if saida.exists() and agora - est.get("ultima", 0) < 50 * 60 * 1000:
        print("concentradas: rodou há menos de 50 min")
        return 0
    g = gecko or Gecko()
    lista = (meteora("/pools", page=1, page_size=100, sort_by="fee_tvl_ratio_24h:desc", filter_by=FILTRO) or {}).get("data") or []
    por_end = {p["address"]: p for p in lista}
    elegiveis = escolher(lista)

    # 0) o balanço do preço nas últimas 24 h (velas de 1 h), da maior taxa para baixo, até achar as calmas
    medidos = {k: v for k, v in (est.get("balanco") or {}).items() if agora - v[0] < 3 * HORA_MS}
    calmas, consultas = [], 0
    for pool in elegiveis:
        if len(calmas) >= POR_FAIXA + 2:
            break
        addr = pool["address"]
        if addr not in medidos:
            if consultas >= MAX_CONSULTAS:
                break
            consultas += 1
            try:
                j = g.get(f"/networks/solana/pools/{addr}/ohlcv/hour", aggregate=1, limit=26, currency="token", token=pool["token_x"]["address"])
                vs = sorted((((j or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or [], key=lambda v: v[0])
                b = balanco([float(v[4]) for v in vs])
            except Exception as ex:  # noqa: BLE001
                print("concentradas: velas de 1 h falharam", pool.get("name"), str(ex)[:80])
                continue
            medidos[addr] = [agora, b]
        b = medidos[addr][1]
        if b is not None and b < BALANCO_MAX:
            calmas.append(pool)
    est["balanco"] = medidos

    # 1) as abertas: taxa da última hora enquanto o preço ficou na faixa; sai se fechou fora ou passou de 24 h
    velas_de, dados_de = {}, {}
    for f in est["faixas"].values():
        for pos in f["abertas"]:
            if pos["pool"] not in dados_de:
                p = por_end.get(pos["pool"])
                if p is None:
                    try:
                        p = meteora(f"/pools/{pos['pool']}")
                    except Exception as ex:  # noqa: BLE001
                        print("concentradas: pool falhou", pos["nome"], str(ex)[:80])
                dados_de[pos["pool"]] = p or {}
            if pos["pool"] not in velas_de:
                try:
                    n = max(2, min(300, int((agora - pos["ult_t"]) / 300000) + 2))
                    j = g.get(f"/networks/solana/pools/{pos['pool']}/ohlcv/minute", aggregate=5, limit=n, currency="token", token=pos["token_x"])
                    velas_de[pos["pool"]] = (((j or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
                except Exception as ex:  # noqa: BLE001
                    print("concentradas: velas falharam", pos["nome"], str(ex)[:80])
                    velas_de[pos["pool"]] = []
    for k, f in est["faixas"].items():
        for pos in list(f["abertas"]):
            p = dados_de.get(pos["pool"]) or {}
            motivo = andar(pos, velas_de.get(pos["pool"], []), num((p.get("fee_tvl_ratio") or {}).get("1h")),
                           num((p.get("token_y") or {}).get("price")), agora)
            if motivo:
                volta = fechar(pos)
                f["caixa"] += volta
                f["abertas"].remove(pos)
                f["fechadas"].append({"nome": pos["nome"], "pool": pos["pool"], "entrou": pos["entrou"], "saiu": agora, "motivo": motivo,
                                      "r": round(volta / pos["dolares"] - 1, 4), "taxas": round(pos["taxas"] / pos["dolares"], 4),
                                      "horas_dentro": round(pos["dentro_min"] / 60, 1)})
                f["fechadas"] = f["fechadas"][-150:]

    # 2) as vagas: abre nas pools do topo que a faixa ainda não tem
    for k, f in est["faixas"].items():
        vagas = POR_FAIXA - len(f["abertas"])
        tem = {p["pool"] for p in f["abertas"]}
        for pool in [p for p in calmas if p["address"] not in tem][:vagas]:
            dol = f["caixa"] / (POR_FAIXA - len(f["abertas"]))
            if dol < 1:
                break
            f["caixa"] -= dol
            f["abertas"].append(abrir(pool, k, dol, agora))

    # 3) patrimônio de cada faixa (as abertas como se saíssem agora)
    out = {}
    for k, f in est["faixas"].items():
        pat = f["caixa"] + sum(fechar(p) for p in f["abertas"])
        f["curva"] = (f["curva"] + [[agora, round(pat, 2)]])[-1500:]
        out[k] = {"nome": NOMES[k], "faixa": FAIXAS[k], "patrimonio": round(pat, 2), "caixa": round(f["caixa"], 2), "curva": f["curva"],
                  "abertas": [{"nome": p["nome"], "pool": p["pool"], "entrou": p["entrou"], "r": round(fechar(p) / p["dolares"] - 1, 4),
                               "taxas": round(p["taxas"] / p["dolares"], 4), "dentro": p["a"] <= p["p"] <= p["b"],
                               "horas_dentro": round(p["dentro_min"] / 60, 1)} for p in f["abertas"]],
                  "fechadas": f["fechadas"][-40:]}
    est["ultima"] = agora
    rel = {"gerado": agora, "gerado_txt": datetime.fromtimestamp(agora / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "versao": VERSAO,
           "capital": CAPITAL, "inicio": est["inicio"], "faixas": out,
           "regra": "só SOL/USDC numa faixa abaixo do preço; pools com balanço < 2 %/h nas últimas 24 h; maior taxa entre elas",
           "topo": [{"nome": p.get("name"), "tvl": round(num(p.get("tvl"))), "volume_24h": round(num((p.get("volume") or {}).get("24h"))),
                     "taxa_24h": num((p.get("fee_tvl_ratio") or {}).get("24h")), "apr": num(p.get("apr")),
                     "balanco_1h": (est["balanco"].get(p["address"]) or [0, None])[1]} for p in calmas[:10]]}
    saida.parent.mkdir(exist_ok=True)
    saida.write_text(json.dumps(rel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(est, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("concentradas: " + "; ".join(f"{k} {v['patrimonio'] - CAPITAL:+.2f} US$ ({len(v['abertas'])} abertas)" for k, v in out.items())
          + f"; {len(elegiveis)} pools elegíveis, {len(calmas)} calmas ({consultas} consultas de velas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
