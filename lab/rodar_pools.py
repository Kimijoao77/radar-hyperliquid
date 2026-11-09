"""Roda o laboratório de pools e looping (a cada 12 horas): ranking e carteira simulada (protegida desde a versão 2)."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from lab.pools import (EMPRESTIMO, POOLS, PRECOS, PADRAO, VERSAO_CARTEIRA, chave_preco, com_perda, estaveis, loops,  # noqa: E402
                       sem_repetir, valor_protegido, volateis, volateis_protegiveis)
from radar.api import Hyperliquid  # noqa: E402

HORA = 3600 * 1000
ANO = 365 * 24 * HORA
S = requests.Session()
S.headers["User-Agent"] = "laboratorio-investimentos/1.0"


def _get(url):
    r = S.get(url, timeout=120)
    r.raise_for_status()
    return r.json()


def precos_atuais(chaves: list[str], get=_get) -> dict:
    out = {}
    for i in range(0, len(chaves), 25):
        out.update((get("https://coins.llama.fi/prices/current/" + ",".join(chaves[i:i + 25])) or {}).get("coins", {}))
    return {k: v.get("price") for k, v in out.items()}


def funding_desde(api, moeda: str, t0: int, t1: int) -> float:
    """Soma das taxas de funding (por hora) de uma moeda entre t0 e t1: a venda no perpétuo recebe quando é positiva."""
    try:
        h = api._post({"type": "fundingHistory", "coin": moeda, "startTime": t0 + 1, "endTime": t1}, 20) or []
    except Exception as ex:  # noqa: BLE001
        print("pools: funding falhou", moeda, str(ex)[:80])
        return 0.0
    return sum(float(x.get("fundingRate") or 0) for x in h)


def main(raiz: Path = RAIZ, get=_get, api=None) -> int:
    agora = int(time.time() * 1000)
    saida = raiz / "saida" / "pools.json"
    arq = raiz / "lab" / "dados" / "pools_estado.json"
    est = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    nova_versao = est.get("versao") != VERSAO_CARTEIRA
    if not nova_versao and saida.exists() and agora - est.get("ultima", 0) < 12 * HORA - 10 * 60 * 1000:
        print("pools: rodou há menos de 12 h")
        return 0
    f = PADRAO
    pools = get(POOLS).get("data", [])
    emp = {e["pool"]: e for e in get(EMPRESTIMO)}
    est_l, vol_l = estaveis(pools, f), volateis(pools, f)
    chaves = sorted({chave_preco(v["rede"], t) for v in vol_l for t in v["tokens"]})
    precos = {}
    for i in range(0, len(chaves), 20):
        precos.update(get(PRECOS.format(moedas=",".join(chaves[i:i + 20]))).get("coins", {}))
    vol_l = [com_perda(v, precos) for v in vol_l]
    lp = loops(pools, emp)
    api = api or Hyperliquid(1000)
    perps = {u["name"] for u in (api._post({"type": "meta"}, 20) or {}).get("universe", [])}
    prot = volateis_protegiveis(pools, f, perps)

    # versão nova da carteira: guarda o resultado da anterior e recomeça
    if nova_versao:
        anterior = list(est.get("anterior") or [])
        velho = json.loads(saida.read_text(encoding="utf-8")) if saida.exists() else {}
        c = velho.get("carteira") or {}
        if c.get("capital"):
            anterior.append({"nome": "3 estáveis + 3 pares sem proteção + looping sem contar o ETH", "retorno": round(c["saldo"] / c["capital"] - 1, 4),
                             "de": c.get("inicio"), "ate": velho.get("gerado")})
        est = {"versao": VERSAO_CARTEIRA, "anterior": anterior}
    # carteira simulada: 3 estáveis + 3 pares protegidos + o melhor looping (protegido), partes iguais
    if not est.get("itens"):
        itens = [{"tipo": "estavel", "id": v["id"], "nome": f"{v['par']} ({v['projeto']}, {v['rede']})"} for v in sem_repetir(est_l, 3)]
        itens += [{"tipo": "volatil", "id": v["id"], "nome": f"{v['par']} ({v['projeto']}, {v['rede']})", "moeda_perp": v["moeda_perp"],
                   "chaves": [chave_preco(v["rede"], t) for t in v["tokens"]]} for v in prot[:3]]
        if lp:
            n = max(lp[0]["niveis"], key=lambda n: n["vezes"])
            itens.append({"tipo": "loop", "id": f"{lp[0]['protocolo']}|{lp[0]['rede']}|{lp[0]['token']}", "vezes": n["vezes"], "moeda_perp": "ETH",
                          "chaves": ["coingecko:ethereum"], "nome": f"{lp[0]['token']} {n['vezes']}× ({lp[0]['protocolo']}, {lp[0]['rede']})"})
        est.update({"inicio": agora, "itens": itens, "fotos": []})
    # foto de agora: rendimento de cada item, preço da moeda protegida e o funding desde a foto anterior
    por_id = {p["pool"]: p for p in pools}
    foto = {"t": agora, "v": {}, "f": {}}
    chaves_c = sorted({k for it in est["itens"] for k in it.get("chaves", [])})
    pa = precos_atuais(chaves_c, get) if chaves_c else {}
    if est["fotos"]:
        for m in sorted({it["moeda_perp"] for it in est["itens"] if it.get("moeda_perp")}):
            foto["f"][m] = funding_desde(api, m, est["fotos"][-1]["t"], agora)
    for it in est["itens"]:
        if it["tipo"] in ("estavel", "volatil"):
            p = por_id.get(it["id"])
            apy = ((p or {}).get("apyBase") or 0) / 100
            if it["tipo"] == "estavel":
                foto["v"][it["id"]] = [apy]
            else:
                ps = [pa.get(k) for k in it["chaves"]]
                vol = [x for x in ps if x and abs(x - 1) > 0.05]        # o lado que não é estável
                foto["v"][it["id"]] = [apy, vol[0] if len(vol) == 1 else None]
        else:
            prot_, rede, tok = it["id"].split("|")
            l = next((x for x in lp if x["protocolo"] == prot_ and x["rede"] == rede and x["token"] == tok), None)
            n = next((n for n in (l or {}).get("niveis", []) if n["vezes"] == it["vezes"]), None)
            foto["v"][it["id"]] = [n["ao_ano"] if n else None, pa.get("coingecko:ethereum")]
    est["fotos"].append(foto)
    est["fotos"] = est["fotos"][-800:]
    # valor de cada item desde o começo
    parte = 1000 / max(1, len(est["itens"]))
    carteira = []
    for it in est["itens"]:
        if it["tipo"] == "estavel":
            v, ult = 1.0, None
            for ft in est["fotos"]:
                x = ft["v"].get(it["id"])
                if not x:
                    continue
                if ult is not None and ult[1][0] is not None:
                    v *= 1 + ult[1][0] * (ft["t"] - ult[0]) / ANO
                ult = (ft["t"], x)
            carteira.append({"tipo": "estavel", "nome": it["nome"], "taxas": round(parte * (v - 1), 2), "valor": round(parte * v, 2)})
        else:
            carteira.append({"tipo": it["tipo"], "nome": it["nome"], "moeda": it["moeda_perp"], **valor_protegido(est["fotos"], it, parte, ANO)})
    total = sum(c["valor"] for c in carteira)
    # guarda um ponto por rodada (resultado da carteira) para o app desenhar a linha; acumula o teste inteiro
    est.setdefault("curva", []).append([agora, round(total, 2)])
    est["curva"] = est["curva"][-1500:]
    rel = {"gerado": agora, "gerado_txt": datetime.fromtimestamp(agora / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "total_pools": len(pools), "parametros": f, "versao": VERSAO_CARTEIRA, "estaveis": est_l, "volateis": vol_l, "protegiveis": prot[:8],
           "loops": lp[:8], "anterior": est.get("anterior", []),
           "carteira": {"inicio": est["inicio"], "capital": 1000, "saldo": round(total, 2), "lucro": round(total - 1000, 2), "itens": carteira, "curva": est["curva"]}}
    est["ultima"] = agora
    saida.parent.mkdir(exist_ok=True)
    saida.write_text(json.dumps(rel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(est, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"pools: {len(pools)} pools; {len(est_l)} estáveis, {len(prot)} pares protegíveis, {len(lp)} loopings; carteira {total - 1000:+.2f} US$")
    return 0


if __name__ == "__main__":
    sys.exit(main())
