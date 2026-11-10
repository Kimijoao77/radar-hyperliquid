"""Robôs de grade e DCA com velas de mentira."""
import math

import pytest

from lab.grade import CONFIGS, TENDENCIA, TODAS, dca, escolher, grade, nome, tendencia

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


# ---------- versão 4: funding e tendência ----------
def velas_lisas(precos):
    """Sem pavio: a máxima e a mínima são a abertura e o fechamento (para o rompimento ser claro)."""
    return velas(precos, 0.0)


def test_funding_cobra_de_quem_esta_comprado():
    precos = [100 + 8 * math.sin(i / 6) for i in range(24 * 30)]
    fund = {i * H: 0.0001 for i in range(1, 800)}                  # 0,01 % por hora
    sem = grade(velas(precos), 0.10, 10)
    com = grade(velas(precos), 0.10, 10, funding=fund)
    assert sem["funding_pago"] == 0 and com["funding_pago"] > 5 and com["retorno"] < sem["retorno"]
    # taxa negativa: quem está comprado recebe
    neg = grade(velas(precos), 0.10, 10, funding={i * H: -0.0001 for i in range(1, 800)})
    assert neg["funding_pago"] < 0 and neg["retorno"] > sem["retorno"]


def test_funding_no_dca_so_conta_com_posicao_aberta():
    precos = [100 * (1 - 0.003 * i) for i in range(200)]            # cai sem parar: o DCA fica preso
    fund = {i * H: 0.0001 for i in range(1, 300)}
    a, b = dca(velas(precos), 0.02, 0.015), dca(velas(precos), 0.02, 0.015, funding=fund)
    assert b["funding_pago"] > 0 and b["retorno"] < a["retorno"]
    parado = dca(velas([100.0] * 100), 0.02, 0.015, funding=fund)    # sem queda: abre, vende no alvo? não sobe; fica aberto
    assert parado["funding_pago"] >= 0


def test_tendencia_acompanha_a_alta_e_a_queda():
    alta = velas_lisas([100 * (1 + 0.0008 * i) for i in range(600)])
    r = tendencia(alta, "medias", 12, 48)
    assert r["retorno"] > 0.3 and r["horas_comprado"] == 1.0 and not r["liquidada"]
    queda = velas_lisas([200 * (1 - 0.0006 * i) for i in range(600)])
    q = tendencia(queda, "medias", 12, 48)
    assert q["retorno"] > 0.25 and q["horas_comprado"] == 0.0        # ganhou ficando vendido
    rp = tendencia(alta, "rompe", 48)
    assert rp["retorno"] > 0.3 and rp["ciclos"] == 1


def test_tendencia_funding_comprado_paga_e_vendido_recebe():
    fund = {i * H: 0.0001 for i in range(1, 700)}
    alta = velas_lisas([100 * (1 + 0.0008 * i) for i in range(600)])
    assert tendencia(alta, "medias", 12, 48, funding=fund)["retorno"] < tendencia(alta, "medias", 12, 48)["retorno"]
    queda = velas_lisas([200 * (1 - 0.0006 * i) for i in range(600)])
    com = tendencia(queda, "medias", 12, 48, funding=fund)
    assert com["funding_pago"] < 0 and com["retorno"] > tendencia(queda, "medias", 12, 48)["retorno"]


def test_tendencia_liquida_no_buraco_de_preco():
    # alta firme (fica comprado 3× desde ~120) e depois o preço cai 60 % numa vela só, para bem abaixo do preço de entrada
    precos = [100 * (1 + 0.004 * i) for i in range(200)]
    precos += [precos[-1] * 0.4] * 5
    r = tendencia(velas_lisas(precos), "medias", 12, 48, alav=3)
    assert r["liquidada"] and r["retorno"] == -1.0


def test_tendencia_sem_olhar_o_futuro():
    # o sinal sai no fechamento de uma vela e a ordem vale na abertura da seguinte: a primeira ordem nunca é na vela 0
    ops: list = []
    tendencia(velas_lisas([100 * (1 + 0.001 * i) for i in range(300)]), "medias", 12, 48, ops=ops)
    assert ops and ops[0]["t"] >= 48 * H and ops[0]["tipo"] == "compra"


def test_tendencia_usa_as_velas_de_antes():
    # com as velas de antes a tendência já vale desde a primeira hora; sem elas, espera as médias esquentarem
    todas = velas_lisas([100 * (1 + 0.001 * i) for i in range(400)])
    sem = tendencia(todas[200:], "medias", 12, 48)
    com = tendencia(todas[200:], "medias", 12, 48, antes=todas[:200])
    assert com["horas_com_posicao"] > sem["horas_com_posicao"] and com["retorno"] > sem["retorno"]


def test_janela_e_ema():
    from lab.grade import _ema, _janela
    assert _janela([1, 3, 2, 5, 4, 1], 2, True) == [None, None, 3, 3, 5, 5]
    assert _janela([1, 3, 2, 5, 4, 1], 2, False) == [None, None, 1, 2, 2, 4]
    e = _ema([10, 10, 10, 20], 3)
    assert e[:3] == [10, 10, 10] and 10 < e[3] < 20


def test_configs_de_tendencia_e_nomes():
    assert len(TENDENCIA) == 21 and len(TODAS) == 53 and {c["alav"] for c in TENDENCIA} == {1, 2, 3}
    assert nome(TENDENCIA[0]) == "Tendência: médias de 12 h e 48 h"
    assert nome({"tipo": "tendencia", "modo": "rompe", "a": 120, "alav": 2}) == "Tendência: rompimento de 5 dias, 2×"


def test_escolher_tres_de_cada_familia_ate_duas_por_moeda():
    def r(moeda, tipo, nota, liq=False):
        return {"moeda": moeda, "config": {"tipo": tipo, "n": nota}, "nota": nota, "liquidada": liq}
    passado = [r("BTC", "dca", 2.0), r("BTC", "grade", 1.9), r("BTC", "dca", 1.8), r("ETH", "dca", 1.7), r("SOL", "dca", 1.6),
               r("HYPE", "tendencia", 0.5), r("HYPE", "tendencia", 0.4), r("HYPE", "tendencia", 0.3), r("BTC", "tendencia", -0.2),
               r("ETH", "tendencia", -0.3), r("SOL", "grade", -0.1), r("ETH", "grade", 9, liq=True)]
    esc = escolher(passado)
    rev = [(x["moeda"], x["nota"]) for x in esc if x["config"]["tipo"] != "tendencia"]
    tend = [(x["moeda"], x["nota"]) for x in esc if x["config"]["tipo"] == "tendencia"]
    assert rev == [("BTC", 2.0), ("BTC", 1.9), ("ETH", 1.7)]            # até 2 por moeda; nunca a liquidada nem a de nota negativa
    assert tend == [("HYPE", 0.5), ("HYPE", 0.4), ("BTC", -0.2)]        # a tendência entra mesmo no vermelho


def test_escolher_nao_repete_o_mesmo_robo_com_outra_alavancagem():
    def r(moeda, nota, alav, a=48):
        return {"moeda": moeda, "config": {"tipo": "tendencia", "modo": "medias", "a": a, "b": 168, "alav": alav}, "nota": nota, "liquidada": False}
    passado = [r("HYPE", 5.0, 3), r("HYPE", 4.4, 2), r("HYPE", 4.0, 1), r("SOL", 2.0, 3), r("SOL", 1.0, 2), r("HYPE", 0.9, 3, a=24), r("ETH", 0.5, 2)]
    esc = escolher(passado)
    # o 2× e o 1× do mesmo sinal na mesma moeda ficam de fora (ficou o de maior nota); outro sinal na mesma moeda ainda entra
    assert [(x["moeda"], x["config"]["a"], x["config"]["alav"]) for x in esc] == [("HYPE", 48, 3), ("SOL", 48, 3), ("HYPE", 24, 3)]
    # o mesmo sinal em OUTRA moeda é outro robô
    assert [x["moeda"] for x in escolher([r("HYPE", 5.0, 3), r("SOL", 4.0, 3), r("ETH", 3.0, 3)])] == ["HYPE", "SOL", "ETH"]
