"""Robôs de grade e DCA com velas de mentira."""
import math

import pytest

from lab.grade import CONFIGS, dca, grade, nome

H = 3600 * 1000


def velas(precos, amp=0.0):
    out = []
    for i, p in enumerate(precos):
        a = precos[i - 1] if i else p
        out.append({"t": i * H, "o": a, "c": p, "h": max(a, p) * (1 + amp), "l": min(a, p) * (1 - amp)})
    return out


def test_grade_ganha_andando_de_lado():
    precos = [100 + 8 * math.sin(i / 6) for i in range(24 * 30)]
    r = grade(velas(precos), 0.10, 10)
    assert r["ciclos"] > 20 and r["retorno"] > 0 and r["fora_da_faixa"] == 0


def test_grade_sai_por_baixo_e_perde():
    precos = [100 - i * 0.05 for i in range(24 * 30)]      # cai 36 %
    r = grade(velas(precos), 0.10, 10)
    assert r["retorno"] < 0 and r["fora_da_faixa"] > 0.5


def test_grade_alavancada_liquida_numa_queda_forte():
    precos = [100 * (1 - 0.004 * i) for i in range(240)]    # cai ~96 %
    r = grade(velas(precos), 0.10, 10, alav=3)
    assert r["liquidada"]


def test_dca_acerta_no_repique():
    precos = [100, 99, 98, 97, 96, 95, 96, 97, 98, 99, 100, 101]
    r = dca(velas(precos), 0.02, 0.015)
    assert r["ciclos"] >= 1 and r["retorno"] > 0


def test_dca_alavancado_quebra_numa_queda_sem_volta():
    precos = [100 * (1 - 0.003 * i) for i in range(300)]
    assert dca(velas(precos), 0.02, 0.015, alav=3)["liquidada"]
    r1 = dca(velas(precos), 0.02, 0.015)
    assert not r1["liquidada"] and r1["retorno"] < -0.5


def test_nomes():
    assert len(CONFIGS) == 16 and nome(CONFIGS[0]).startswith("Grade ±10 %")
