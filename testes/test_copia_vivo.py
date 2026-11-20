"""O copy trading em tempo real (vivo/copia.py), com uma Hyperliquid de mentira e um relógio na mão."""
import json

import pytest

from lab import copia as C
from vivo import copia as V

W1, W2 = "0xaaa", "0xbbb"


class Limite:
    por_minuto = 1000

    def usado(self):
        return 0


class Api:
    """Devolve o que o teste mandar: preços, contas, livros e fills."""

    def __init__(self):
        self.precos, self.contas, self.livros, self.fills, self.velas_de = {}, {}, {}, {}, {}
        self.fora_do_ar = set()
        self.pedidos = []
        self.lim = Limite()

    def mids(self):
        return {m: str(p) for m, p in self.precos.items()}

    def estado(self, w):
        self.pedidos.append(("estado", w))
        if w in self.fora_do_ar:
            raise RuntimeError("sem resposta")
        saldo, pos = self.contas[w]
        return {"marginSummary": {"accountValue": str(saldo)},
                "assetPositions": [{"position": {"coin": m, "szi": str(q), "positionValue": str(abs(q) * self.precos[m.split(":")[-1]])}}
                                   for m, q in pos.items()]}

    def livro(self, moeda):
        self.pedidos.append(("livro", moeda))
        if moeda in self.livros:
            return self.livros[moeda]
        p = self.precos[moeda]                      # livro fundo, 1 centésimo de 1 % de cada lado
        return {"levels": [[{"px": str(p * 0.9999), "sz": "1000000"}], [{"px": str(p * 1.0001), "sz": "1000000"}]]}

    def velas(self, moeda, intervalo, inicio, fim):
        self.pedidos.append(("velas", moeda))
        return [v for v in self.velas_de.get(moeda, []) if inicio <= v["t"] <= fim]

    def fills_desde(self, w, inicio, fim=None, maximo=10000):
        self.pedidos.append(("fills", w))
        return [f for f in self.fills.get(w, []) if inicio <= f["time"] <= (fim or 10**18)]


def carteira(w, duracao=240, ok=True, exposicao=1.0, classe="Habilidade provável"):
    return {"carteira": w, "apelido": "", "classe_nome": classe, "desde": "2026-11-03",
            "copiavel": {"ok": ok, "motivo": "" if ok else "rápido demais"},
            "geral": {"duracao_mediana_min": duracao}, "copia": {"alavancagem": {"exposicao_mediana": exposicao}}}


class Mundo:
    def __init__(self, tmp_path, carteiras):
        self.raiz, self.t, self.api = tmp_path, 1_000_000_000, Api()
        (tmp_path / "saida").mkdir(exist_ok=True)
        self.radar(carteiras)
        self.api.precos = {"BTC": 100.0, "ETH": 10.0}
        self.robo = self.novo()

    def radar(self, carteiras):
        (self.raiz / "saida" / "relatorio.json").write_text(json.dumps({"carteiras": carteiras, "n": self.t}), encoding="utf-8")

    def novo(self):
        return V.CopiaAoVivo(self.raiz, self.api, lambda: self.t, ler_fills=lambda w: [])

    def volta(self, depois_s=0.0):
        self.t += int(depois_s * 1000)
        self.robo.proximo = 0
        self.robo.passo(self.t)

    def sub(self, variante, w=W1):
        return self.robo.est["variantes"][variante]["subs"][w]


@pytest.fixture
def mundo(tmp_path):
    m = Mundo(tmp_path, [carteira(W1)])
    m.api.contas[W1] = (10_000.0, {})
    return m


def test_livro_compra_come_as_vendas_e_o_que_falta_sai_com_escorregamento():
    livro = {"levels": [[{"px": "99", "sz": "5"}, {"px": "98", "sz": "5"}], [{"px": "101", "sz": "1"}, {"px": "102", "sz": "3"}]]}
    assert V.preco_no_livro(livro, 1, 100) == 101
    assert V.preco_no_livro(livro, 2, 100) == pytest.approx(101.5)
    assert V.preco_no_livro(livro, -10, 100) == pytest.approx(98.5)
    assert V.preco_no_livro(livro, 5, 100) == pytest.approx((101 + 3 * 102 + 102 * (1 + C.ESCORREGA)) / 5)   # livro raso
    assert V.preco_no_livro(None, 1, 100) == pytest.approx(100 * (1 + C.ESCORREGA))
    assert V.preco_no_livro({}, -1, 100) == pytest.approx(100 * (1 - C.ESCORREGA))


def test_conta_so_os_perpetuos_da_hyperliquid():
    conta = {"marginSummary": {"accountValue": "5000"},
             "assetPositions": [{"position": {"coin": "BTC", "szi": "-2", "positionValue": "200"}},
                                {"position": {"coin": "xyz:GOLD", "szi": "1", "positionValue": "50"}},
                                {"position": {"coin": "ETH", "szi": "0", "positionValue": "0"}}]}
    assert V.ler_conta(conta) == (5000.0, {"BTC": -2.0}, {"BTC": 200.0})
    assert V.ler_conta({}) == (0.0, {}, {})


def test_primeira_olhada_so_anota_e_a_mudanca_vira_ordem_na_mesma_volta_em_todas_as_copias(mundo):
    m = mundo
    m.api.contas[W1] = (10_000.0, {"ETH": 100.0})           # ela já tinha ETH antes de a máquina ligar
    m.volta()
    assert all(not m.sub(v)["pos"] for v in V.VARIANTES)     # a cópia começa sem posição
    assert m.robo.est["mudancas"] == [] and m.robo.est["semente"]["de"] == "zero"

    m.api.contas[W1] = (10_000.0, {"ETH": 100.0, "BTC": 30.0})   # comprou BTC: 30 × 100 = 30 % do saldo
    m.volta(3)
    for v in V.VARIANTES:                                    # ao vivo ninguém espera: 60 s e 10 s viram "agora"
        q, medio = m.sub(v)["pos"]["BTC"]
        assert q == pytest.approx(0.3 * 1000 / 100)          # 30 % da subconta de US$ 1.000 (exposição dela 1× → fator 1)
        assert medio == pytest.approx(100.01)                # preço do livro, não o do meio
        assert "ETH" not in m.sub(v)["pos"]                  # o que ela já tinha não entra: só o que mudou
    assert m.sub("seletiva") == m.sub("rapida")              # ao vivo são o mesmo robô
    assert V.VARIANTES["seletiva"]["atraso_s"] == 0 and V.VARIANTES["seletiva"]["atraso_normal_s"] == 60
    ordem = m.robo.est["variantes"]["rapida"]["log"][-1]
    assert ordem["lado"] == "compra" and ordem["espera_ms"] == 0 and ordem["mud"] == 1


def test_ela_fecha_e_a_copia_zera_com_o_lucro_e_a_taxa(mundo):
    m = mundo
    m.volta()
    m.api.contas[W1] = (10_000.0, {"BTC": -50.0})            # vendida em 50 % do saldo
    m.volta(3)
    sc = m.sub("seletiva")
    assert sc["pos"]["BTC"][0] == pytest.approx(-5.0)
    m.api.precos["BTC"] = 90.0
    m.api.contas[W1] = (10_500.0, {})
    m.volta(3)
    assert sc["pos"] == {} and sc["ordens"] == 2
    ganho = 5 * (100 * 0.9999 - 90 * 1.0001)
    assert sc["patrimonio"] == pytest.approx(1000 + ganho - sc["taxas"], abs=0.01)
    assert sc["taxas"] == pytest.approx((5 * 99.99 + 5 * 90.009) * C.TAXA)


def test_fator_teto_e_ordem_pequena(tmp_path):
    m = Mundo(tmp_path, [carteira(W1, exposicao=8.0)])       # ela opera a 8× → a cópia leva para 2× (fator 0,25)
    m.api.contas[W1] = (1_000.0, {})
    m.volta()
    assert m.sub("seletiva")["fator"] == 0.25 and m.sub("agressiva")["fator"] == 0.5 and m.sub("todas")["fator"] == 1.0
    m.api.contas[W1] = (1_000.0, {"BTC": 200.0})             # 20× o saldo dela
    m.volta(3)
    assert m.sub("seletiva")["pos"]["BTC"][0] * 100 == pytest.approx(3000)       # 20 × 0,25 = 5×, cortado no teto de 3×
    assert m.sub("agressiva")["pos"]["BTC"][0] * 100 == pytest.approx(6000)      # 20 × 0,5 = 10×, cortado no teto de 6×
    m.api.contas[W1] = (1_000.0, {"BTC": 200.0, "ETH": 0.5})                     # US$ 5 em ETH: e o teto já está cheio
    m.volta(3)
    assert "ETH" not in m.sub("seletiva")["pos"]
    assert m.robo.est["variantes"]["seletiva"]["pulos"] == {"ordem pequena": 1}


def test_parada_de_protecao_fecha_tudo_e_a_copia_para(mundo):
    m = mundo
    m.volta()
    m.api.contas[W1] = (1_000.0, {"BTC": 30.0})              # 3× comprada
    m.volta(3)
    assert m.sub("seletiva")["vivo"]
    m.api.precos["BTC"] = 91.0                               # −9 % a 3× = −27 %: passou da parada de 25 %
    m.volta(3)
    sc = m.sub("seletiva")
    assert not sc["vivo"] and sc["pos"] == {} and "parada" in sc["parou"]
    assert 700 < sc["patrimonio"] < 750
    assert m.sub("todas")["vivo"] and W1 in m.robo.carteiras()   # a cópia sem parada segue viva
    m.api.contas[W1] = (1_000.0, {"BTC": 10.0})
    m.volta(3)
    assert sc["ordens"] == 2                                 # a parada não opera mais


def test_quem_entra_em_cada_copia_e_quem_sai_do_radar(tmp_path):
    m = Mundo(tmp_path, [carteira(W1), carteira(W2, duracao=2, ok=False, classe="Sorte")])
    m.api.contas = {W1: (1_000.0, {}), W2: (1_000.0, {})}
    m.volta()
    vs = m.robo.est["variantes"]
    assert set(vs["seletiva"]["subs"]) == {W1} and set(vs["todas"]["subs"]) == {W1, W2}
    assert "curto demais" in vs["seletiva"]["fora"][W2]
    m.api.contas[W1] = (1_000.0, {"BTC": 10.0})
    m.volta(3)
    m.radar([carteira(W2, duracao=2, ok=False, classe="Sorte")])   # W1 saiu do radar
    m.volta(3)
    sc = m.sub("seletiva")
    assert not sc["vivo"] and sc["parou"] == "saiu do radar" and sc["pos"] == {}
    assert m.robo.carteiras() == [W2]
    m.api.pedidos.clear()
    m.volta(3)
    assert ("estado", W1) not in m.api.pedidos               # não gasta consulta com quem ninguém segue


def test_carteira_sem_resposta_nao_atrapalha_as_outras(tmp_path):
    m = Mundo(tmp_path, [carteira(W1), carteira(W2)])
    m.api.contas = {W1: (1_000.0, {}), W2: (1_000.0, {})}
    m.volta()
    m.api.fora_do_ar = {W1}
    m.api.contas[W2] = (1_000.0, {"ETH": 50.0})
    m.volta(3)
    assert m.sub("seletiva", W2)["pos"]["ETH"][0] == pytest.approx(50.0)
    assert len(m.robo.falhas) == 1
    m.api.fora_do_ar = set()
    m.api.contas[W1] = (1_000.0, {"BTC": 5.0})               # mudou enquanto não respondia: é vista quando volta
    m.volta(3)
    assert m.sub("seletiva", W1)["pos"]["BTC"][0] == pytest.approx(5.0)


def test_estado_guardado_o_motor_reinicia_e_ve_o_que_mudou_enquanto_estava_parado(mundo):
    m = mundo
    m.volta()
    m.api.contas[W1] = (1_000.0, {"BTC": 10.0})
    m.volta(3)
    m.robo.fechar()
    guardado = json.loads((m.raiz / "vivo" / "dados" / "copia_estado.json").read_text(encoding="utf-8"))
    assert guardado["versao"] == V.VERSAO and guardado["vistas"][W1]["pos"] == {"BTC": 10.0}
    m.api.contas[W1] = (1_000.0, {"BTC": 20.0})              # ela dobrou com o motor desligado
    m.robo = m.novo()
    m.volta(120)
    assert m.sub("seletiva")["pos"]["BTC"][0] == pytest.approx(20.0, rel=1e-3)
    assert m.sub("seletiva")["ordens"] == 2
    assert m.robo.est["semente"]["t"] == guardado["semente"]["t"]              # não parte de novo


def subconta_lab(w, ult, pos=None, vivo=True, colateral=1100.0):
    sc = C.nova_subconta(w, 1, 1.0)
    sc.update(colateral=colateral, patrimonio=round(colateral, 2), pico=max(1000.0, colateral), pos=pos or {}, ult=ult,
              vivo=vivo, ordens=7, taxas=3.0, parou=None if vivo else "parada: caiu 25 % do pico")
    return sc


def test_parte_do_estado_do_laboratorio_e_acerta_o_que_ela_fez_no_intervalo(tmp_path):
    """O gêmeo começa com as mesmas subcontas, saldos e posições do teste de hora em hora. O que a carteira operou
    depois da última ordem que o laboratório copiou é acertado na primeira olhada."""
    m = Mundo(tmp_path, [carteira(W1), carteira(W2)])
    ate = m.t - 20 * 60_000                                  # a última rodada do laboratório foi há 20 minutos
    lab = {"versao": 4, "inicio": 111, "ate": ate, "variantes": {}}
    for nome in C.VARIANTES:
        lab["variantes"][nome] = {"subs": {W1: subconta_lab(W1, ate - 3_600_000, {"BTC": [5.0, 90.0]}),
                                           W2: subconta_lab(W2, ate - 7_200_000, {"ETH": [-20.0, 11.0]}, vivo=nome == "todas", colateral=700.0)},
                                  "curva": [[ate - 3_600_000, 0.01], [ate, 0.02]], "log": [{"t": ate - 3_600_000, "w": W1, "moeda": "BTC", "lado": "compra", "valor": 450, "px": 90, "realizado": 0.0, "resultado": -0.2}],
                                  "pulos": {"ordem pequena": 2}, "fora": {}}
    (tmp_path / "lab" / "dados").mkdir(parents=True)
    (tmp_path / "lab" / "dados" / "copia_estado.json").write_text(json.dumps(lab), encoding="utf-8")
    m.robo = m.novo()
    # desde a última rodada do laboratório: W1 vendeu metade do BTC (fill novo) e mexeu em ETH, que a cópia nem tinha;
    # W2 não fez nada
    m.api.fills[W1] = [{"coin": "BTC", "time": ate - 3_600_000, "px": "90", "sz": "50", "side": "B"},      # já copiado
                       {"coin": "BTC", "time": ate + 60_000, "px": "99", "sz": "25", "side": "A"},
                       {"coin": "ETH", "time": ate + 90_000, "px": "10", "sz": "100", "side": "B"},
                       {"coin": "xyz:GOLD", "time": ate + 95_000, "px": "1", "sz": "1", "side": "B"}]
    m.api.contas = {W1: (10_000.0, {"BTC": 25.0, "ETH": 100.0}), W2: (5_000.0, {"ETH": -300.0})}
    m.volta()
    est = m.robo.est
    assert est["semente"] == {"t": m.t, "ate": ate, "de": "laboratório", "retorno": {n: pytest.approx(-0.1) for n in C.VARIANTES}}
    assert est["inicio"] == 111 and est["a_acertar"] == []
    sc = m.sub("seletiva")
    assert sc["ordens"] == 9 and sc["taxas"] > 3.0           # as 7 do laboratório e as 2 do acerto
    pat = 1100 + 5 * (100 - 90)                              # o saldo que veio do laboratório, com o BTC a 100
    assert sc["pos"]["BTC"][0] == pytest.approx(0.25 * pat / 100, rel=1e-3)     # ela ficou com 25 % do saldo em BTC
    assert sc["pos"]["ETH"][0] == pytest.approx(0.10 * pat / 10, rel=2e-2)      # e 10 % em ETH
    assert m.sub("seletiva", W2) == lab["variantes"]["seletiva"]["subs"][W2]    # parada no laboratório: fica parada
    todas = m.sub("todas", W2)
    assert todas["vivo"] and todas["pos"]["ETH"][0] == -20.0 and todas["ordens"] == 7   # W2 não operou: a posição fica
    assert todas["patrimonio"] == pytest.approx(700 - 20 * (10 - 11), abs=0.01)
    v = est["variantes"]["seletiva"]
    assert v["curva"][:2] == [[ate - 3_600_000, 0.01], [ate, 0.02]] and v["curva"][-1][0] == m.t
    assert len(v["log"]) == 3 and v["pulos"] == {"ordem pequena": 2}
    assert [("fills", W1), ("fills", W2)] == [p for p in m.api.pedidos if p[0] == "fills"]
    assert not any(mu.get("atraso_ms") for mu in est["mudancas"]) and est["conferir"] == []   # o acerto não entra nas medidas
    # dali em diante é a cópia normal: W2 dobra a venda e o "todas" acompanha
    m.api.pedidos.clear()
    m.api.contas[W2] = (5_000.0, {"ETH": -600.0})
    m.volta(3)
    assert todas["ordens"] == 8 and todas["pos"]["ETH"][0] < -20.0
    assert not [p for p in m.api.pedidos if p[0] == "fills"]


def test_na_partida_acerta_poucas_carteiras_por_volta_e_insiste_se_a_consulta_falha(tmp_path):
    ws = [f"0x{i:03d}" for i in range(5)]
    m = Mundo(tmp_path, [carteira(w) for w in ws])
    ate = m.t - 60_000
    lab = {"versao": 4, "inicio": 1, "ate": ate, "variantes": {n: {"subs": {w: subconta_lab(w, ate - 1000) for w in ws}, "curva": [], "log": [], "pulos": {}, "fora": {}} for n in C.VARIANTES}}
    (tmp_path / "lab" / "dados").mkdir(parents=True)
    (tmp_path / "lab" / "dados" / "copia_estado.json").write_text(json.dumps(lab), encoding="utf-8")
    m.robo = m.novo()
    m.api.contas = {w: (1_000.0, {}) for w in ws}
    falha = {ws[0]}
    original = m.api.fills_desde

    def fills(w, *a, **k):
        if w in falha:
            m.api.pedidos.append(("fills", w))
            raise RuntimeError("sem resposta")
        return original(w, *a, **k)
    m.api.fills_desde = fills
    m.volta()
    assert sorted(m.robo.est["vistas"]) == ws[1:3] and m.robo.est["a_acertar"] == [ws[0], ws[3], ws[4]]
    m.volta(3)
    assert sorted(m.robo.est["vistas"]) == ws[1:5]
    m.volta(3)                                               # terceira falha: segue sem o acerto, para não ficar cega
    assert sorted(m.robo.est["vistas"]) == ws and m.robo.est["a_acertar"] == []


def test_mede_o_atraso_de_deteccao_e_o_custo_do_atraso(mundo):
    m = mundo
    m.volta()
    t_fill = m.t + 1_200
    m.api.fills[W1] = [{"coin": "BTC", "time": t_fill, "px": "100.0", "sz": "20", "side": "B"},
                       {"coin": "BTC", "time": t_fill, "px": "100.2", "sz": "20", "side": "B"},
                       {"coin": "ETH", "time": t_fill, "px": "10", "sz": "1", "side": "B"}]
    m.api.contas[W1] = (10_000.0, {"BTC": 40.0})
    m.volta(3)                                               # vê a mudança 1,8 s depois do fill
    assert ("fills", W1) not in m.api.pedidos                # espera o fill aparecer na API
    m.volta(10)
    mud = m.robo.est["mudancas"][0]
    assert mud["atraso_ms"] == 1_800 and mud["px_dela"] == pytest.approx(100.1)
    saida = m.robo.montar_saida(m.t)
    assert saida["maquina"]["atraso_deteccao_ms"] == {"mediana": 1800, "pior": 1800, "medidas": 1}
    assert saida["variantes"]["seletiva"]["custo_do_atraso_bps"] == {"mediana": pytest.approx(-9.0, abs=0.1), "ordens": 1}
    m.api.pedidos.clear()
    m.volta(3)
    assert ("fills", W1) not in m.api.pedidos                # cada mudança é medida uma vez só


DIA = 86_400_000


def test_diario_das_medidas_um_resumo_por_dia_que_sobrevive_ao_estado_zerado(mundo):
    m = mundo
    arq = m.raiz / "vivo" / "dados" / "medidas.json"
    m.volta()
    t_fill = m.t + 1_200
    m.api.fills[W1] = [{"coin": "BTC", "time": t_fill, "px": "100.1", "sz": "40", "side": "B"}]
    m.api.contas[W1] = (10_000.0, {"BTC": 40.0})
    m.volta(3)
    m.volta(10)                                              # mede: 1,8 s de atraso; a cópia comprou a 100,01 e ela a 100,1
    hoje = m.robo.medidas.d["hoje"]
    assert hoje["mudancas"] == 1 and hoje["atraso_ms"] == [1800] and hoje["sem_fill"] == 0
    assert hoje["custo_bps"] == [pytest.approx(-9.0, abs=0.1)] and hoje["valor"] > 0     # uma medida por mudança, não por cópia
    m.volta(3)
    assert m.robo.medidas.d["hoje"]["atraso_ms"] == [1800]   # cada mudança entra uma vez só
    m.robo.gravar(m.t)
    dia1 = V.dia_de(m.t)
    assert json.loads(arq.read_text())["hoje"]["dia"] == dia1
    assert m.robo.montar_saida(m.t)["maquina"]["diario"]["hoje"]["atraso_ms"]["mediana"] == 1800

    # no dia seguinte: uma mudança sem ordem dela (ajuste da bolsa). O dia que acabou vira resumo e as cruas saem
    m.t += DIA
    m.api.contas[W1] = (10_000.0, {"BTC": 30.0})
    m.volta(3)
    m.volta(10)
    m.robo.gravar(m.t)
    d = json.loads(arq.read_text())
    assert d["dias"][dia1]["valor_medio"] > 100              # o tamanho médio da ordem da cópia (US$)
    assert d["dias"][dia1] == {"mudancas": 1, "sem_fill": 0, "valor_medio": d["dias"][dia1]["valor_medio"],
                               "atraso_ms": {"n": 1, "mediana": 1800, "media": 1800, "p90": 1800, "pior": 1800},
                               "custo_bps": {"n": 1, "mediana": pytest.approx(-9.0, abs=0.1), "media": pytest.approx(-9.0, abs=0.1),
                                             "p90": pytest.approx(-9.0, abs=0.1), "pior": pytest.approx(-9.0, abs=0.1)}}
    assert d["hoje"]["dia"] == V.dia_de(m.t) and d["hoje"]["mudancas"] == 1 and d["hoje"]["sem_fill"] == 1
    assert d["hoje"]["atraso_ms"] == [] and d["hoje"]["custo_bps"] == []

    # o estado do robô é zerado (regras novas, máquina refeita): o diário continua de onde estava
    m.robo.arq_estado.unlink()
    novo = m.novo()
    assert novo.est.get("mudancas") == [] and novo.medidas.d["dias"][dia1]["atraso_ms"]["n"] == 1
    assert novo.medidas.resumo()["desde"] == dia1 and novo.medidas.resumo()["dias"] == 1


def test_diario_novo_comeca_com_as_medidas_que_o_estado_ainda_guarda(mundo):
    m = mundo
    m.volta()
    m.api.fills[W1] = [{"coin": "BTC", "time": m.t + 1_200, "px": "100.1", "sz": "40", "side": "B"}]
    m.api.contas[W1] = (10_000.0, {"BTC": 40.0})
    m.volta(3)
    m.volta(10)
    m.api.contas[W1] = (10_000.0, {"BTC": 30.0})             # outra mudança, ainda na fila para medir
    m.volta(3)
    m.robo.gravar(m.t)
    (m.raiz / "vivo" / "dados" / "medidas.json").unlink()    # como na máquina, que já media antes de o diário existir
    novo = m.novo()
    hoje = novo.medidas.d["hoje"]
    assert hoje["mudancas"] == 2 and hoje["atraso_ms"] == [1800] and hoje["custo_bps"] == [pytest.approx(-9.0, abs=0.1)]
    novo.gravar(m.t)
    assert m.novo().medidas.d["hoje"]["mudancas"] == 2       # com o arquivo no lugar, não entra de novo


def test_diario_com_defeito_nao_derruba_a_copia(mundo):
    m = mundo
    m.volta()

    def quebra(*a, **k):
        raise RuntimeError("disco cheio")
    m.robo.medidas.mudanca = m.robo.medidas.medida = m.robo.medidas.gravar = quebra
    m.api.fills[W1] = [{"coin": "BTC", "time": m.t + 1_200, "px": "100.1", "sz": "40", "side": "B"}]
    m.api.contas[W1] = (10_000.0, {"BTC": 40.0})
    m.volta(3)
    m.volta(10)
    m.robo.gravar(m.t)
    assert m.sub("seletiva")["pos"]["BTC"][0] > 0 and m.robo.arq_estado.exists()     # copiou e guardou o estado assim mesmo


def test_diario_medida_atrasada_de_antes_da_meia_noite_nao_reabre_o_dia_fechado(tmp_path):
    d = V.Medidas(tmp_path / "medidas.json")
    t = 5 * DIA + 1000
    d.mudanca(t - 2000)                                      # 23:59:59 do dia 5
    d.medida(t - 2000, 900, 1.5, 300.0)
    d.mudanca(t)                                             # 00:00:01 do dia 6
    d.medida(t - 2000, 1100, 2.5, 500.0)                     # medida, já no dia 6, de uma mudança do dia 5
    assert sorted(d.d["dias"]) == [V.dia_de(t - 2000)] and d.d["dias"][V.dia_de(t - 2000)]["atraso_ms"]["n"] == 1
    assert d.d["hoje"]["dia"] == V.dia_de(t) and d.d["hoje"]["atraso_ms"] == [1100] and d.d["hoje"]["mudancas"] == 1
    d.gravar()
    assert V.Medidas(tmp_path / "medidas.json").d == d.d     # relê igual
    (tmp_path / "medidas.json").write_text("{quebrado")
    assert V.Medidas(tmp_path / "medidas.json").d["dias"] == {}      # arquivo estragado: começa de novo, sem travar...
    guardados = list(tmp_path.glob("medidas-guardado-*.json"))
    assert len(guardados) == 1 and guardados[0].read_text() == "{quebrado"   # ...e o estragado fica guardado ao lado


def test_resumir():
    assert V.resumir([]) is None
    assert V.resumir(list(range(1, 11))) == {"n": 10, "mediana": 5.5, "media": 5.5, "p90": 10, "pior": 10}


def test_saida_no_formato_do_laboratorio_e_resumo(mundo):
    m = mundo
    m.volta()
    m.api.contas[W1] = (1_000.0, {"BTC": 10.0})
    m.volta(3)
    m.robo.gravar(m.t)
    s = json.loads((m.raiz / "vivo" / "gemeo" / "saida" / "copia_fiel.json").read_text(encoding="utf-8"))
    assert s["ao_vivo"] and "simulação" in s["modo"] and set(s["variantes"]) == set(C.VARIANTES)
    v = s["variantes"]["seletiva"]
    assert v["nome"] == C.VARIANTES["seletiva"]["nome"] and v["regras"]["atraso_s"] == 0 and v["regras"]["teto"] == 3.0
    assert v["carteiras"] == 1 and v["ordens"] == 1 and v["curva"] and v["capital"] == 1000
    assert v["subcontas"][0]["abertas"][0]["moeda"] == "BTC" and v["ordens_recentes"][0]["lado"] == "compra"
    assert s["semente"]["de"] == "zero" and s["maquina"]["carteiras_olhadas"] == 1
    r = m.robo.resumo(m.t)
    assert r["carteiras"] == 1 and r["mudancas_1h"] == 1 and set(r["retorno"]) == set(C.VARIANTES)
    assert r["volta_s"] == 3.0 and r["partiu"] == s["semente"]["t"]


def test_curva_um_ponto_por_minuto_nas_ultimas_horas_e_um_a_cada_dez_minutos_antes():
    agora = 100 * V.HORA
    velha = [[agora - 5 * V.HORA + i * 60_000, i] for i in range(31)]            # 31 pontos de minuto em minuto, há 5 h
    nova = [[agora - 10 * 60_000 + i * 60_000, i] for i in range(10)]
    c = V.afinar(velha + nova, agora)
    assert [p[1] for p in c[:4]] == [0, 10, 20, 30] and c[4:] == nova
    assert V.afinar(c, agora) == c


def test_sem_ordem_nova_a_comparacao_da_o_mesmo_que_o_laboratorio_no_preco_da_vela(mundo):
    """O gêmeo fotografa as subcontas; quando o laboratório publica a rodada (ate), ele avalia a foto daquele instante
    nas velas de 1 minuto, como o laboratório. Com as mesmas posições, dá o mesmo número."""
    m = mundo
    m.volta()
    m.api.contas[W1] = (1_000.0, {"BTC": 10.0, "ETH": -20.0})
    m.volta(3)
    sc = m.sub("seletiva")
    q_btc, a_btc = sc["pos"]["BTC"]
    q_eth, a_eth = sc["pos"]["ETH"]
    col = sc["colateral"]
    m.api.precos.update(BTC=103.0, ETH=9.0)                 # o preço do instante (mid) anda...
    m.volta(180)
    ate = (m.t // 60_000) * 60_000 - 60_000                  # ...e o laboratório fecha a rodada um minuto antes
    m.api.velas_de = {"BTC": [{"t": ate, "T": ate + 60_000, "o": "102", "c": "102.5"}],
                      "ETH": [{"t": ate, "T": ate + 60_000, "o": "9.5", "c": "9.4"}]}
    (m.raiz / "saida" / "copia_fiel.json").write_text(json.dumps({"ate": ate}), encoding="utf-8")
    for _ in range(3):                                       # uma moeda por volta
        m.volta(3)
    esperado = (col + q_btc * (102 - a_btc) + q_eth * (9.5 - a_eth)) / 1000 - 1
    comp = m.robo.est["comparacoes"][str(ate)]
    assert comp["seletiva"] == pytest.approx(esperado, abs=1e-5)
    assert comp["seletiva"] != pytest.approx(sc["patrimonio"] / 1000 - 1, abs=1e-4)   # a curva usa o mid: outro número
    assert [p for p in m.api.pedidos if p[0] == "velas"] == [("velas", "BTC"), ("velas", "ETH")]
    m.robo.gravar(m.t)
    s = json.loads((m.raiz / "vivo" / "gemeo" / "saida" / "copia_fiel.json").read_text(encoding="utf-8"))
    assert s["comparacoes"][str(ate)]["seletiva"] == comp["seletiva"]
    m.api.pedidos.clear()
    m.volta(3)
    assert not [p for p in m.api.pedidos if p[0] == "velas"]  # cada rodada é medida uma vez


def test_foto_do_instante_certo_e_sem_foto_antiga_nao_compara(mundo):
    m = mundo
    m.volta()
    t_antes = m.t
    m.api.contas[W1] = (1_000.0, {"BTC": 10.0})
    m.volta(3)
    assert m.robo.foto_em("seletiva", t_antes)[3] == {}      # antes da compra: nada aberto
    assert m.robo.foto_em("seletiva", m.t)[3]["BTC"][0] > 0
    (m.raiz / "saida" / "copia_fiel.json").write_text(json.dumps({"ate": t_antes - 3_600_000}), encoding="utf-8")
    m.volta(3)
    assert m.robo.pendente is None and m.robo.est["comparacoes"] == {}   # o gêmeo nem existia naquela hora
