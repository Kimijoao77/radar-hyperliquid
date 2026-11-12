"""Cópia fiel com preços e fills de mentira."""
import json

import pytest

from lab import copia as C

M = C.MINUTO
T0 = 1_800_000_000_000 // M * M


def velas_minuto(precos, t0=T0):
    """Uma vela de 1 min por preço (abre no anterior, fecha no atual)."""
    return [{"t": t0 + i * M, "T": t0 + (i + 1) * M - 1, "o": str(precos[i - 1] if i else p), "c": str(p)} for i, p in enumerate(precos)]


def fill(t, moeda, lado, z, px, sp):
    return {"t": t, "c": moeda, "s": lado, "z": z, "p": px, "sp": sp}


def precos_eth(seq):
    pr = C.Precos()
    pr.juntar("ETH", velas_minuto(seq))
    return pr


def test_preco_interpola_dentro_da_vela():
    pr = precos_eth([100, 110])
    assert pr.em("ETH", T0 + M + M // 2) == pytest.approx(105)
    assert pr.em("ETH", T0 - 1) is None


def test_eventos_juntam_o_minuto_e_atrasam():
    fs = [fill(T0 + 1000, "ETH", "B", 1, 100, 0), fill(T0 + 5000, "ETH", "B", 1, 100, 1), fill(T0 + 3 * M, "ETH", "A", 2, 101, 2),
          fill(T0 + 4 * M, "@107", "B", 5, 1, 0), fill(T0 + 4 * M, "PURR/USDC", "B", 5, 1, 0)]
    evs = C.eventos(fs, 0, 60_000)
    assert [e["pos"] for e in evs] == [2, 0]                       # spot e pares ficam de fora
    assert evs[0]["exec"] == T0 + 5000 + 60_000


def test_fills_do_mesmo_instante_seguem_a_cadeia():
    # caso real (ADA, 08/11): vendido 102.244 e fecha com 3 fills no mesmo milissegundo, que a API manda fora de ordem
    t = T0 + 5 * M + 400
    fs = [fill(T0 + 10, "ADA", "A", 102244, 0.5, 0),
          fill(t, "ADA", "B", 62639, 0.5, -102244),
          fill(t, "ADA", "B", 26426, 0.5, -26426),                   # o último da cadeia veio no meio
          fill(t, "ADA", "B", 13179, 0.5, -39605)]
    assert [round(C.posicao_apos(f)) for f in C.em_ordem(fs)] == [-102244, -39605, -26426, 0]
    evs = C.eventos(fs, 0, 60_000)
    assert [e["pos"] for e in evs] == [-102244, 0]                 # antes: ficava -26.426 (um resto que ela já fechou)
    # sem a posição de antes (só o grupo), a cadeia começa no "antes" que não é o "depois" de ninguém
    assert C.posicao_apos(C.em_ordem(fs[1:])[-1]) == 0
    # abre e fecha no mesmo instante (volta ao zero): a posição de antes decide a ordem
    t2 = T0 + 9 * M
    gira = [fill(t2, "ADA", "B", 86, 0.5, -86), fill(t2, "ADA", "A", 86, 0.5, 0)]
    assert [C.posicao_apos(f) for f in C.em_ordem([fill(T0, "ADA", "B", 1, 0.5, -1)] + gira)][1:] == [-86, 0]


def test_posicao_que_some_da_foto_sem_fill_vira_zerou():
    # caso real (CASHCAT, 04/11): vendida e, entre uma foto e outra, a posição some sem fill (mercado encerrado)
    fs = [fill(T0 + 10, "CAT", "A", 1000, 1.0, 0)]
    fotos = [{"t": T0 + 30 * M, "v": 1000, "pos": [["CAT", -1000, 1.0, 3]]},
             {"t": T0 + 90 * M, "v": 1000, "pos": []},
             {"t": T0 + 150 * M, "v": 1000, "pos": []}]
    evs = C.eventos(fs, 0, 60_000, fotos)
    assert [(e["pos"], e.get("obs")) for e in evs] == [(-1000, None), (0.0, "sumiu da conta dela")]
    assert evs[1]["exec"] == T0 + 90 * M + 60_000
    # a cópia zera no último preço conhecido, mesmo velho
    pr = C.Precos()
    pr.juntar("CAT", velas_minuto([1.0, 1.0, 0.9, 0.9, 0.8]))
    sc = C.nova_subconta("w", T0 - M, 1.0)
    log = []
    C.avancar(sc, fs, C.Saldos([{"t": T0 - M, "v": 1000}]), pr, dict(C.TODAS), T0 + 3 * 60 * M, log, evs)
    assert sc["pos"] == {} and log[-1]["obs"] == "sumiu da conta dela" and log[-1]["px"] == pytest.approx(0.8 * (1 + C.ESCORREGA))
    # zerar o que a cópia não tem não é "pulo"
    sc2 = C.nova_subconta("w", T0 + 60 * M, 1.0)
    assert C.avancar(sc2, fs, C.Saldos([]), pr, dict(C.TODAS), T0 + 3 * 60 * M, [], evs) == {}


def test_mercados_de_terceiros_ficam_de_fora():
    fs = [fill(T0 + 10, "xyz:GOLD", "B", 1, 4000, 0), fill(T0 + 20, "para:ANSEM", "B", 1, 1, 0),
          fill(T0 + 30, "ETH", "B", 1, 100, 0), fill(T0 + 40, "@107", "B", 1, 1, 0)]
    assert [e["moeda"] for e in C.eventos(fs, 0, 0)] == ["ETH"]
    assert C.parte_terceiros(fs) == pytest.approx(2 / 3)           # spot não conta
    assert not C.copiavel_mercado("xyz:SP500") and C.copiavel_mercado("kPEPE")


def test_copia_ganha_na_alta_com_o_custo_do_atraso():
    # a carteira compra 2× o saldo em ETH a 100 e vende a 110; o copiador entra e sai 1 min depois
    seq = [100, 100, 101, 102, 104, 106, 108, 110, 110, 110, 110]
    pr = precos_eth(seq)
    fs = [fill(T0 + 10, "ETH", "B", 200, 100, 0), fill(T0 + 7 * M + 10, "ETH", "A", 200, 110, 200)]
    sc = C.nova_subconta("w", T0 - M, 1.0)
    var = dict(C.TODAS)
    C.avancar(sc, fs, C.Saldos([{"t": T0 - M, "v": 10_000}]), pr, var, T0 + 10 * M, [])
    # entrou perto de 100 e saiu perto de 110 com 2×: perto de +20 %, menos taxas e escorregamento
    assert sc["pos"] == {}
    assert 0.17 < sc["patrimonio"] / 1000 - 1 < 0.20
    assert sc["ordens"] == 2 and sc["taxas"] > 0


def test_short_perde_na_alta_e_vira_de_lado():
    pr = precos_eth([100] * 3 + [110] * 4 + [120] * 4)
    fs = [fill(T0 + 10, "ETH", "A", 100, 100, 0),                 # vendido 1× (100 × 100 = saldo)
          fill(T0 + 4 * M, "ETH", "B", 200, 110, -100)]           # vira comprado 1×
    sc = C.nova_subconta("w", T0 - M, 1.0)
    log = []
    C.avancar(sc, fs, C.Saldos([{"t": T0 - M, "v": 10_000}]), pr, dict(C.TODAS), T0 + 10 * M, log)
    q, a = sc["pos"]["ETH"]
    assert q > 0 and a == pytest.approx(110 * (1 + C.ESCORREGA), rel=1e-6)
    assert log[1]["resultado"] < -90                                 # perdeu ~10 % de 1.000 no vendido
    assert sc["patrimonio"] > 1000 * 0.95                            # o comprado recuperou com a alta para 120


def test_teto_corta_a_alavancagem():
    pr = precos_eth([100] * 5)
    fs = [fill(T0 + 10, "ETH", "B", 3000, 100, 0)]                  # a carteira põe 30× o saldo
    sc = C.nova_subconta("w", T0 - M, 1.0)
    C.avancar(sc, fs, C.Saldos([{"t": T0 - M, "v": 10_000}]), pr, dict(C.TODAS), T0 + 4 * M, [])
    q, _ = sc["pos"]["ETH"]
    assert q * 100 == pytest.approx(10 * 1000, rel=0.01)            # no máximo 10× da subconta


def test_parada_de_protecao_da_seletiva():
    pr = precos_eth([100, 100, 100, 95, 90, 85, 80, 80])
    fs = [fill(T0 + 10, "ETH", "B", 200, 100, 0)]                   # 2× comprado e o preço cai 20 %
    var = dict(C.VARIANTES["seletiva"])
    sc = C.nova_subconta("w", T0 - M, 1.0)
    log = []
    for k in range(2, 8):
        C.avancar(sc, fs, C.Saldos([{"t": T0 - M, "v": 10_000}]), pr, var, T0 + k * M, log)
    assert not sc["vivo"] and sc["parou"].startswith("parada")
    assert sc["pos"] == {} and log[-1]["obs"] == "parada de proteção"


def test_liquidada_quando_zera():
    pr = precos_eth([100, 100, 100, 90, 85])
    fs = [fill(T0 + 10, "ETH", "B", 1000, 100, 0)]                  # 10× e cai 15 %
    sc = C.nova_subconta("w", T0 - M, 1.0)
    for k in range(2, 5):
        C.avancar(sc, fs, C.Saldos([{"t": T0 - M, "v": 10_000}]), pr, dict(C.TODAS), T0 + k * M, [])
    assert not sc["vivo"] and sc["parou"].startswith("liquidada") and sc["patrimonio"] == 0


def test_seletiva_filtra_e_reduz_a_alavancagem():
    var = C.VARIANTES["seletiva"]
    rapida = {"geral": {"duracao_mediana_min": 0.1}, "copiavel": {"ok": False, "motivo": "rápido"}}
    lenta = {"geral": {"duracao_mediana_min": 200}, "copiavel": {"ok": True}, "copia": {"alavancagem": {"exposicao_mediana": 8}}}
    assert C.copiavel(rapida, var)[0] is False
    assert C.copiavel(lenta, var) == (True, "")
    assert C.fator_de(lenta, var) == pytest.approx(0.25)
    assert C.fator_de(lenta, C.TODAS) == 1.0


def test_rodar_ponta_a_ponta(tmp_path, monkeypatch):
    """O rodar_copia com um radar de mentira: grava a saída e continua de onde parou na rodada seguinte."""
    w = "0xabc"
    (tmp_path / "saida").mkdir()
    (tmp_path / "config.json").write_text("{}")
    rel = {"carteiras": [{"carteira": w, "desde": "2026-11-03", "geral": {"duracao_mediana_min": 120}, "copiavel": {"ok": True},
                          "copia": {"alavancagem": {"exposicao_mediana": 2}}}]}
    (tmp_path / "saida" / "relatorio.json").write_text(json.dumps(rel))
    inicio = 1793678400000                                             # 03/11/2026 00:00 em Brasília
    pasta = tmp_path / "dados" / "fills" / w
    pasta.mkdir(parents=True)
    t1 = inicio + 3 * 3600_000
    (pasta / "2026-11.jsonl").write_text("\n".join(json.dumps(f) for f in [
        {"t": t1, "c": "ETH", "s": "B", "z": 10, "p": 2000.0, "sp": 0, "id": 1},
        {"t": t1 + 30 * M, "c": "ETH", "s": "A", "z": 10, "p": 2100.0, "sp": 10, "id": 2}]))
    (tmp_path / "dados" / "contas").mkdir(parents=True)
    (tmp_path / "dados" / "contas" / "2026-11.jsonl").write_text(json.dumps({"t": inicio, "a": w, "v": 20000.0, "ntl": 0, "pos": []}))
    monkeypatch.setenv("RADAR_RAIZ", str(tmp_path))
    import importlib
    from radar import armazenamento
    importlib.reload(armazenamento)

    class Api:
        def velas(self, moeda, intervalo, a, b):
            passo = 60_000 if intervalo == "1m" else 300_000
            out, t = [], a // passo * passo
            while t <= b:
                p = 2000.0 if t < t1 + 15 * M else 2100.0
                out.append({"t": t, "T": t + passo - 1, "o": p, "c": p})
                t += passo
            return out

    from lab import rodar_copia
    # um estado velho (sem versão) não vale mais: a cópia é refeita desde o começo
    (tmp_path / "lab" / "dados").mkdir(parents=True)
    (tmp_path / "lab" / "dados" / "copia_estado.json").write_text(json.dumps(
        {"inicio": inicio, "ate": t1, "variantes": {"todas": {"subs": {}, "curva": [[t1, 9.9]], "log": [], "pulos": {}, "fora": {}}}}))
    agora = t1 + 2 * 3600_000
    assert rodar_copia.main(tmp_path, Api(), agora) == 0
    out = json.loads((tmp_path / "saida" / "copia_fiel.json").read_text())
    assert out["refeito"] is True and out["versao"] == rodar_copia.VERSAO
    assert list(out["variantes"]) == list(C.VARIANTES)               # vários copy tradings lado a lado (12/11)
    assert out["variantes"]["habilidade"]["carteiras"] == 0          # a carteira de mentira não tem classe "Habilidade provável"
    assert out["variantes"]["longas"]["carteiras"] == 0              # segura 120 min, abaixo dos 180 da variante
    todas = out["variantes"]["seletiva"]
    assert todas["carteiras"] == 1 and todas["ordens"] == 2
    assert 0.04 < todas["retorno"] < 0.05                             # 1× (2× / exposição típica 2 = fator 1) e +5 %
    # a curva tem a história: uma hora cheia por ponto desde o começo, mais o agora
    horas = [p[0] for p in todas["curva"]]
    base = rodar_copia.ms_do_dia(rodar_copia.INICIO_PADRAO)
    assert horas[:4] == [base + k * 3600_000 for k in (1, 2, 3, 4)] and horas[-1] == out["ate"]
    assert todas["curva"][0][1] == 0 and todas["curva"][-1][1] == todas["retorno"]
    # segunda rodada: nada novo, nada muda (e a curva só ganha as horas novas)
    assert rodar_copia.main(tmp_path, Api(), agora + 3600_000) == 0
    out2 = json.loads((tmp_path / "saida" / "copia_fiel.json").read_text())
    assert out2["refeito"] is False and out2["variantes"]["seletiva"]["ordens"] == 2
    assert len(out2["variantes"]["seletiva"]["curva"]) == len(todas["curva"]) + 2
    importlib.reload(armazenamento)


def test_rodar_deixa_de_fora_quem_opera_em_mercados_de_terceiros(tmp_path, monkeypatch):
    w = "0xdef"
    (tmp_path / "saida").mkdir()
    (tmp_path / "config.json").write_text("{}")
    rel = {"carteiras": [{"carteira": w, "desde": "2026-11-03", "geral": {"duracao_mediana_min": 120}, "copiavel": {"ok": True}}]}
    (tmp_path / "saida" / "relatorio.json").write_text(json.dumps(rel))
    pasta = tmp_path / "dados" / "fills" / w
    pasta.mkdir(parents=True)
    t1 = 1793678400000 + 3 * 3600_000
    fs = [{"t": t1 + k * M, "c": "xyz:GOLD", "s": "B", "z": 1, "p": 4000.0, "sp": k, "id": k} for k in range(9)]
    fs.append({"t": t1, "c": "ETH", "s": "B", "z": 1, "p": 2000.0, "sp": 0, "id": 99})
    (pasta / "2026-11.jsonl").write_text("\n".join(json.dumps(f) for f in fs))
    monkeypatch.setenv("RADAR_RAIZ", str(tmp_path))
    import importlib
    from radar import armazenamento
    importlib.reload(armazenamento)

    class Api:
        def velas(self, moeda, intervalo, a, b):
            return []

    from lab import rodar_copia
    assert rodar_copia.main(tmp_path, Api(), t1 + 3600_000) == 0
    out = json.loads((tmp_path / "saida" / "copia_fiel.json").read_text())
    for nome in ("seletiva",):
        v = out["variantes"][nome]
        assert v["carteiras"] == 0 and "terceiros" in v["fora"][0]["motivo"]
    importlib.reload(armazenamento)


def test_variantes_mudam_uma_coisa_cada():
    base = C.VARIANTES["seletiva"]
    assert C.VARIANTES["rapida"]["atraso_s"] < base["atraso_s"]
    assert C.VARIANTES["agressiva"]["alvo"] > base["alvo"] and C.VARIANTES["agressiva"]["teto"] > base["teto"]
    hab = {"geral": {"duracao_mediana_min": 200}, "copiavel": {"ok": True}, "classe_nome": "Habilidade provável"}
    pro = {**hab, "classe_nome": "Promissora"}
    assert C.copiavel(hab, C.VARIANTES["habilidade"])[0] and not C.copiavel(pro, C.VARIANTES["habilidade"])[0]
    assert C.copiavel(pro, C.VARIANTES["longas"])[0] and not C.copiavel({**pro, "geral": {"duracao_mediana_min": 90}}, C.VARIANTES["longas"])[0]
    assert C.copiavel({"geral": {"duracao_mediana_min": 0.1}}, C.VARIANTES["todas"])[0]
