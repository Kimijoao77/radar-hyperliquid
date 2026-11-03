"""Laboratório de funding com uma Hyperliquid de mentira."""
import json
import math

import pytest

from lab.funding import ANO_H, HORA, PADRAO, Banco, simular, universo


def banco_falso(tmp_path, series):
    b = Banco(tmp_path / "f")
    linhas = [[m, t, f, p] for m, s in series.items() for t, (f, p) in s.items()]
    b.acrescentar(linhas)
    return b


def serie(t0, horas, f, px=100.0):
    return {t0 + i * HORA: (f(i) if callable(f) else f, px) for i in range(horas)}


def test_recebe_funding_e_paga_custos(tmp_path):
    t0 = 1_700_000_000_000 // HORA * HORA
    taxa = 0.30 / ANO_H                      # 30 % ao ano, sempre
    b = banco_falso(tmp_path, {"AAA": serie(t0, 24 * 20, taxa)})
    p = {**PADRAO, "posicoes": 1}
    r = simular(b, ["AAA"], t0, t0 + (24 * 20 - 1) * HORA, p)
    tam = 1000 / (1 + 1 / p["alavancagem_perp"])
    custo = tam * (p["taxa_perp"] + p["taxa_spot"] + 2 * p["escorregamento"])
    horas_com_posicao = 24 * 20 - 44         # entra quando tem 60 % das 72 h (44 h) de média
    assert r["posicoes"] and r["posicoes"][0]["moeda"] == "AAA"
    assert r["custos"] == pytest.approx(custo, abs=0.01)
    assert r["recebido"] == pytest.approx(tam * taxa * horas_com_posicao, rel=0.02)
    assert r["lucro"] == pytest.approx(r["recebido"] - r["custos"], abs=0.02)


def test_sai_quando_vira_negativo_e_troca_por_melhor(tmp_path):
    t0 = 1_700_000_000_000 // HORA * HORA
    boa, otima = 0.25 / ANO_H, 0.80 / ANO_H
    b = banco_falso(tmp_path, {
        "AAA": serie(t0, 24 * 10, lambda i: boa if i < 24 * 6 else -boa),     # vira negativa no 6º dia
        "BBB": serie(t0, 24 * 10, lambda i: 0 if i < 24 * 3 else otima),       # começa a pagar muito no 3º dia
    })
    r = simular(b, ["AAA", "BBB"], t0, t0 + (24 * 10 - 1) * HORA, {**PADRAO, "posicoes": 1})
    saidas = [x["moeda"] for x in r["trocas"]]
    assert "AAA" in saidas                   # trocada pela melhor (ou saiu ao virar negativa)
    assert r["posicoes"][0]["moeda"] == "BBB"
    assert r["recebido"] > 0


def test_aviso_de_margem_numa_alta_forte(tmp_path):
    t0 = 1_700_000_000_000 // HORA * HORA
    taxa = 0.5 / ANO_H
    s = {t0 + i * HORA: (taxa, 100.0 * (1 + 0.01 * max(0, i - 80))) for i in range(24 * 6)}   # sobe ~1 %/h
    b = banco_falso(tmp_path, {"AAA": s})
    r = simular(b, ["AAA"], t0, t0 + (24 * 6 - 1) * HORA, {**PADRAO, "posicoes": 1})
    assert r["avisos_margem"] == 1


def test_universo_filtra_liquidez():
    meta = {"universe": [{"name": "BTC"}, {"name": "LIXO"}, {"name": "VELHA", "isDelisted": True}]}
    ctx = [{"oraclePx": "100000", "dayNtlVlm": "900000000", "openInterest": "5000", "funding": "0.0000125"},
           {"oraclePx": "0.01", "dayNtlVlm": "1000", "openInterest": "10", "funding": "0.001"},
           {"oraclePx": "1", "dayNtlVlm": "1e9", "openInterest": "1e9", "funding": "0"}]
    u = universo([meta, ctx], PADRAO)
    assert [x["moeda"] for x in u] == ["BTC"]


def test_rodar_ponta_a_ponta(tmp_path):
    import lab.rodar_funding as R
    (tmp_path / "config.json").write_text(json.dumps({"peso_por_minuto": 100000}), encoding="utf-8")
    agora_h = 1_790_000_000_000 // HORA * HORA

    class Lim:
        total = 0
        def gastar(self, p): self.total += p

    class Api:
        lim = Lim()
        def _post(self, corpo, peso):
            if corpo["type"] == "metaAndAssetCtxs":
                return [{"universe": [{"name": "BTC"}, {"name": "ETH"}]},
                        [{"oraclePx": "100000", "dayNtlVlm": "9e8", "openInterest": "5000", "funding": "0.00003"},
                         {"oraclePx": "3000", "dayNtlVlm": "5e8", "openInterest": "90000", "funding": "-0.00001"}]]
            if corpo["type"] == "fundingHistory":
                f = 0.00003 if corpo["coin"] == "BTC" else -0.00001
                ts = range(max(corpo["startTime"], agora_h - 40 * 24 * HORA) // HORA * HORA + HORA, min(corpo["endTime"], agora_h) + 1, HORA)
                return [{"coin": corpo["coin"], "fundingRate": str(f), "premium": "0", "time": t} for t in list(ts)[:500]]
            raise AssertionError(corpo)
        def velas(self, m, iv, a, b):
            return [{"t": t, "c": "100"} for t in range(a // HORA * HORA, b, HORA)]

    import time as _t
    orig = _t.time
    _t.time = lambda: agora_h / 1000 + 600
    try:
        assert R.main(tmp_path, Api()) == 0
        rel = json.loads((tmp_path / "saida" / "funding.json").read_text())
        assert rel["passado"]["posicoes"][0]["moeda"] == "BTC"
        assert rel["passado"]["lucro"] > 0
        assert rel["ranking"][0]["moeda"] == "BTC" and rel["ranking"][0]["ao_ano_7d"] == pytest.approx(0.00003 * ANO_H, rel=1e-3)
        # segunda rodada: nada novo para coletar
        assert R.main(tmp_path, Api()) == 0
        assert json.loads((tmp_path / "saida" / "funding.json").read_text())["coleta"]["horas_novas"] == 0
    finally:
        _t.time = orig
