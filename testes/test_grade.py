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
    assert len(CONFIGS) == 32 and nome(CONFIGS[0]).startswith("Grade ±10 %")
    assert {c["alav"] for c in CONFIGS} == {1, 2, 3}              # versão 3: com 2× e 3× (o máximo de lucro)
    assert nome({"tipo": "dca", "passo": 0.02, "alvo": 0.03, "alav": 3, "pausa": True}).find("3×") > 0
    assert nome({"tipo": "dca", "passo": 0.02, "alvo": 0.015, "alav": 1, "pausa": True}).endswith("pausa na queda")


def test_dca_com_pausa_fica_no_caixa_na_queda_longa():
    # já vinha caindo (a média de 7 dias está acima do preço) e continua caindo devagar por 300 horas: sem pausa, o DCA
    # fica preso e perde muito; com a pausa, não abre ciclo (a pausa não fecha um ciclo já aberto, só evita abrir)
    hist = [120 - 20 * i / 167 for i in range(168)]
    precos = [100 * (1 - 0.003 * i) for i in range(1, 301)]
    sem = dca(velas(precos), 0.02, 0.015)
    com = dca(velas(precos), 0.02, 0.015, media_h=168, historico=hist)
    assert sem["retorno"] < -0.3 and com["retorno"] > sem["retorno"] + 0.25
    assert com["horas_pausado"] > 0.5


def test_dca_com_pausa_volta_a_operar_na_alta():
    hist = [90.0] * 168                                           # vinha de baixo: a média é 90
    precos = [100 + (i % 6) for i in range(200)]                  # anda acima da média, sobe e desce
    r = dca(velas(precos), 0.02, 0.015, media_h=168, historico=hist)
    assert r["ciclos"] >= 1 and r["horas_pausado"] < 0.2


def test_escolha_honesta_usa_a_pior_nota():
    from lab.grade import nota_honesta
    boa = {"retorno": 0.2, "pior_queda": 0.1}
    ruim = {"retorno": -0.05, "pior_queda": 0.2}
    assert nota_honesta(boa, ruim) < 0 < nota_honesta(boa, boa)


def test_nota_lucro():
    from lab.grade import nota_lucro
    a = {"retorno": 0.10, "dias": 100, "liquidada": False}
    b = {"retorno": 0.02, "dias": 50, "liquidada": False}
    assert 0 < nota_lucro(a, b) < 0.2 and nota_lucro(a, {**b, "liquidada": True}) == -9
