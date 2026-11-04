"""Roda o laboratório de pools e looping (a cada 12 horas): ranking e carteira simulada."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from lab.pools import EMPRESTIMO, POOLS, PRECOS, PADRAO, chave_preco, com_perda, estaveis, loops, perda_impermanente, volateis  # noqa: E402

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


def main(raiz: Path = RAIZ, get=_get) -> int:
    agora = int(time.time() * 1000)
    saida = raiz / "saida" / "pools.json"
    arq = raiz / "lab" / "dados" / "pools_estado.json"
    est = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    if saida.exists() and agora - est.get("ultima", 0) < 12 * HORA - 10 * 60 * 1000:
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

    # carteira simulada: 3 estáveis + 3 voláteis + o melhor looping (3×), partes iguais
    if not est.get("itens"):
        itens = [{"tipo": "estavel", "id": v["id"], "nome": f"{v['par']} ({v['projeto']}, {v['rede']})"} for v in est_l[:3]]
        boas = sorted([v for v in vol_l if v.get("liquido_30d") is not None], key=lambda v: -v["liquido_30d"])[:3]
        itens += [{"tipo": "volatil", "id": v["id"], "nome": f"{v['par']} ({v['projeto']}, {v['rede']})", "chaves": [chave_preco(v["rede"], t) for t in v["tokens"]]} for v in boas]
        if lp:
            n = max(lp[0]["niveis"], key=lambda n: n["vezes"])
            itens.append({"tipo": "loop", "id": f"{lp[0]['protocolo']}|{lp[0]['rede']}|{lp[0]['token']}", "vezes": n["vezes"],
                          "nome": f"{lp[0]['token']} {n['vezes']}× ({lp[0]['protocolo']}, {lp[0]['rede']})"})
        est = {"inicio": agora, "itens": itens, "fotos": []}
    # foto de agora dos itens da carteira
    por_id = {p["pool"]: p for p in pools}
    foto = {"t": agora, "v": {}}
    chaves_c = sorted({k for it in est["itens"] for k in it.get("chaves", [])})
    pa = precos_atuais(chaves_c, get) if chaves_c else {}
    for it in est["itens"]:
        if it["tipo"] in ("estavel", "volatil"):
            p = por_id.get(it["id"])
            foto["v"][it["id"]] = [((p or {}).get("apyBase") or 0) / 100] + [pa.get(k) for k in it.get("chaves", [])]
        else:
            prot, rede, tok = it["id"].split("|")
            l = next((x for x in lp if x["protocolo"] == prot and x["rede"] == rede and x["token"] == tok), None)
            n = next((n for n in (l or {}).get("niveis", []) if n["vezes"] == it["vezes"]), None)
            foto["v"][it["id"]] = [n["ao_ano"] if n else None]
    est["fotos"].append(foto)
    est["fotos"] = est["fotos"][-800:]
    # valor de cada item desde o começo
    parte = 1000 / max(1, len(est["itens"]))
    carteira = []
    for it in est["itens"]:
        v, ult = 1.0, None
        prim = None
        for ft in est["fotos"]:
            x = ft["v"].get(it["id"])
            if not x:
                continue
            if ult is not None and ult[1][0] is not None:
                v *= 1 + ult[1][0] * (ft["t"] - ult[0]) / ANO
            ult = (ft["t"], x)
            prim = prim or x
        item = {**{k: it[k] for k in ("tipo", "nome")}, "taxas": round(parte * (v - 1), 2)}
        if it["tipo"] == "volatil" and prim and ult and all(prim[1:]) and all(ult[1][1:]):
            ra, rb = ult[1][1] / prim[1], ult[1][2] / prim[2]
            il = perda_impermanente(ra / rb)
            segurar = (ra + rb) / 2
            item.update({"perda": round(parte * segurar * il, 2), "moedas": round(parte * (segurar - 1), 2)})
            item["valor"] = round(parte * segurar * (1 + il) * v, 2)
        else:
            item["valor"] = round(parte * v, 2)
        carteira.append(item)
    total = sum(c["valor"] for c in carteira)
    # guarda um ponto por rodada (resultado da carteira) para o app desenhar a linha; acumula o teste inteiro
    est.setdefault("curva", []).append([agora, round(total, 2)])
    est["curva"] = est["curva"][-1500:]
    rel = {"gerado": agora, "gerado_txt": datetime.fromtimestamp(agora / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "total_pools": len(pools), "parametros": f, "estaveis": est_l, "volateis": vol_l, "loops": lp[:8],
           "carteira": {"inicio": est["inicio"], "capital": 1000, "saldo": round(total, 2), "lucro": round(total - 1000, 2), "itens": carteira, "curva": est["curva"]}}
    est["ultima"] = agora
    saida.parent.mkdir(exist_ok=True)
    saida.write_text(json.dumps(rel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(est, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"pools: {len(pools)} pools; {len(est_l)} estáveis, {len(vol_l)} voláteis, {len(lp)} loopings; carteira {total - 1000:+.2f} US$")
    return 0


if __name__ == "__main__":
    sys.exit(main())
