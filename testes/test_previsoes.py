import json

from lab import previsoes as P
from lab import rodar_previsoes as R

H = P.HORA
T0 = 1_795_000_000_000          # 2026-11-18 (ms)


def mercado(mid, q, p0, fim_ms, ask=None, bid=None, fechado=False, precos=None, tags=("politics",), ev="e1", **extra):
    ask = p0 + 0.01 if ask is None else ask
    bid = p0 - 0.01 if bid is None else bid
    m = {"id": mid, "question": q, "outcomes": json.dumps(["Yes", "No"]), "outcomePrices": json.dumps(precos or [str(p0), str(round(1 - p0, 4))]),
         "clobTokenIds": json.dumps([f"t{mid}a", f"t{mid}b"]), "endDate": P.datetime.fromtimestamp(fim_ms / 1000, P.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "closed": fechado, "acceptingOrders": not fechado, "enableOrderBook": True, "bestAsk": ask, "bestBid": bid, "spread": round(ask - bid, 4),
         "liquidityNum": 50000, "volume24hr": 20000, "volumeNum": 100000, "tags": [{"slug": t} for t in tags], "events": [{"id": ev}],
         "feesEnabled": True, "feeSchedule": {"rate": 0.04}}
    m.update(extra)
    return m


def test_datas_e_categorias():
    assert P.ms_de("2026-11-18T03:00:00Z") == P.ms_de("2026-11-18 03:00:00+00")
    assert P.ms_de("2026-11-18 03:13:18.091431+00") - P.ms_de("2026-11-18T03:13:18Z") == 0
    assert P.categoria({"tags": [{"slug": "crypto"}]}) == "Cripto"
    assert P.categoria({"tags": [{"slug": "politics"}]}) == "Política"
    assert P.categoria({"gameStartTime": "2026-11-18 19:40:00+00"}) == "Esportes"
    assert P.categoria({"tags": []}) == "Outros"


def test_candidatos_por_jeito():
    ms = [mercado("1", "Fav curto", 0.93, T0 + 20 * H),          # favorito "No" a 1 - 0.93 + ... não: Yes a 0.93
          mercado("2", "Azarao", 0.08, T0 + 3 * 24 * H, ev="e2"),
          mercado("3", "Longe", 0.93, T0 + 30 * 24 * H, ev="e3"),
          mercado("4", "BTC Up or Down 5m", 0.93, T0 + 2 * H, ev="e4")]
    qc = P.candidatos(ms, P.VARIANTES["quase_certas"], T0)
    assert [c["m"]["id"] for c in qc] == ["1"] and qc[0]["lado"] == 0 and abs(qc[0]["preco"] - 0.94) < 1e-9
    az = P.candidatos(ms, P.VARIANTES["azaroes"], T0)
    assert [c["m"]["id"] for c in az] == ["1", "2"] or [c["m"]["id"] for c in az] == ["2"]
    lados = {c["m"]["id"]: (c["lado"], c["preco"]) for c in az}
    assert lados["2"] == (0, 0.09)                               # o azarão é o "Yes" a 9¢


def test_resolucao():
    assert P.resolucao({"closed": True, "outcomePrices": '["1", "0"]', "umaResolutionStatus": "resolved"}) == [1.0, 0.0]
    assert P.resolucao({"closed": True, "outcomePrices": '["0.5", "0.5"]', "umaResolutionStatus": "resolved"}) == [0.5, 0.5]
    assert P.resolucao({"closed": True, "outcomePrices": '["0.97", "0.03"]', "umaResolutionStatus": "resolved"}) is None
    assert P.resolucao({"closed": False, "outcomePrices": '["1", "0"]'}) is None


class Falsa:
    def __init__(self):
        self.abertos, self.porid, self.fechados, self.hist = [], {}, [], {}

    def mercados(self, **p):
        return self.fechados if p.get("closed") == "true" else self.abertos

    def por_id(self, ids):
        return {i: self.porid[i] for i in ids if i in self.porid}

    def historico(self, token, ini, fim):
        return self.hist.get(token, [])


def test_rodada_aposta_e_resolve(tmp_path):
    api = Falsa()
    m = mercado("10", "Vai acontecer?", 0.92, T0 + 30 * H)
    api.abertos = [m]
    assert R.main(tmp_path, api, T0) == 0
    rel = json.loads((tmp_path / "saida" / "previsoes.json").read_text())
    qc = rel["variantes"]["quase_certas"]
    assert len(qc["abertas"]) == 1 and qc["abertas"][0]["preco"] == 0.93 and qc["caixa"] == 980
    cotas = qc["abertas"][0]["cotas"]
    assert abs(cotas * (0.93 + 0.04 * 0.93 * 0.07) - 20) < 1e-3       # a taxa sai dos US$ 20
    assert rel["variantes"]["favoritas"]["abertas"] == []               # 93¢ não é "favorita da semana"
    # resolveu "Yes": cada cota vale US$ 1
    api.abertos = []
    api.porid = {"10": mercado("10", "Vai acontecer?", 0.92, T0 + 30 * H, fechado=True, precos=["1", "0"], umaResolutionStatus="resolved")}
    R.main(tmp_path, api, T0 + 2 * H)
    rel = json.loads((tmp_path / "saida" / "previsoes.json").read_text())
    qc = rel["variantes"]["quase_certas"]
    assert qc["abertas"] == [] and qc["apostas"] == 1 and qc["acertos"] == 1
    assert abs(qc["patrimonio"] - (980 + cotas)) < 0.01 and qc["retorno"] > 0
    assert qc["fechadas"][0]["estado"] == "ganhou"
    # não roda de novo antes de 50 min
    assert R.main(tmp_path, api, T0 + 2 * H + 10 * 60 * 1000) == 0


def test_passado_e_calibracao(tmp_path):
    fech = T0 - 2 * 24 * H
    m = mercado("20", "Passou?", 0.9, fech, fechado=True, precos=["1", "0"], umaResolutionStatus="resolved",
                closedTime=P.datetime.fromtimestamp(fech / 1000, P.timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00"))
    hist = [(fech - k * H, 0.9) for k in range(100, 0, -1)]
    r = P.no_passado(m, hist)
    assert r["p24"] == 0.9 and r["venceu"] == [1.0, 0.0]
    assert "quase_certas" in r["apostas"] and r["apostas"]["quase_certas"]["r"] > 0
    assert "azaroes" in r["apostas"] and r["apostas"]["azaroes"]["r"] == -1.0
    res = P.resumo_passado([r])
    cal = {c["faixa"]: c for c in res["calibracao"]}
    assert cal["90–100¢"]["n"] == 1 and cal["90–100¢"]["real"] == 1.0
    assert cal["10–20¢"]["n"] == 1 and cal["10–20¢"]["real"] == 0.0
    # pela rodada: entra no passado
    api = Falsa()
    api.fechados = [m]
    api.hist = {"t20a": hist}
    R.main(tmp_path, api, T0)
    rel = json.loads((tmp_path / "saida" / "previsoes.json").read_text())
    assert rel["passado"]["mercados"] == 1 and rel["passado"]["variantes"]["quase_certas"]["apostas"] == 1
