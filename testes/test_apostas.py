"""Apostas esportivas na bolsa, com jogos de mentira."""
import json
from datetime import datetime, timezone

import pytest

from lab import rodar_apostas
from lab.apostas import (APOSTA, CAPITAL, CONFIGS, achar_resultado, avaliar, clv, efetiva, escolher, inicio_jogo, jogos_da_lista,
                         justas, ler_csv, medir, nome, resultado, temporada)

CFG = {"limiar": 0.02, "odd_min": 1.3, "odd_max": 8.0, "empate": True}


def ms(a, m, d, h=0, mi=0):
    return int(datetime(a, m, d, h, mi, tzinfo=timezone.utc).timestamp() * 1000)


def test_justas_tira_mais_margem_da_zebra():
    p = justas([1.5, 4.0, 7.0])
    assert sum(p) == pytest.approx(1)
    simples = [x / sum(1 / o for o in (1.5, 4.0, 7.0)) for x in (1 / 1.5, 1 / 4.0, 1 / 7.0)]
    assert p[0] > simples[0] and p[2] < simples[2]          # favorito mais provável, zebra menos que no corte por igual
    assert justas([2.0, None, 3.0]) is None


def test_avaliar_e_resultado_com_comissao():
    j = {"AvgH": "2.0", "AvgD": "3.4", "AvgA": "3.9", "BFEH": "2.30", "BFED": "3.5", "BFEA": "4.0"}
    a = avaliar(j, CFG)
    assert a["aposta"] == "H" and a["odd"] == 2.30 and a["vantagem"] > 0.02
    assert efetiva(2.30) == pytest.approx(1 + 1.30 * 0.95)
    assert resultado(a, "H") == pytest.approx(APOSTA * 1.30 * 0.95)
    assert resultado(a, "D") == -APOSTA
    assert avaliar({**j, "BFEH": "2.02"}, CFG) is None                 # sem vantagem depois da comissão
    assert avaliar(j, {**CFG, "odd_max": 2.0}) is None                   # fora da faixa de odds
    assert clv(a, {"BFECH": "2.0"}) == pytest.approx(0.15)               # pegou 2,30 e fechou em 2,00


def test_medir_e_escolher():
    jogos = [{"Div": "E0", "FTR": "H", "AvgH": "2.0", "AvgD": "3.4", "AvgA": "3.9", "BFEH": "2.3", "BFED": "3.5", "BFEA": "4.0", "BFECH": "2.1"},
             {"Div": "E0", "FTR": "A", "AvgH": "2.0", "AvgD": "3.4", "AvgA": "3.9", "BFEH": "2.3", "BFED": "3.5", "BFEA": "4.0", "BFECH": "2.4"},
             {"Div": "E1", "FTR": "D", "AvgH": "2.0", "AvgD": "3.4", "AvgA": "3.9", "BFEH": "2.0", "BFED": "3.5", "BFEA": "4.0"}]
    m = medir(jogos, CFG)
    assert m["apostas"] == 2 and m["acerto"] == 0.5
    assert m["lucro"] == pytest.approx(APOSTA * 1.3 * 0.95 - APOSTA)
    assert m["bateu"] == 0.5 and m["por_liga"]["E0"][0] == 2
    medidas = [{"apostas": 200, "roi": 0.01}, {"apostas": 90, "roi": 0.5}, {"apostas": 300, "roi": 0.03}]
    assert escolher(medidas) == 2 and escolher([{"apostas": 3, "roi": 1}]) is None
    assert "sem empate" in nome({"limiar": 0.04, "odd_min": 1.3, "odd_max": 4.0, "empate": False})
    assert len(CONFIGS) == 40 and {c['onde'] for c in CONFIGS} == {'bolsa', 'casa'} and {c['mercado'] for c in CONFIGS} == {'1x2', 'gols'}


def test_datas_de_londres_e_temporada():
    assert inicio_jogo("08/11/2026", "16:30") == ms(2026, 11, 8, 16, 30)        # inverno: Londres = UTC
    assert inicio_jogo("15/08/25", "20:00") == ms(2025, 8, 15, 19)              # verão: Londres = UTC+1
    assert inicio_jogo("xx", "1") is None
    assert temporada(ms(2026, 11, 9)) == "2627" and temporada(ms(2027, 5, 1)) == "2627" and temporada(ms(2026, 6, 1)) == "2526"


def test_achar_resultado_remarcado():
    a = {"liga": "BRA", "casa": "Cruzeiro", "fora": "Bahia", "inicio": ms(2026, 11, 6, 0, 30), "aposta": "H", "odd": 1.9}
    linhas = [{"Home": "Cruzeiro", "Away": "Bahia", "Date": "07/11/2026", "Time": "23:00", "HG": "3", "AG": "2", "Res": "H"},
              {"Home": "Cruzeiro", "Away": "Bahia", "Date": "20/05/2026", "Time": "23:00", "HG": "0", "AG": "0", "Res": "D"}]
    r = achar_resultado(a, linhas)
    assert r["res"] == "H" and r["placar"] == "3–2"


CAB = "Div,Date,Time,HomeTeam,AwayTeam,AvgH,AvgD,AvgA,BFEH,BFED,BFEA"
CAB_R = "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,AvgH,AvgD,AvgA,BFEH,BFED,BFEA,BFECH,BFECD,BFECA"


def test_rodar_aposta_e_depois_liquida(tmp_path, monkeypatch):
    lista = "\n".join([CAB, "E0,14/11/2026,15:00,Arsenal,Chelsea,2.0,3.4,3.9,2.3,3.5,4.0",
                       "E0,14/11/2026,15:00,Leeds,Burnley,2.0,3.4,3.9,2.0,3.5,4.0",
                       "E0,08/11/2026,15:00,Fulham,Wolves,2.0,3.4,3.9,2.3,3.5,4.0"])        # já começou: fica de fora
    extras = "Country,League,Date,Time,Home,Away,PSH,PSD,PSA,MaxH,MaxD,MaxA,AvgH,AvgD,AvgA,BFEH,BFED,BFEA\n" \
             "Brazil,Serie A,15/11/2026,22:00,Flamengo,Santos,,,,,,,1.6,4.0,5.5,1.9,4.2,5.6"
    resultados = "\n".join([CAB_R, "E0,14/11/2026,15:00,Arsenal,Chelsea,2,0,H,2.0,3.4,3.9,2.3,3.5,4.0,2.1,3.5,4.2"])
    passado = "\n".join([CAB_R] + [f"E0,10/0{1 + i % 9}/2025,15:00,T{i},U{i},2,0,H,2.0,3.4,3.9,2.3,3.5,4.0,2.2,3.5,4.0" for i in range(200)])
    pedidos = []

    def baixar(url):
        pedidos.append(url)
        if url.endswith("/fixtures.csv"):
            return lista
        if url.endswith("new_league_fixtures.csv"):
            return extras
        if "/2627/E0.csv" in url:
            return resultados
        if "/2425/E0.csv" in url or "/2526/E0.csv" in url:
            return passado
        if url.endswith("/new/BRA.csv"):
            return "Country,League,Season,Date,Time,Home,Away,HG,AG,Res,BFECH,BFECD,BFECA\n"
        return ""

    (tmp_path / "lab" / "dados").mkdir(parents=True)
    agora = ms(2026, 11, 13, 18)
    assert rodar_apostas.main(tmp_path, baixar=baixar, agora=agora) == 0
    s = json.loads((tmp_path / "saida" / "apostas.json").read_text())
    p = s["passado"]
    assert [t["papel"] for t in p["temporadas"]] == ["exigida", "escolha", "até hoje"] and not s["desligado"]
    assert p["temporadas"][0]["apostas"] == 200 and p["temporadas"][0]["roi"] > 0
    ab = s["ao_vivo"]["abertas"]
    assert {a["casa"] for a in ab} == {"Arsenal", "Flamengo"}               # Leeds sem vantagem; Fulham já começou
    assert next(a for a in ab if a["casa"] == "Flamengo")["escolha"] == "Flamengo vence"
    assert s["ao_vivo"]["em_jogo"] == 2 * APOSTA and s["ao_vivo"]["saldo"] == CAPITAL
    # 3 h depois: nada novo (intervalo); 3 dias depois: Arsenal ganhou, o Flamengo ainda sem resultado
    assert rodar_apostas.main(tmp_path, baixar=baixar, agora=agora + 3600 * 1000) == 0
    assert rodar_apostas.main(tmp_path, baixar=baixar, agora=agora + 3 * 86400 * 1000) == 0
    s = json.loads((tmp_path / "saida" / "apostas.json").read_text())
    v = s["ao_vivo"]
    assert v["apostas"] == 1 and v["acertos"] == 1 and v["clv"] == pytest.approx(2.3 / 2.1 - 1, abs=1e-4)
    assert v["saldo"] == pytest.approx(CAPITAL + APOSTA * 1.3 * 0.95, abs=0.01)
    assert [f["placar"] for f in v["fechadas"]] == ["2–0"] and len(v["abertas"]) == 1
    # 13 dias depois sem resultado do Flamengo: aposta anulada (dinheiro de volta)
    rodar_apostas.main(tmp_path, baixar=baixar, agora=agora + 13 * 86400 * 1000)
    v = json.loads((tmp_path / "saida" / "apostas.json").read_text())["ao_vivo"]
    assert not v["abertas"] and v["fechadas"][-1]["estado"] == "anulada" and v["apostas"] == 1


def test_casa_contra_a_bolsa_e_gols():
    from lab.apostas import desfecho, descrever, venceu
    j = {"BFEH": "2.0", "BFED": "3.6", "BFEA": "4.2", "B365H": "2.25", "B365D": "3.4", "B365A": "3.9",
         "BFE>2.5": "1.9", "BFE<2.5": "2.05", "B365>2.5": "2.1", "B365<2.5": "1.75", "Avg>2.5": "1.85", "Avg<2.5": "1.95"}
    a = avaliar(j, {"onde": "casa", "mercado": "1x2", "limiar": 0.02, "odd_min": 1.3, "odd_max": 4.0, "empate": False})
    assert a["aposta"] == "H" and a["odd"] == 2.25 and a["onde"] == "casa"           # a Bet365 paga 2,25 numa chance justa de ~2,04
    assert resultado(a, True) == pytest.approx(APOSTA * 1.25)                         # na casa não tem comissão
    g = avaliar(j, {"onde": "casa", "mercado": "gols", "limiar": 0.02, "odd_min": 1.3, "odd_max": 4.0, "empate": False})
    assert g["aposta"] == ">2.5" and g["odd"] == 2.1
    d = desfecho({"FTR": "H", "FTHG": "2", "FTAG": "1"})
    assert venceu(g, d) is True and venceu({**g, "aposta": "<2.5"}, d) is False and venceu(a, d) is True
    assert venceu(g, {"res": "H", "gols": None}) is None
    assert clv(g, {"BFEC>2.5": "1.75"}) == pytest.approx(2.1 / 1.75 - 1)
    assert descrever({**g, "casa": "A", "fora": "B"}) == "Mais de 2,5 gols (Bet365)"
    assert "Gols (mais ou menos de 2,5) na Bet365" in nome({"onde": "casa", "mercado": "gols", "limiar": 0.0, "odd_min": 1.3, "odd_max": 4.0, "empate": False})


def test_escolha_exige_lucro_nas_duas_temporadas():
    escolha = [{"apostas": 300, "roi": 0.05}, {"apostas": 300, "roi": 0.03}, {"apostas": 300, "roi": 0.01}]
    exigida = [{"apostas": 200, "roi": -0.02}, {"apostas": 200, "roi": 0.01}, {"apostas": 40, "roi": 0.2}]
    assert escolher(escolha, exigida) == 1                     # a melhor perdeu na outra temporada; a 3ª apostou pouco lá
    assert escolher(escolha, [{"apostas": 300, "roi": -0.01}] * 3) is None


def test_desliga_se_o_escolhido_perde_nesta_temporada(tmp_path):
    passado = "\n".join([CAB_R] + [f"E0,10/0{1 + i % 9}/2025,15:00,T{i},U{i},2,0,H,2.0,3.4,3.9,2.3,3.5,4.0,2.2,3.5,4.0" for i in range(200)])
    atual = "\n".join([CAB_R] + [f"E0,1{i % 9}/09/2026,15:00,V{i},X{i},0,1,A,2.0,3.4,3.9,2.3,3.5,4.0,2.2,3.5,4.0" for i in range(40)])

    def baixar(url):
        if "/2627/E0.csv" in url:
            return atual
        if "/2425/E0.csv" in url or "/2526/E0.csv" in url:
            return passado
        if url.endswith("fixtures.csv"):
            return CAB + "\nE0,14/11/2026,15:00,Arsenal,Chelsea,2.0,3.4,3.9,2.3,3.5,4.0"
        return ""

    (tmp_path / "lab" / "dados").mkdir(parents=True)
    assert rodar_apostas.main(tmp_path, baixar=baixar, agora=ms(2026, 11, 13, 18)) == 0
    s = json.loads((tmp_path / "saida" / "apostas.json").read_text())
    assert s["desligado"] and "perdeu nesta temporada" in s["motivo"]
    assert s["ao_vivo"]["abertas"] == []                        # desligado: não aposta mais
