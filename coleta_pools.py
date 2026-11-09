"""Ensaio: coleta para o estudo das pools concentradas (Meteora DLMM): lista de pools e velas de 1 h dos últimos ~8 dias."""
import json, sys, time
sys.path.insert(0, ".")
from lab.rodar_memecoins import Gecko
from lab.rodar_concentradas import _meteora

saida = sys.argv[1]
pools, vistos = [], set()
for ordem, filtro in [("volume_24h:desc", "is_blacklisted=false && tvl>=10000 && volume_24h>=50000"),
                      ("fee_tvl_ratio_24h:desc", "is_blacklisted=false && tvl>=10000 && volume_24h>=50000"),
                      ("tvl:desc", "is_blacklisted=false && tvl>=100000")]:
    for pag in (1, 2):
        try:
            d = _meteora("/pools", page=pag, page_size=100, sort_by=ordem, filter_by=filtro) or {}
        except Exception as ex:
            print("meteora falhou", ordem, pag, ex); continue
        for p in d.get("data") or []:
            if p["address"] in vistos:
                continue
            y = (p.get("token_y") or {}).get("symbol", "").upper()
            if y not in ("SOL", "USDC"):
                continue
            vistos.add(p["address"]); pools.append(p)
print("pools", len(pools))
if pools:
    print("campos", sorted(pools[0].keys()))
g = Gecko(intervalo=3.2, limite_espera=3000)
def velas(addr, token):
    j = g.get(f"/networks/solana/pools/{addr}/ohlcv/hour", aggregate=1, limit=200, currency="usd", token=token)
    return (((j or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
sol = velas("58oQChx4yWmvKdwLLZzBi4ChoCc2fqCUWBkwMihLYQo2", "So11111111111111111111111111111111111111112")
print("sol velas", len(sol))
out = {"sol": sol, "pools": []}
t0 = time.time()
for i, p in enumerate(pools[:360]):
    try:
        v = velas(p["address"], p["token_x"]["address"])
    except Exception as ex:
        print("velas falharam", p.get("name"), str(ex)[:80]); v = []
    out["pools"].append({"p": p, "velas": v})
    if i % 40 == 0:
        print(i, round(time.time() - t0), "s", p.get("name"), len(v))
    if time.time() - t0 > 35 * 60:
        break
json.dump(out, open(saida, "w"))
print("ok", len(out["pools"]), "com velas:", sum(1 for x in out["pools"] if len(x["velas"]) >= 60))
