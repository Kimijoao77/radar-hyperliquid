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


def test_rodar(tmp_path, monkeypatch):
    import lab.rodar_pools as R
    pools = [pool(), pool(pool="s", symbol="USDC-USDT", stablecoin=True, ilRisk="no", exposure="multi", apyBase=6),
             pool(pool="s2", symbol="USDC-USDT", stablecoin=True, ilRisk="no", exposure="multi", apyBase=5),
             pool(pool="x", symbol="PAXG-WETH", apyBase=40),                         # sem lado estável: não dá para proteger
             pool(pool="w", project="aave-v3", symbol="WSTETH", exposure="single", ilRisk="no", apyBase=0.1),
             pool(pool="e", project="aave-v3", symbol="WETH", exposure="single", ilRisk="no", apyBase=2),
             pool(pool="l", project="lido", symbol="STETH", exposure="single", ilRisk="no", apyBase=3)]
    preco = {"eth": 100.0}

    def get(url):
        if url.endswith("/pools"):
            return {"data": pools}
        if url.endswith("/lendBorrow"):
            return [{"pool": "w", "ltv": 0.8}, {"pool": "e", "apyBaseBorrow": 2.5, "borrowable": True}]
        if "/chart/" in url:
            return {"coins": {"ethereum:0xa": {"prices": [{"price": 100}, {"price": 120}]}, "ethereum:0xb": {"prices": [{"price": 1}, {"price": 1}]}}}
        if "/prices/current/" in url:
            return {"coins": {"ethereum:0xa": {"price": preco["eth"]}, "ethereum:0xb": {"price": 1}, "coingecko:ethereum": {"price": preco["eth"]}}}
        raise AssertionError(url)

    class Api:
        def _post(self, corpo, peso):
            if corpo["type"] == "meta":
                return {"universe": [{"name": "ETH"}, {"name": "BTC"}]}
            if corpo["type"] == "fundingHistory":
                return [{"fundingRate": "0.00001"}] * 12
            raise AssertionError(corpo)

    # resultado da versão 1 gravado antes: vira "anterior"
    (tmp_path / "saida").mkdir()
    (tmp_path / "saida" / "pools.json").write_text(json.dumps({"gerado": 5, "carteira": {"capital": 1000, "saldo": 992.59, "inicio": 1}}))
    t = {"agora": 1_790_000_000.0}
    monkeypatch.setattr(R.time, "time", lambda: t["agora"])
    assert R.main(tmp_path, get, Api()) == 0
    rel = json.loads((tmp_path / "saida" / "pools.json").read_text())
    assert rel["estaveis"][0]["id"] == "s" and rel["volateis"][0]["perda_30d"] < 0 and rel["loops"]
    assert rel["anterior"][0]["retorno"] == pytest.approx(-0.0074, abs=1e-4)
    tipos = [i["tipo"] for i in rel["carteira"]["itens"]]
    assert tipos == ["estavel", "volatil", "loop"]                    # USDC-USDT só uma vez; PAXG-WETH fora
    # 12 h depois o ETH sobe 10 %: a proteção anula quase todo o efeito do preço
    preco["eth"] = 110.0
    t["agora"] += 12 * 3600
    assert R.main(tmp_path, get, Api()) == 0
    rel = json.loads((tmp_path / "saida" / "pools.json").read_text())
    parte = 1000 / 3
    vol, loop = rel["carteira"]["itens"][1], rel["carteira"]["itens"][2]
    assert vol["moedas"] > 0 and vol["protecao"] < 0 and abs(vol["moedas"] + vol["protecao"]) < 0.01 * parte
    assert abs(loop["moedas"] + loop["protecao"]) < 0.001 * parte and loop["funding"] > 0
    assert len(rel["anterior"]) == 1
