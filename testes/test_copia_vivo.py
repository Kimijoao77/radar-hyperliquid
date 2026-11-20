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


def test_primeira_olhada_so_anota_e_a_mudanca_vira_ordem_no_atraso_de_cada_copia(mundo):
    m = mundo
    m.api.contas[W1] = (10_000.0, {"ETH": 100.0})           # ela já tinha ETH antes de a máquina ligar
    m.volta()
    assert all(not m.sub(v)["pos"] for v in V.VARIANTES)     # a cópia começa sem posição
    assert m.robo.est["mudancas"] == []

    m.api.contas[W1] = (10_000.0, {"ETH": 100.0, "BTC": 30.0})   # comprou BTC: 30 × 100 = 30 % do saldo
    m.volta(3)
    q, medio = m.sub("imediata")["pos"]["BTC"]
    assert q == pytest.approx(0.3 * 1000 / 100)              # 30 % da subconta de US$ 1.000 (exposição dela 1× → fator 1)
    assert medio == pytest.approx(100.01)                    # preço do livro, não o do meio
    assert "ETH" not in m.sub("imediata")["pos"]             # o que ela já tinha não entra: só o que mudou
    assert "BTC" not in m.sub("rapida")["pos"] and "BTC" not in m.sub("seletiva")["pos"]

    m.api.precos["BTC"] = 101.0
    m.volta(10)                                              # 10 s depois: a vez da cópia rápida, no preço de agora
    assert m.sub("rapida")["pos"]["BTC"][1] == pytest.approx(101.0 * 1.0001)
    assert "BTC" not in m.sub("seletiva")["pos"]
    m.api.precos["BTC"] = 103.0
    m.volta(50)                                              # 1 min depois da mudança
    assert m.sub("seletiva")["pos"]["BTC"][1] == pytest.approx(103.0 * 1.0001)
    assert m.sub("agressiva")["pos"]["BTC"][0] == pytest.approx(0.3 * 1000 / 103)   # fator 1 (o teto dela é que é maior)
    assert m.sub("imediata")["patrimonio"] > m.sub("rapida")["patrimonio"] > m.sub("seletiva")["patrimonio"]
    ordem = m.robo.est["variantes"]["rapida"]["log"][-1]
    assert ordem["lado"] == "compra" and ordem["espera_ms"] == 10_000 and ordem["mud"] == 1


def test_ela_fecha_e_a_copia_zera_com_o_lucro_e_a_taxa(mundo):
    m = mundo
    m.volta()
    m.api.contas[W1] = (10_000.0, {"BTC": -50.0})            # vendida em 50 % do saldo
    m.volta(3)
    sc = m.sub("imediata")
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
    assert m.sub("imediata")["pos"]["BTC"][0] * 100 == pytest.approx(3000)       # 20 × 0,25 = 5×, cortado no teto de 3×
    m.api.contas[W1] = (1_000.0, {"BTC": 200.0, "ETH": 0.5})                     # US$ 5 em ETH: e o teto já está cheio
    m.volta(3)
    assert "ETH" not in m.sub("imediata")["pos"]
    assert m.robo.est["variantes"]["imediata"]["pulos"] == {"ordem pequena": 1}


def test_parada_de_protecao_fecha_tudo_e_a_copia_para(mundo):
    m = mundo
    m.volta()
    m.api.contas[W1] = (1_000.0, {"BTC": 30.0})              # 3× comprada
    m.volta(3)
    assert m.sub("imediata")["vivo"]
    m.api.precos["BTC"] = 91.0                               # −9 % a 3× = −27 %: passou da parada de 25 %
    m.volta(3)
    sc = m.sub("imediata")
    assert not sc["vivo"] and sc["pos"] == {} and "parada" in sc["parou"]
    assert 700 < sc["patrimonio"] < 750
    assert W1 in m.robo.carteiras()                          # as cópias de 60 s ainda nem entraram: seguem vivas
    m.api.contas[W1] = (1_000.0, {"BTC": 10.0})
    m.volta(3)
    assert sc["ordens"] == 2                                 # a parada não opera mais


def test_quem_entra_em_cada_copia_e_quem_sai_do_radar(tmp_path):
    m = Mundo(tmp_path, [carteira(W1), carteira(W2, duracao=2, ok=False, classe="Sorte")])
    m.api.contas = {W1: (1_000.0, {}), W2: (1_000.0, {})}
    m.volta()
    vs = m.robo.est["variantes"]
    assert set(vs["seletiva"]["subs"]) == {W1} and set(vs["todas"]["subs"]) == {W1, W2}
    assert "curto demais" in vs["imediata"]["fora"][W2]
    m.api.contas[W1] = (1_000.0, {"BTC": 10.0})
    m.volta(3)
    m.radar([carteira(W2, duracao=2, ok=False, classe="Sorte")])   # W1 saiu do radar
    m.volta(3)
    sc = m.sub("imediata")
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
    assert m.sub("imediata", W2)["pos"]["ETH"][0] == pytest.approx(50.0)
    assert len(m.robo.falhas) == 1
    m.api.fora_do_ar = set()
    m.api.contas[W1] = (1_000.0, {"BTC": 5.0})               # mudou enquanto não respondia: é vista quando volta
    m.volta(3)
    assert m.sub("imediata", W1)["pos"]["BTC"][0] == pytest.approx(5.0)


def test_estado_guardado_o_motor_reinicia_e_ve_o_que_mudou_enquanto_estava_parado(mundo):
    m = mundo
    m.volta()
    m.api.contas[W1] = (1_000.0, {"BTC": 10.0})
    m.volta(3)
    m.robo.fechar()
    guardado = json.loads((m.raiz / "vivo" / "dados" / "copia_estado.json").read_text(encoding="utf-8"))
    assert guardado["variantes"]["seletiva"]["fila"][0]["moeda"] == "BTC"      # a ordem de 60 s ficou na fila
    m.api.contas[W1] = (1_000.0, {"BTC": 20.0})              # ela dobrou com o motor desligado
    m.robo = m.novo()
    m.volta(120)
    assert m.sub("imediata")["pos"]["BTC"][0] == pytest.approx(20.0, rel=1e-3)
    assert m.sub("seletiva")["pos"]["BTC"][0] == pytest.approx(10.0)           # executou a que estava na fila
    assert m.sub("imediata")["ordens"] == 2


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
    m.api.precos["BTC"] = 100.6
    m.volta(10)
    mud = m.robo.est["mudancas"][0]
    assert mud["atraso_ms"] == 1_800 and mud["px_dela"] == pytest.approx(100.1)
    saida = m.robo.montar_saida(m.t)
    assert saida["maquina"]["atraso_deteccao_ms"] == {"mediana": 1800, "pior": 1800, "medidas": 1}
    assert saida["variantes"]["imediata"]["custo_do_atraso_bps"] == {"mediana": pytest.approx(-9.0, abs=0.1), "ordens": 1}
    assert saida["variantes"]["rapida"]["custo_do_atraso_bps"]["mediana"] == pytest.approx(51.0, abs=0.2)
    assert saida["variantes"]["seletiva"]["custo_do_atraso_bps"] is None and saida["variantes"]["seletiva"]["na_fila"] == 1
    m.api.pedidos.clear()
    m.volta(3)
    assert ("fills", W1) not in m.api.pedidos                # cada mudança é medida uma vez só


def test_saida_e_resumo(mundo):
    m = mundo
    m.volta()
    m.api.contas[W1] = (1_000.0, {"BTC": 10.0})
    m.volta(3)
    m.robo.gravar(m.t)
    s = json.loads((m.raiz / "saida" / "copia_ao_vivo.json").read_text(encoding="utf-8"))
    assert s["ao_vivo"] and "simulação" in s["modo"] and set(s["variantes"]) == set(V.VARIANTES)
    im = s["variantes"]["imediata"]
    assert im["regras"]["atraso_s"] == 0 and im["carteiras"] == 1 and im["ordens"] == 1 and im["curva"]
    assert im["subcontas"][0]["abertas"][0]["moeda"] == "BTC" and im["ordens_recentes"][0]["lado"] == "compra"
    r = m.robo.resumo(m.t)
    assert r["carteiras"] == 1 and r["mudancas_1h"] == 1 and set(r["retorno"]) == set(V.VARIANTES)
    assert r["volta_s"] == 3.0
