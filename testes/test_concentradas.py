"""Pools concentradas com pools e velas de mentira."""
import json

import pytest

from lab import rodar_concentradas
from lab.concentradas import FATOR, abrir, andar, escolher, fechar, liquidez, valor_usd, valor_y

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


def test_taxa_so_dentro_da_faixa_e_saida():
    pos = abrir(pool(), "estreita", 1000, T0)
    assert valor_usd(pos) == pytest.approx(1000 * (1 - 0.007), rel=1e-6)          # metade trocada a 1 % + 0,2 %
    velas = [[(T0 + i * 300000) / 1000, 1, 1, 1, c, 10] for i, c in enumerate([1.0, 1.01, 0.99])]
    assert andar(pos, velas, 2.0, 150, T0 + 3 * 300000) is None
    taxa = 993 * 0.02 / 12 * FATOR["estreita"] * 3
    assert pos["taxas"] == pytest.approx(taxa, rel=0.02)
    assert andar(pos, [[(T0 + 3 * 300000) / 1000, 1, 1, 1, 0.9, 1]], 2.0, 150, T0 + 4 * 300000) == "saiu da faixa"
    assert fechar(pos) < 1000


def test_rodar(tmp_path):
    (tmp_path / "lab" / "dados").mkdir(parents=True)

    class G:
        def get(self, caminho, **k):
            return {"data": {"attributes": {"ohlcv_list": [[(T0 + 3600 * 1000 + i * 300000) / 1000, 1, 1, 1, 1.0, 1] for i in range(12)]}}}

    lista = {"data": [pool("a", ftvl24=80), pool("b", ftvl24=60), pool("c", ftvl24=40), pool("d", ftvl24=20)]}
    met = lambda caminho, **k: lista if caminho == "/pools" else None  # noqa: E731
    assert rodar_concentradas.main(tmp_path, meteora=met, gecko=G(), agora=T0) == 0
    s = json.loads((tmp_path / "saida" / "concentradas.json").read_text())
    assert [len(f["abertas"]) for f in s["faixas"].values()] == [3, 3, 3]
    assert [p["nome"] for p in s["faixas"]["larga"]["abertas"]] == ["MEME-SOL"] * 3
    rodar_concentradas.main(tmp_path, meteora=met, gecko=G(), agora=T0 + 2 * 3600 * 1000)
    s = json.loads((tmp_path / "saida" / "concentradas.json").read_text())
    e, l = s["faixas"]["estreita"]["abertas"][0], s["faixas"]["larga"]["abertas"][0]
    assert e["taxas"] > l["taxas"] > 0 and e["horas_dentro"] == 1.0
