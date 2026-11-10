"""Vender moeda recém-listada: operações, carteira e o executor com uma Hyperliquid de mentira."""
import json

import pytest

import lab.rodar_listagens as R
from lab.listagens import (ESPERA_H, HORA, MAXIMO, PARTE, PRAZO_H, TAXA, carteira, com_alav, estreia_de, manutencao, r1,
                           resumo_op, simular)

T0 = 1_790_000_000_000 // HORA * HORA


def velas_de(precos, t0=T0, iv=HORA, salto=None):
    out = []
    for i, p in enumerate(precos):
        a = precos[i - 1] if i else p
        o = salto if (salto and i == salto[0]) else a
        o = o[1] if isinstance(o, tuple) else o
        out.append({"t": t0 + i * iv, "o": o, "c": p, "h": max(o, p), "l": min(o, p)})
    return out


def test_estreia_e_manutencao():
    assert estreia_de([{"time": T0 + 3 * HORA + 61}, {"time": T0 + 4 * HORA + 50}]) == T0 + 2 * HORA
    assert estreia_de([]) is None
    assert manutencao(3) == pytest.approx(1 / 6) and manutencao(10) == pytest.approx(0.05)


def test_moeda_que_cai_da_lucro_em_14_dias():
    precos = [1.0] * ESPERA_H + [1.0 - 0.4 * i / PRAZO_H for i in range(PRAZO_H + 30)]
    fund = {T0 + h * HORA: 0.0001 for h in range(1, 600)}            # funding positivo: o vendido recebe
    op = simular("NOVA", T0, velas_de(precos), fund, HORA)
    assert op["entrada"] == T0 + ESPERA_H * HORA and op["px_e"] == pytest.approx(1.0)
    assert op["motivo"] == "14 dias" and op["saida"] == op["entrada"] + PRAZO_H * HORA
    assert op["fund"] > 0.02                                         # ~336 h × 0,01 % sobre uma posição que encolhe
    rel = op["caminho"][-1][1]
    assert op["r1"] == pytest.approx((1 - rel) - TAXA - TAXA * rel + op["fund"], abs=1e-4) and op["r1"] > 0.4
    assert len(op["caminho"]) <= 90


def test_moeda_que_dispara_para_em_30_por_cento():
    precos = [1.0] * ESPERA_H + [1.0, 1.1, 1.2, 1.25, 1.4, 1.6] + [1.6] * 400
    op = simular("FOGUETE", T0, velas_de(precos), {}, HORA)
    assert op["motivo"] == "parada: subiu 30 %" and op["px_s"] == pytest.approx(1.3)
    assert op["r1"] == pytest.approx(-0.3 - TAXA - TAXA * 1.3, abs=1e-5)
    assert com_alav(op, 1.3, 0.0, 2) == pytest.approx(2 * op["r1"], abs=1e-4)    # 2×: perde o dobro (a liquidação ficava em +33 %)


def test_salto_acima_da_liquidacao_perde_a_margem():
    precos = [1.0] * ESPERA_H + [1.0, 1.05] + [1.5] * 400
    vs = velas_de(precos)
    vs[ESPERA_H + 2]["o"] = 1.45                                     # a vela já abre 45 % acima: a parada não pega
    vs[ESPERA_H + 2]["h"] = 1.5
    op = simular("SALTO", T0, vs, {}, HORA, alav_max=3)
    assert op["px_s"] == pytest.approx(1.45)
    assert com_alav(op, 1.45, 0.0, 2) == -1.0                        # 2× liquida em +33 %: perdeu a margem inteira
    assert com_alav(op, 1.45, 0.0, 1) == pytest.approx(r1(1.45, 0.0))  # 1× liquidaria só em +83 %


def test_ainda_nao_deu_24_horas():
    assert simular("CEDO", T0, velas_de([1.0] * 10), {}, HORA) is None


def test_saiu_da_hyperliquid_fecha_no_ultimo_preco():
    precos = [1.0] * ESPERA_H + [0.9, 0.8, 0.7]
    op = simular("FORA", T0, velas_de(precos), {}, HORA, fora=True)
    assert op["motivo"] == "saiu da Hyperliquid" and op["px_s"] == pytest.approx(0.7)
    aberta = simular("VIVA", T0, velas_de(precos), {}, HORA)
    assert aberta["saida"] is None and resumo_op(aberta)["aberta"]


def _op(nome, entrada, rels, iv=HORA, fechada=True):
    cam = [[entrada + (i + 1) * iv, r, 0.0] for i, r in enumerate(rels)]
    return {"moeda": nome, "estreia": entrada - ESPERA_H * HORA, "entrada": entrada, "px_e": 1.0, "saida": cam[-1][0] if fechada else None,
            "px_s": rels[-1] if fechada else None, "motivo": "14 dias" if fechada else None, "manut": 1 / 6, "fund": 0.0,
            "subiu_max": 0.0, "r1": r1(rels[-1], 0.0), "caminho": cam}


def test_carteira_10_por_cento_por_moeda():
    a = _op("A", T0, [0.9, 0.8, 0.5])                                   # caiu 50 %: +50 % sobre a margem (1×)
    b = _op("B", T0 + 10 * HORA, [1.1, 1.3])                            # subiu 30 %: −30 %
    c1 = carteira([a, b], 1)
    ra, rb = r1(0.5, 0), r1(1.3, 0)
    m_a = PARTE * 1000
    m_b = PARTE * 1000                                                  # o livro ainda vale 1.000 quando B entra (A só fecha em T0 + 3 h... já fechou)
    m_b = PARTE * (1000 - m_a + m_a * (1 + ra))
    assert c1["patrimonio"] == pytest.approx(1000 + m_a * ra + m_b * rb, abs=0.01)
    assert c1["operacoes"] == 2 and c1["acertos"] == 1 and c1["pior_queda"] > 0
    c2 = carteira([a, b], 2)
    assert c2["retorno"] != c1["retorno"]


def test_carteira_no_maximo_10_abertas():
    ops = [_op(f"M{i}", T0, [0.99] * 5) for i in range(MAXIMO + 2)]
    c = carteira(ops, 1)
    assert c["operacoes"] == MAXIMO and c["puladas"] == 2


def test_carteira_ao_vivo_mostra_as_abertas():
    c = carteira([_op("V", T0, [0.95, 0.9], fechada=False)], 1, inicio=T0 - HORA)
    assert c["abertas"] == 1 and c["operacoes"] == 0 and c["retorno"] > 0
    assert c["curva"][0] == [T0 - HORA, 0.0]


# ---------- o executor ----------
class Api:
    """Moedas novas: VELHA estreou há 100 dias e caiu; FOGO estreou há 60 dias e disparou; NOVA estreou depois do começo."""

    def __init__(self, agora, nova_desde=None):
        self.agora = agora
        self.estreias = {"BTC": agora - 900 * 24 * HORA, "VELHA": agora - 100 * 24 * HORA, "FOGO": agora - 60 * 24 * HORA}
        if nova_desde:
            self.estreias["NOVA"] = nova_desde
        self.chamadas = []

    def preco(self, moeda, t):
        h = (t - self.estreias[moeda]) / HORA
        if moeda == "FOGO":
            return 1.0 + max(0, h - 30) * 0.01
        return 1.0 / (1 + max(0, h - 24) * 0.002)

    def _post(self, corpo, peso):
        self.chamadas.append(corpo["type"])
        if corpo["type"] == "meta":
            return {"universe": [{"name": m, "maxLeverage": 3} for m in self.estreias]}
        if corpo["type"] == "fundingHistory":
            e = self.estreias[corpo["coin"]]
            h = max(e + HORA, (corpo["startTime"] // HORA + 1) * HORA)
            fim = min(self.agora, corpo.get("endTime") or self.agora)
            out = []
            while h <= fim and len(out) < 500:
                out.append({"coin": corpo["coin"], "fundingRate": "0.00005", "time": h + 61})
                h += HORA
            return out
        raise AssertionError(corpo)

    def velas(self, moeda, iv, a, b):
        self.chamadas.append(f"velas {iv}")
        passo = HORA if iv == "1h" else 4 * HORA
        e = self.estreias[moeda]
        t = max(a, e) // passo * passo
        out = []
        while t <= b and t + passo <= self.agora:
            o, c = self.preco(moeda, t), self.preco(moeda, t + passo)
            out.append({"t": t, "T": t + passo - 1, "o": str(o), "c": str(c), "h": str(max(o, c)), "l": str(min(o, c))})
            t += passo
        return out


def test_rodar_passado_e_ao_vivo(tmp_path):
    agora = T0 + 1000 * HORA
    api = Api(agora)
    assert R.main(tmp_path, api, agora) == 0
    rel = json.loads((tmp_path / "saida" / "listagens.json").read_text())
    ops = {o["moeda"]: o for o in rel["passado"]["operacoes"]}
    assert set(ops) == {"VELHA", "FOGO"}                               # BTC é antiga demais
    assert ops["VELHA"]["motivo"] == "14 dias" and ops["VELHA"]["r"]["1"] > 0.3
    assert ops["FOGO"]["motivo"] == "parada: subiu 30 %" and ops["FOGO"]["r"]["2"] < -0.5
    assert set(rel["passado"]["variantes"]) == {"1", "2"} and rel["ao_vivo"]["variantes"]["1"]["retorno"] == 0
    est = json.loads((tmp_path / "lab" / "dados" / "listagens_estado.json").read_text())
    assert "_lista" not in json.dumps(est) and est["moedas"]["VELHA"]["estreia"] == api.estreias["VELHA"]

    # 2 horas depois: estreou uma moeda nova; 30 h depois dela, a venda ao vivo já entrou
    agora2 = agora + 2 * HORA
    api2 = Api(agora2 + 30 * HORA, nova_desde=agora2)
    assert R.main(tmp_path, api2, agora2 + 30 * HORA) == 0
    rel2 = json.loads((tmp_path / "saida" / "listagens.json").read_text())
    vivo = rel2["ao_vivo"]["operacoes"]
    assert [o["moeda"] for o in vivo] == ["NOVA"] and vivo[0]["aberta"]
    assert rel2["ao_vivo"]["variantes"]["1"]["abertas"] == 1
    assert {o["moeda"] for o in rel2["passado"]["operacoes"]} == {"VELHA", "FOGO"}
    assert api2.chamadas.count("fundingHistory") <= 3                 # as estreias já conhecidas não são buscadas de novo


def test_rodar_espera_as_24_horas(tmp_path):
    agora = T0 + 1000 * HORA
    assert R.main(tmp_path, Api(agora), agora) == 0
    agora2 = agora + 2 * HORA
    assert R.main(tmp_path, Api(agora2 + 5 * HORA, nova_desde=agora2), agora2 + 5 * HORA) == 0
    rel = json.loads((tmp_path / "saida" / "listagens.json").read_text())
    assert rel["ao_vivo"]["operacoes"] == [] and [e["moeda"] for e in rel["ao_vivo"]["esperando"]] == ["NOVA"]
