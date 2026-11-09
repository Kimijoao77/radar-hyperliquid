import json

from lab.cofres import candidatos, constante, desde, indice, medir

D = 86400000


def port(n, passo):
    av = [[i * D, str(1000 + 100 * i)] for i in range(n)]           # depósitos fazem o saldo subir
    pnl = [[i * D, str(sum(passo(k) for k in range(1, i + 1)))] for i in range(n)]
    return [["allTime", {"accountValueHistory": av, "pnlHistory": pnl}], ["month", {"accountValueHistory": av[-30:], "pnlHistory": pnl[-30:]}]]


def test_indice_ignora_depositos():
    ind = indice(port(10, lambda k: 0.0))
    assert ind[-1][1] == 1.0                                         # sem lucro: índice parado, mesmo com o saldo subindo


def test_constante_e_sorte():
    bom = medir(indice(port(120, lambda k: 3 + (k % 3))))
    assert constante(bom) and bom["ao_ano"] > 0
    ruim = medir(indice(port(120, lambda k: (-1) ** k * 50)))
    assert not constante(ruim)


def test_desde_e_candidatos():
    ind = [[0, 1.0], [D, 1.1], [2 * D, 1.21]]
    assert abs(desde(ind, D) - 0.1) < 1e-9
    lista = [{"apr": 0.3, "summary": {"vaultAddress": "0xA", "name": "a", "tvl": "500000", "isClosed": False, "createTimeMillis": 0}},
             {"apr": 0.3, "summary": {"vaultAddress": "0xB", "name": "b", "tvl": "500000", "isClosed": True, "createTimeMillis": 0}},
             {"apr": 0.3, "summary": {"vaultAddress": "0xC", "name": "c", "tvl": "50", "isClosed": False, "createTimeMillis": 0}}]
    c = candidatos(lista, 100 * D, {"tvl_minimo": 100000, "idade_minima_dias": 60})
    assert [x["cofre"] for x in c] == ["0xa"]


def test_rodar(tmp_path):
    import lab.rodar_cofres as R
    lista = [{"apr": 0.2, "summary": {"vaultAddress": f"0x{i}", "name": f"c{i}", "tvl": str(1e6 - i), "isClosed": False, "createTimeMillis": 0}} for i in range(3)]

    import math

    class Api:
        def _post(self, corpo, peso):
            bom = corpo["vaultAddress"] != "0x2"
            return {"name": corpo["vaultAddress"], "leaderCommission": 0.1, "followers": [1, 2],
                    "portfolio": port(150, (lambda k: 3 + (k % 3)) if bom else (lambda k: (-1) ** k * 80))}

        def velas(self, moeda, iv, a, b):                    # BTC sobe e desce ~15 % (há quedas de mais de 5 %)
            return [{"t": i * D, "c": str(100 * (1 + 0.15 * math.sin(i / 6)))} for i in range(0, 160)]
    assert R.main(tmp_path, Api(), lambda: lista) == 0
    rel = json.loads((tmp_path / "saida" / "cofres.json").read_text())
    assert rel["cofres"][0]["constante"] and rel["carteira"]["capital"] == 1000
    assert rel["versao"] == 2
    bom = next(c for c in rel["cofres"] if c["cofre"] == "0x0")
    assert bom["independente"] and abs(bom["beta"]) < 0.3 and bom["trechos_queda"] > 0
    est = json.loads((tmp_path / "lab" / "dados" / "cofres_estado.json").read_text())
    assert "0x2" not in est["escolhidos"] and est["escolhidos"][-1].startswith("0xdfc24b")
    assert abs(est["pesos"][est["escolhidos"][-1]] - 0.4) < 1e-9 and abs(sum(est["pesos"].values()) - 1) < 1e-9
