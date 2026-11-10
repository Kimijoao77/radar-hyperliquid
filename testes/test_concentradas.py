"""Pools concentradas com pools e velas de mentira."""
import json

import pytest

from lab import rodar_concentradas
from lab.concentradas import FATOR, REDE, abrir, andar, balanco, escolher, fechar, liquidez, parte_moeda, valor_usd, valor_y

T0 = 1_762_700_000_000 - 1_762_700_000_000 % 300000


def pool(addr="P", preco=1.0, ftvl24=50, ftvl1=2.0, y="SOL", tvl=100000, vol=900000, taxa=1.0):
    return {"address": addr, "name": f"MEME-{y}", "is_blacklisted": False, "tvl": tvl, "volume": {"24h": vol}, "current_price": preco,
            "fee_tvl_ratio": {"24h": ftvl24, "1h": ftvl1}, "dynamic_fee_pct": taxa,
            "token_x": {"address": "X" + addr, "symbol": "MEME", "price": preco * 150}, "token_y": {"address": "SOLmint", "symbol": y, "price": 150}}


def test_conta_da_liquidez_concentrada():
    a, b = 0.95, 1.05
    L = liquidez(100, 1.0, a, b)
    assert valor_y(L, 1.0, a, b) == pytest.approx(100)
    assert valor_y(L, 0.9, a, b) < 100 * 0.95            # abaixo da faixa: toda em moeda, que caiu
    assert valor_y(L, 1.2, a, b) == pytest.approx(valor_y(L, 1.05, a, b))   # acima: todo SOL, não ganha mais
    assert FATOR["estreita"] == pytest.approx(5.8, abs=0.05) and FATOR["larga"] == 1


def test_escolher():
    ps = [pool("a", ftvl24=10), pool("b", ftvl24=90), pool("c", y="BONK"), pool("d", tvl=10), {**pool("e"), "is_blacklisted": True}]
    assert [p["address"] for p in escolher(ps)] == ["b", "a"]


def test_balanco():
    assert balanco([1.0] * 10) is None                       # menos de 24 h de velas
    assert balanco([1.0] * 30) == pytest.approx(0)
    assert balanco([1.0, 1.05] * 15) > 0.02                  # sobe e desce 5 % toda hora


def test_so_sol_abaixo_do_preco():
    pos = abrir(pool(), "estreita", 1000, T0)
    assert pos["b"] == pytest.approx(1.0) and pos["a"] == pytest.approx(0.9)
    assert valor_usd(pos) == pytest.approx(1000 * (1 - REDE), rel=1e-6)            # sem troca: só a rede
    assert parte_moeda(pos["L"], 1.0, pos["a"], pos["b"]) == 0
    # o preço cai 2 % e fica: recebe taxa e vira um pouco de moeda
    velas = [[(T0 + i * 300000) / 1000, 1, 1, 1, 0.98, 10] for i in range(3)]
    assert andar(pos, velas, 2.0, 150, T0 + 3 * 300000) is None
    assert pos["taxas"] > 0 and 0 < parte_moeda(pos["L"], 0.98, pos["a"], pos["b"]) < 1
    # sobe acima da entrada: fica todo em SOL; só sai depois de 3 h lá em cima, sem perda além da rede
    pos2 = abrir(pool(), "estreita", 1000, T0)
    assert andar(pos2, [[T0 / 1000, 1, 1, 1, 1.03, 1]], 2.0, 150, T0 + 300000) is None
    acima = [[(T0 + i * 300000) / 1000, 1, 1, 1, 1.03, 1] for i in range(1, 37)]
    assert andar(pos2, acima, 2.0, 999, T0 + 37 * 300000) == "subiu e ficou 3 h acima: reabre no preço novo"
    assert fechar(pos2) == pytest.approx(1000 * (1 - REDE) * (1 - REDE), rel=1e-6)    # o SOL que mudou de preço não conta
    # cai abaixo da faixa: vira toda moeda e paga a venda dela
    pos3 = abrir(pool(), "estreita", 1000, T0)
    assert andar(pos3, [[T0 / 1000, 1, 1, 1, 0.85, 1]], 2.0, 150, T0 + 300000) == "caiu abaixo da faixa"
    assert fechar(pos3) < 950


def test_rodar(tmp_path):
    (tmp_path / "lab" / "dados").mkdir(parents=True)

    class G:
        def get(self, caminho, **k):
            if caminho.endswith("/hour"):                     # balanço: preço parado nas últimas 24 h (pool "d" balança muito)
                c = [1.0, 1.1] * 13 if "/d/" in caminho else [1.0] * 26
                return {"data": {"attributes": {"ohlcv_list": [[(T0 - (26 - i) * 3600 * 1000) / 1000, 1, 1, 1, x, 1] for i, x in enumerate(c)]}}}
            return {"data": {"attributes": {"ohlcv_list": [[(T0 + 3600 * 1000 + i * 300000) / 1000, 1, 1, 1, 1.0, 1] for i in range(12)]}}}

    lista = {"data": [pool("d", ftvl24=99), pool("a", ftvl24=80), pool("b", ftvl24=60), pool("c", ftvl24=40)]}
    met = lambda caminho, **k: lista if caminho == "/pools" else None  # noqa: E731
    assert rodar_concentradas.main(tmp_path, meteora=met, gecko=G(), agora=T0) == 0
    s = json.loads((tmp_path / "saida" / "concentradas.json").read_text())
    assert [len(f["abertas"]) for f in s["faixas"].values()] == [3, 3, 3, 3]
    assert all(p["pool"] != "d" for f in s["faixas"].values() for p in f["abertas"])     # a que balança fica de fora
    assert [p["nome"] for p in s["faixas"]["larga"]["abertas"]] == ["MEME-SOL"] * 3
    rodar_concentradas.main(tmp_path, meteora=met, gecko=G(), agora=T0 + 2 * 3600 * 1000)
    s = json.loads((tmp_path / "saida" / "concentradas.json").read_text())
    e, l = s["faixas"]["estreita"]["abertas"][0], s["faixas"]["larga"]["abertas"][0]
    assert e["taxas"] > l["taxas"] > 0 and e["horas_dentro"] == 1.0


def test_fator_da_versao_5_compara_com_a_pool_e_divide_com_o_nosso_dinheiro():
    from lab.concentradas import FATOR, faixa_tipica, fator
    assert faixa_tipica(20) == pytest.approx(1.002 ** 34 - 1) and faixa_tipica(None) == 0.05 and faixa_tipica(500) == 0.6
    p = {**pool(tvl=20_000), "pool_config": {"bin_step": 20}}
    f = fator(p, "agressiva", 333)
    assert 2 < f < 4 and f < FATOR["agressiva"] / 4          # bem abaixo das 14 vezes da conta antiga
    assert fator(p, "agressiva", 5000) < f / 1.5                 # mais dinheiro na mesma pool = fatia menor de cada dólar
    assert fator({**p, "tvl": 10_000_000}, "agressiva", 333) == pytest.approx(f * 1.058, rel=0.01)   # pool grande: sem os 5,5 % de diluição
    assert fator(p, "larga", 333) < 1                            # faixa mais larga que a das outras posições: menos que a média
    pos = abrir(p, "estreita", 333, T0)
    assert pos["fator"] == pytest.approx(fator(p, "estreita", 333), rel=1e-3) and pos["bin_step"] == 20
