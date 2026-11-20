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
        self.precos, self.contas, self.livros, self.fills = {}, {}, {}, {}
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
