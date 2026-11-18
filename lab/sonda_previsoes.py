"""Amostras das APIs públicas do Polymarket (só leitura), para escrever o teste de previsões. Roda só sob pedido."""
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent / "amostras"
OUT.mkdir(exist_ok=True)
S = requests.Session()
S.headers["User-Agent"] = "laboratorio-investimentos/1.0"
G = "https://gamma-api.polymarket.com"


def corta(x, n=3):
    if isinstance(x, list):
        return {"_tamanho": len(x), "_amostra": [corta(i, n) for i in x[:n]]}
    if isinstance(x, dict):
        return {k: corta(v, n) for k, v in list(x.items())[:250]}
    if isinstance(x, str) and len(x) > 400:
        return x[:400] + "…"
    return x


def pega(nome, url, **params):
    try:
        r = S.get(url, params=params, timeout=60)
        try:
            corpo = r.json()
        except ValueError:
            corpo = r.text[:2000]
        res = {"status": r.status_code, "url": r.url, "corpo": corta(corpo)}
    except Exception as e:  # noqa: BLE001
        res, corpo = {"erro": str(e)[:300], "url": url}, None
    (OUT / f"pm_{nome}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(nome, res.get("status"), res.get("erro", ""))
    return corpo


agora = datetime.now(timezone.utc)
iso = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
abertos = pega("mercados_abertos", f"{G}/markets", closed="false", limit=3, order="volume24hr", ascending="false", include_tag="true")
pega("mercados_curtos", f"{G}/markets", closed="false", limit=3, end_date_min=iso(agora), end_date_max=iso(agora + timedelta(days=3)),
     liquidity_num_min=1000, order="volume24hr", ascending="false")
pega("eventos", f"{G}/events", closed="false", limit=2, order="volume24hr", ascending="false")
pega("eventos_keyset", f"{G}/events/keyset", closed="false", limit=2)
fechados = pega("mercados_fechados", f"{G}/markets", closed="true", limit=3, end_date_min=iso(agora - timedelta(days=7)),
                end_date_max=iso(agora), order="volume24hr", ascending="false")
pega("tags", f"{G}/tags", limit=80)
tok = None
try:
    tok = json.loads(abertos[0]["clobTokenIds"])[0]
except Exception:  # noqa: BLE001
    pass
tokf = None
try:
    tokf = json.loads(fechados[0]["clobTokenIds"])[0]
except Exception:  # noqa: BLE001
    pass
if tok:
    pega("historico_v2", "https://data-api.polymarket.com/v2/prices-history", token_id=tok, interval="1w", bucket_seconds=3600)
    pega("historico_clob", "https://clob.polymarket.com/prices-history", market=tok, interval="1w", fidelity=60)
    pega("preco_compra", "https://clob.polymarket.com/price", token_id=tok, side="BUY")
    pega("livro", "https://clob.polymarket.com/book", token_id=tok)
if tokf:
    t = int(time.time())
    pega("historico_v2_fechado", "https://data-api.polymarket.com/v2/prices-history", token_id=tokf, start=t - 14 * 86400, bucket_seconds=3600)
    pega("historico_clob_fechado", "https://clob.polymarket.com/prices-history", market=tokf, startTs=t - 14 * 86400, endTs=t, fidelity=60)
