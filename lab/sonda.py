"""Grava amostras pequenas das respostas das APIs públicas (para escrever os leitores certos). Roda só sob pedido."""
import json
import time
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent / "amostras"
OUT.mkdir(exist_ok=True)
S = requests.Session()
S.headers["User-Agent"] = "laboratorio-investimentos/1.0"


def corta(x, n=3):
    if isinstance(x, list):
        return {"_tamanho": len(x), "_amostra": [corta(i, n) for i in x[:n]]}
    if isinstance(x, dict):
        return {k: corta(v, n) for k, v in list(x.items())[:60]}
    return x


def pega(nome, metodo, url, **kw):
    try:
        r = S.request(metodo, url, timeout=60, **kw)
        try:
            corpo = r.json()
        except ValueError:
            corpo = r.text[:2000]
        res = {"status": r.status_code, "url": url, "corpo": corta(corpo)}
    except Exception as e:  # noqa: BLE001
        res = {"erro": str(e)[:300], "url": url}
    (OUT / f"{nome}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(nome, res.get("status"), res.get("erro", ""))
    return res


HL = "https://api.hyperliquid.xyz/info"
pega("hl_vaults_stats", "GET", "https://stats-data.hyperliquid.xyz/Mainnet/vaults")
pega("hl_vault_hlp", "POST", HL, json={"type": "vaultDetails", "vaultAddress": "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"})
pega("hl_velas", "POST", HL, json={"type": "candleSnapshot", "req": {"coin": "BTC", "interval": "1h", "startTime": int(time.time() * 1000) - 3 * 3600_000, "endTime": int(time.time() * 1000)}})
pega("hl_spot_meta", "POST", HL, json={"type": "spotMetaAndAssetCtxs"})
pega("llama_pools", "GET", "https://yields.llama.fi/pools")
pega("llama_lendborrow", "GET", "https://yields.llama.fi/lendBorrow")
pega("llama_chart", "GET", "https://yields.llama.fi/chart/747c1d2a-c668-4682-b9f9-296708a3dd90")
pega("llama_precos", "GET", "https://coins.llama.fi/prices/current/coingecko:ethereum,coingecko:bitcoin")
pega("llama_precos_hist", "GET", "https://coins.llama.fi/chart/coingecko:ethereum?span=10&period=1d")
pega("deribit_opcoes", "GET", "https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC&kind=option")
pega("deribit_instrumentos", "GET", "https://www.deribit.com/api/v2/public/get_instruments?currency=BTC&kind=option&expired=false")
pega("deribit_indice", "GET", "https://www.deribit.com/api/v2/public/get_index_price?index_name=btc_usd")
pega("deribit_ticker", "GET", "https://www.deribit.com/api/v2/public/ticker?instrument_name=BTC-PERPETUAL")
pega("deribit_expiradas", "GET", "https://www.deribit.com/api/v2/public/get_delivery_prices?index_name=btc_usd&count=5")

# 10/11/2026: amostras para o teste de moedas recém-listadas, a conta nova das pools concentradas e o novo ajuste das apostas
def meta_hl():
    try:
        r = S.post(HL, json={"type": "meta"}, timeout=60)
        u = r.json().get("universe", [])
        res = {"status": r.status_code, "tamanho": len(u), "primeiras": u[:3], "ultimas": u[-60:]}
    except Exception as e:  # noqa: BLE001
        res, u = {"erro": str(e)[:300]}, []
    (OUT / "hl_meta_ultimas.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("hl_meta_ultimas", res.get("status"), res.get("tamanho"))
    return [m["name"] for m in u[-60:] if not m.get("isDelisted")]


novas = meta_hl()
for i, moeda in enumerate(novas[-3:]):
    pega(f"hl_velas_dia_{i}", "POST", HL, json={"type": "candleSnapshot", "req": {"coin": moeda, "interval": "1d", "startTime": 0, "endTime": int(time.time() * 1000)}})
pega("hl_funding_nova", "POST", HL, json={"type": "fundingHistory", "coin": novas[-1] if novas else "BTC", "startTime": int(time.time() * 1000) - 30 * 86400_000})
pega("meteora_pools", "GET", "https://dlmm.datapi.meteora.ag/pools", params={"page": 1, "page_size": 3, "sort_by": "fee_tvl_ratio_24h:desc",
                                                                            "filter_by": "is_blacklisted=false && tvl>=10000 && volume_24h>=50000"})


def texto(nome, url, n=3000):
    try:
        r = S.get(url, timeout=60)
        corpo = r.content.decode("utf-8-sig", errors="replace")
        res = {"status": r.status_code, "url": url, "linhas": len(corpo.splitlines()), "inicio": corpo[:n]}
    except Exception as e:  # noqa: BLE001
        res = {"erro": str(e)[:300], "url": url}
    (OUT / f"{nome}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(nome, res.get("status"), res.get("linhas"))


texto("fd_fixtures", "https://www.football-data.co.uk/fixtures.csv")
texto("fd_fixtures_extras", "https://www.football-data.co.uk/new_league_fixtures.csv")
texto("fd_resultados_2526", "https://www.football-data.co.uk/mmz4281/2526/E0.csv")
texto("fd_resultados_bra", "https://www.football-data.co.uk/new/BRA.csv", 1500)
