import json
from datetime import datetime, timezone

import pytest

from lab.opcoes import CAPITAL, escolher, ler_nome, novo, passo

DIA = 86400000


def ms(a, m, d, h=0):
    return int(datetime(a, m, d, h, tzinfo=timezone.utc).timestamp() * 1000)


def test_ler_nome():
    x = ler_nome("BTC-13NOV26-83000-P")
    assert x["k"] == 83000 and x["tipo"] == "put" and x["venc"] == ms(2026, 11, 13, 8)
    assert ler_nome("BTC-PERPETUAL") is None


def livro(indice):
    return [{"instrument_name": "BTC-13NOV26-70000-P", "bid_price": 0.002, "mark_price": 0.0021},
            {"instrument_name": "BTC-13NOV26-60000-P", "bid_price": 0.0005, "mark_price": 0.0006},
            {"instrument_name": "BTC-13NOV26-86000-C", "bid_price": 0.003, "mark_price": 0.0031},
            {"instrument_name": "BTC-4NOV26-70000-P", "bid_price": 0.001, "mark_price": 0.001}]


def test_put_ganha_premio_e_paga_na_queda():
    agora = ms(2026, 11, 6, 10)
    assert escolher(livro(78000), "put", 78000, agora)["k"] == 70000
    e = novo({"id": "put-BTC", "tipo": "put", "moeda": "BTC"}, 78000, agora)
    passo(e, livro(78000), 78000, {}, agora)
    premio = e["aberta"]["premio"]
    assert premio > 0 and e["caixa"] == pytest.approx(CAPITAL + premio)
    # vence com o BTC a 63.000: paga (70.000 − 63.000) × qtd
    qtd = e["aberta"]["qtd"]
    passo(e, [], 63000, {"2026-11-13": 63000}, ms(2026, 11, 13, 9))
    assert e["aberta"] is None and e["historico"][0]["pagou"] == pytest.approx(7000 * qtd)
    assert e["patrimonio"] < CAPITAL


def test_call_coberta_fica_com_premio_quando_nao_passa():
    agora = ms(2026, 11, 6, 10)
    e = novo({"id": "call-BTC", "tipo": "call", "moeda": "BTC"}, 78000, agora)
    passo(e, livro(78000), 78000, {}, agora)
    assert e["aberta"]["k"] == 86000
    passo(e, [], 80000, {"2026-11-13": 80000}, ms(2026, 11, 13, 9))
    assert e["historico"][0]["pagou"] == 0 and e["patrimonio"] > CAPITAL * 80000 / 78000


def test_rodar(tmp_path):
    import lab.rodar_opcoes as R

    def get(metodo, **p):
        if metodo == "get_book_summary_by_currency":
            return [dict(b, instrument_name=b["instrument_name"].replace("BTC", p["currency"])) for b in livro(78000)]
        if metodo == "get_index_price":
            return {"index_price": 78000}
        return {"data": []}
    assert R.main(tmp_path, get, ms(2026, 11, 6, 10)) == 0
    rel = json.loads((tmp_path / "saida" / "opcoes.json").read_text())
    assert len(rel["estrategias"]) == 4 and all(s["aberta"] for s in rel["estrategias"])
