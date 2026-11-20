"""A simulação "e se a máquina existisse desde o começo" (lab/simular_host.py), com velas e fills de mentira."""
import pytest

from lab import copia as C
from lab import simular_host as S

W = "0xaaa"
T0 = S.ms_do_dia(S.INICIO_PADRAO)
MIN = 60_000


def carteira():
    return {"carteira": W, "desde": S.INICIO_PADRAO, "classe_nome": "Habilidade provável", "copiavel": {"ok": True},
            "geral": {"duracao_mediana_min": 240}, "copia": {"alavancagem": {"exposicao_mediana": 1.0}, "conta_ref": 10_000.0}}


def precos_subindo():
    """BTC sobe 1 % por minuto durante 5 minutos logo depois da compra dela, e fica lá."""
    p = C.Precos()
    velas, px = [], 100.0
    for i in range(-10, 180):
        t = T0 + 60 * MIN + i * MIN
        novo = px * 1.01 if 0 <= i < 5 else px
        velas.append({"t": t, "T": t + MIN, "o": px, "c": novo})
        px = novo
    p.juntar("BTC", velas)
    return p


def test_quem_copia_no_preco_dela_ganha_o_que_o_atraso_de_um_minuto_perde():
    t = T0 + 60 * MIN
    fills = {W: [{"t": t, "c": "BTC", "s": "B", "p": 100.0, "z": 30.0, "sp": 0.0, "id": 1}]}     # ela põe 30 % do saldo
    fotos = {W: [{"t": T0, "a": W, "v": 10_000.0, "pos": []}]}
    var, ate = C.VARIANTES["seletiva"], T0 + 3 * S.HORA
    r = {k: S.simular({W: carteira()}, fills, fotos, precos_subindo(), var, T0, ate, *v) for k, v in S.CENARIOS.items()}
    fim = 100 * 1.01 ** 5
    # normal: entra 60 s depois, com o preço já 1 % acima; host: no preço dela
    assert r["normal"]["retorno"] == pytest.approx(0.3 * (fim / (101 * 1.0005) - 1) - 0.3 * C.TAXA, abs=6e-5)
    assert r["host"]["retorno"] == pytest.approx(0.3 * (fim / (100 * 1.0005) - 1) - 0.3 * C.TAXA, abs=6e-5)
    assert r["host_prudente"]["retorno"] == pytest.approx(0.3 * (fim / (100 * 1.002) - 1) - 0.3 * C.TAXA, abs=6e-5)
    assert r["normal"]["retorno"] < r["host_vela"]["retorno"] < r["host_prudente"]["retorno"] < r["host"]["retorno"]
    assert all(x["ordens"] == 1 and x["carteiras"] == 1 and len(x["curva"]) == 3 for x in r.values())
    assert C.ESCORREGA == 0.0005                                   # a simulação devolve o escorregamento do laboratório
