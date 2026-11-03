"""Testes com dados simulados (o radar real só fala com a Hyperliquid no GitHub Actions).

Rodar: python -m pytest -q testes
"""
import importlib
import json
import random

import pytest

from radar.metricas import benjamini_hochberg, numeros, p_bootstrap
from radar.trades import montar

H = 3600 * 1000


def fill(t, coin, side, px, sz, sp, pnl=0.0, fee=0.0, crossed=True, oid=1, tid=None):
    return {"t": t, "c": coin, "s": side, "p": px, "z": sz, "sp": sp, "pnl": pnl, "f": fee,
            "x": 1 if crossed else 0, "o": oid, "id": tid if tid is not None else t}


# ---------------- operações ----------------
def test_operacao_simples_long():
    ops = montar([fill(0, "BTC", "B", 100, 1, 0, fee=0.1), fill(H, "BTC", "A", 110, 1, 1, pnl=10, fee=0.1)])
    assert len(ops) == 1
    o = ops[0]
    assert o.lado == "long" and o.fechada and not o.parcial
    assert o.resultado == pytest.approx(9.8)
    assert o.duracao_min == pytest.approx(60)
    assert o.retorno == pytest.approx(9.8 / 100)


def test_entradas_e_saidas_parciais_e_preco_medio():
    fs = [fill(0, "ETH", "B", 100, 1, 0, oid=1), fill(1, "ETH", "B", 90, 1, 1, oid=2),  # média para baixo
          fill(2, "ETH", "A", 98, 1, 2, pnl=3), fill(3, "ETH", "A", 99, 1, 1, pnl=4)]
    o = montar(fs)[0]
    assert o.fechada and o.pos_max == 2 and len(o.ordens_entrada) == 2
    assert o.medio_prejuizo == 1
    assert o.pnl == pytest.approx(7)


def test_virada_de_lado_fecha_e_abre():
    fs = [fill(0, "SOL", "B", 10, 2, 0), fill(1, "SOL", "A", 11, 5, 2, pnl=2, fee=0.5), fill(2, "SOL", "B", 10, 3, -3, pnl=3)]
    ops = montar(fs)
    assert [o.lado for o in ops] == ["long", "short"]
    assert ops[0].fechada and ops[1].fechada
    assert ops[0].pnl == pytest.approx(2 * 2 / 5) and ops[0].taxas == pytest.approx(0.2)
    assert ops[1].taxas == pytest.approx(0.3) and ops[1].pnl == pytest.approx(3)


def test_dados_comecam_no_meio_da_posicao():
    ops = montar([fill(0, "BTC", "A", 100, 1, 3, pnl=5), fill(1, "BTC", "A", 100, 2, 2, pnl=5)])
    assert ops[0].parcial and ops[0].fechada
    assert numeros(ops)["n"] == 0


# ---------------- estatística ----------------
def test_bootstrap_separa_ganho_real_de_acaso():
    rnd = random.Random(1)
    bom = [rnd.gauss(0.004, 0.01) for _ in range(200)]
    zero = [rnd.gauss(0.0, 0.01) for _ in range(200)]
    assert p_bootstrap(bom) < 0.01
    assert p_bootstrap(zero) > 0.05


def test_benjamini_hochberg():
    q = benjamini_hochberg({"a": 0.001, "b": 0.02, "c": 0.04, "d": 0.5})
    assert q["a"] == pytest.approx(0.004) and q["d"] == pytest.approx(0.5)
    assert q["b"] <= q["c"] <= q["d"]


# ---------------- ponta a ponta com uma Hyperliquid falsa ----------------
def gerar_carteira(tipo, inicio, rnd):
    """Fills brutos (formato da API) de um tipo de trader."""
    fills, t, tid = [], inicio, 0
    n, media, dp, dur = {"bom": (220, 0.006, 0.012, 3 * H), "sortudo": (70, -0.0005, 0.01, 4 * H),
                         "hft": (900, 0.0004, 0.002, 60 * 1000), "ruim": (120, -0.004, 0.01, 2 * H)}[tipo]
    for i in range(n):
        px, sz = 100.0, 10.0
        r = rnd.gauss(media, dp)
        if tipo == "sortudo" and i == 30:
            r = 0.8  # uma tacada enorme
        saida = px * (1 + r)
        tid += 1
        fills.append({"time": t, "coin": "BTC", "side": "B", "px": str(px), "sz": str(sz), "startPosition": "0",
                      "closedPnl": "0", "fee": "0.2", "crossed": False, "oid": tid, "tid": tid, "dir": "Open Long"})
        t += dur
        tid += 1
        fills.append({"time": t, "coin": "BTC", "side": "A", "px": str(saida), "sz": str(sz), "startPosition": str(sz),
                      "closedPnl": str((saida - px) * sz), "fee": "0.2", "crossed": r < 0, "oid": tid, "tid": tid, "dir": "Close Long"})
        t += dur // 2 if tipo != "hft" else 1000
    return fills


class FalsaHL:
    def __init__(self, agora):
        rnd = random.Random(3)
        self.agora = agora
        self.tipos = {"0xbom": "bom", "0xsortudo": "sortudo", "0xhft": "hft", "0xruim": "ruim"}
        self.fills = {a: gerar_carteira(t, agora - 80 * 24 * H, rnd) for a, t in self.tipos.items()}

    def leaderboard(self):
        def linha(a, conta, roi, vlm):
            return {"ethAddress": a, "accountValue": str(conta), "displayName": a[2:],
                    "windowPerformances": [["day", {"pnl": "1", "roi": "0.01", "vlm": "1"}], ["week", {"pnl": "10", "roi": "0.02", "vlm": "100"}],
                                           ["month", {"pnl": str(conta * roi), "roi": str(roi), "vlm": str(vlm)}], ["allTime", {"pnl": "1000", "roi": "0.5", "vlm": "1"}]]}
        return [linha("0xbom", 50000, 0.2, 2e6), linha("0xsortudo", 40000, 0.4, 1e6), linha("0xhft", 60000, 0.1, 5e6),
                linha("0xruim", 30000, 0.05, 1e6), linha("0xpequena", 500, 0.5, 1e6), linha("0xmaker", 50000, 0.1, 5e8)]

    def fills_por_tempo(self, a, inicio):
        return [f for f in self.fills.get(a, []) if f["time"] >= inicio][:2000]


def test_ponta_a_ponta(tmp_path, monkeypatch):
    monkeypatch.setenv("RADAR_RAIZ", str(tmp_path))
    (tmp_path / "config.json").write_text(open("config.json", encoding="utf-8").read(), encoding="utf-8")
    import radar.armazenamento as A
    importlib.reload(A)
    import coletar
    import analisar
    importlib.reload(coletar); importlib.reload(analisar)
    agora = A.agora_ms()
    falsa = FalsaHL(agora)

    class Sessao:
        def get(self, url, timeout=0):
            class R:
                status_code = 200
                def raise_for_status(self): pass
                def json(self): return {"leaderboardRows": falsa.leaderboard()}
            return R()

        def post(self, url, json=None, timeout=0):
            corpo = json

            class R:
                status_code = 200
                text = ""
                def json(self):
                    if corpo["type"] == "userFillsByTime":
                        return falsa.fills_por_tempo(corpo["user"], corpo["startTime"])
                    if corpo["type"] == "clearinghouseState":
                        return {"marginSummary": {"accountValue": "50000", "totalNtlPos": "1000"}, "assetPositions": []}
                    return {}
            return R()

    import radar.api as api
    orig = api.Hyperliquid.__init__

    def init(self, por_minuto=1000, sessao=None, tentativas=5):
        orig(self, 100000, Sessao(), tentativas)
    monkeypatch.setattr(api.Hyperliquid, "__init__", init)
    monkeypatch.setattr(coletar, "Hyperliquid", api.Hyperliquid)

    assert coletar.main(5) == 0
    lista = json.loads((tmp_path / "dados" / "carteiras.json").read_text())
    assert set(lista) == {"0xbom", "0xsortudo", "0xhft", "0xruim", "0xmaker"}  # só a conta pequena fica de fora (giro não corta mais)
    # a segunda coleta não duplica fills
    assert coletar.main(5) == 0
    fs = A.ler_fills("0xbom")
    assert len(fs) == len(falsa.fills["0xbom"])

    # a análise vê todo o histórico como "antes" (as carteiras acabaram de entrar)
    assert analisar.main() == 0
    rel = json.loads((tmp_path / "saida" / "relatorio.json").read_text())
    cl = {c["carteira"]: c["classe"] for c in rel["carteiras"]}
    hft = next(c for c in rel["carteiras"] if c["carteira"] == "0xhft")
    assert hft["copiavel"]["ok"] is False and hft["classe"] != "nao_copiavel"  # só informação
    assert cl["0xruim"] == "perdendo"
    assert cl["0xsortudo"] == "sorte"
    assert cl["0xbom"] in ("promissora", "habilidade")
    bom = next(c for c in rel["carteiras"] if c["carteira"] == "0xbom")
    assert bom["estilo"]["pistas"]  # tem alguma pista do jeito de operar
    assert rel["carteiras"][0]["carteira"] == "0xbom"
    # carteira que não dá para copiar continua em observação (o João decide)
    lista = json.loads((tmp_path / "dados" / "carteiras.json").read_text())
    assert lista["0xhft"]["situacao"] == "observando"


# ---------------- humano ou robô ----------------
def test_operador_robo_e_humano():
    from radar.operador import avaliar
    rnd = random.Random(5)
    t0 = 1_760_000_000_000 - (1_760_000_000_000 % 60000)
    robo, humano = [], []
    for i in range(400):  # robô: a cada 15 min, 24 h por dia, no fechamento da vela, tamanho calculado
        t = t0 + i * 15 * 60000 + rnd.randint(0, 900)
        robo.append(fill(t, "BTC" if i % 2 else "ETH", "B" if i % 2 else "A", 60000 + i, round(0.0123 + rnd.random() * 0.01, 5), 0, oid=i, tid=i))
    k = 0
    for d in range(20):  # humano: das 9h às 23h, horários quebrados, tamanhos redondos
        for _ in range(8):
            t = t0 + d * 86400000 + rnd.randint(12, 26) * 3600000 + rnd.randint(0, 3599999)
            humano.append(fill(t, "SOL", "B", 150.0, rnd.choice([1, 2, 5, 10, 0.5]), 0, oid=10000 + k, tid=10000 + k)); k += 1
    r, h = avaliar(robo), avaliar(humano)
    assert r["rotulo"] == "Robô provável", r
    assert h["rotulo"] == "Humano provável", h
    assert avaliar(humano[:5])["nota"] is None


# ---------------- números para copiar ----------------
def test_perfil_copia():
    from radar.copia import perfil_copia
    agora = 1_790_000_000_000
    fs = []
    for i in range(10):  # 10 operações de 1 h e 10 de 2 s
        t = agora - (20 - i) * 86400000
        fs += [fill(t, "BTC", "B", 100, 1, 0, oid=2 * i, tid=4 * i), fill(t + H, "BTC", "A", 102, 1, 1, pnl=2, oid=2 * i + 1, tid=4 * i + 1),
               fill(t + 5000, "ETH", "B", 100, 1, 0, oid=100 + i, tid=4 * i + 2), fill(t + 7000, "ETH", "A", 99, 1, 1, pnl=-1, oid=200 + i, tid=4 * i + 3)]
    ops = montar(fs)
    fotos = [{"t": agora, "v": 1000, "ntl": 5000, "pos": [["BTC", 1, 100, 10]]}, {"t": agora, "v": 2000, "ntl": 0, "pos": []}]
    p = perfil_copia(ops, fotos, 500, agora)
    assert p["conta_ref"] == 1500           # mediana das fotos (maior que o saldo de entrada)
    assert p["alavancagem"]["exposicao_mediana"] == 5 and p["alavancagem"]["configurada_max"] == 10
    assert p["alavancagem"]["posicionado"] == 0.5
    assert p["total"] == pytest.approx(10)
    assert p["por_atraso"]["5"]["n"] == 10 and p["por_atraso"]["5"]["resultado"] == pytest.approx(20)  # só as de 1 h
    assert sum(p["pnl_dia"]) == pytest.approx(10) and len(p["pnl_dia"]) == 21
