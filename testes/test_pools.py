import json

import pytest

from lab.pools import PADRAO, com_perda, loops, perda_impermanente, volateis


def test_perda_impermanente():
    assert perda_impermanente(1) == 0
    assert perda_impermanente(2) == pytest.approx(-0.0572, abs=1e-3)      # uma dobra em relação à outra: −5,7 %
    assert perda_impermanente(0.5) == pytest.approx(-0.0572, abs=1e-3)


def pool(**k):
    base = {"pool": "p", "project": "uniswap-v3", "chain": "Ethereum", "symbol": "ETH-USDC", "tvlUsd": 9e6, "count": 90, "outlier": False,
            "apyBase": 20, "apyReward": 5, "apyMean30d": 18, "exposure": "multi", "ilRisk": "yes", "stablecoin": False, "underlyingTokens": ["0xa", "0xb"]}
    return {**base, **k}


def test_volateis_e_perda():
    v = volateis([pool(), pool(pool="q", tvlUsd=10), pool(pool="r", apyBase=0)], PADRAO)
    assert [x["id"] for x in v] == ["p"]
    precos = {"ethereum:0xa": {"prices": [{"price": 100}, {"price": 200}]}, "ethereum:0xb": {"prices": [{"price": 1}, {"price": 1}]}}
    x = com_perda(v[0], precos)
    assert x["perda_30d"] == pytest.approx(-0.0572, abs=1e-3)
    assert x["liquido_30d"] == pytest.approx(0.2 / 12 - 0.0572, abs=1e-3)


def test_looping():
    pools = [pool(pool="w", project="aave-v3", symbol="WSTETH", exposure="single", ilRisk="no", apyBase=0.1),
             pool(pool="e", project="aave-v3", symbol="WETH", exposure="single", ilRisk="no", apyBase=2),
             pool(pool="l", project="lido", symbol="STETH", exposure="single", ilRisk="no", apyBase=3)]
    emp = {"w": {"ltv": 0.8}, "e": {"apyBaseBorrow": 2.5, "borrowable": True}}
    lp = loops(pools, emp)
    n = {x["vezes"]: x for x in lp[0]["niveis"]}
    assert n[3]["ao_ano"] == pytest.approx(3 * 0.031 - 2 * 0.025)
    assert 0 < n[3]["descolamento_que_liquida"] < n[2]["descolamento_que_liquida"]


def test_rodar(tmp_path):
    import lab.rodar_pools as R
    pools = [pool(), pool(pool="s", symbol="USDC-USDT", stablecoin=True, ilRisk="no", exposure="multi", apyBase=6),
             pool(pool="w", project="aave-v3", symbol="WSTETH", exposure="single", ilRisk="no", apyBase=0.1),
             pool(pool="e", project="aave-v3", symbol="WETH", exposure="single", ilRisk="no", apyBase=2),
             pool(pool="l", project="lido", symbol="STETH", exposure="single", ilRisk="no", apyBase=3)]

    def get(url):
        if url.endswith("/pools"):
            return {"data": pools}
        if url.endswith("/lendBorrow"):
            return [{"pool": "w", "ltv": 0.8}, {"pool": "e", "apyBaseBorrow": 2.5, "borrowable": True}]
        if "/chart/" in url:
            return {"coins": {"ethereum:0xa": {"prices": [{"price": 100}, {"price": 120}]}, "ethereum:0xb": {"prices": [{"price": 1}, {"price": 1}]}}}
        if "/prices/current/" in url:
            return {"coins": {"ethereum:0xa": {"price": 110}, "ethereum:0xb": {"price": 1}}}
        raise AssertionError(url)
    assert R.main(tmp_path, get) == 0
    rel = json.loads((tmp_path / "saida" / "pools.json").read_text())
    assert rel["estaveis"][0]["id"] == "s" and rel["volateis"][0]["perda_30d"] < 0 and rel["loops"]
    assert len(rel["carteira"]["itens"]) == 3 and rel["carteira"]["capital"] == 1000
