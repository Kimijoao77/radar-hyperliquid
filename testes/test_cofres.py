import json

from lab.cofres import candidatos, constante, de_risco, depositar, desde, indice, medir, nota_risco

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
    assert rel["versao"] == 3
    bom = next(c for c in rel["cofres"] if c["cofre"] == "0x0")
    assert bom["independente"] and abs(bom["beta"]) < 0.3 and bom["trechos_queda"] > 0
    est = json.loads((tmp_path / "lab" / "dados" / "cofres_estado.json").read_text())
    assert "0x2" not in est["escolhidos"] and est["escolhidos"][-1].startswith("0xdfc24b")
    assert est["escolhidos"] == [est["escolhidos"][-1]] and est["pesos"][est["escolhidos"][-1]] == 1.0   # versão 3: só o HLP


def cofre(**k):
    base = {"hlp": False, "aceita_deposito": True, "apr": 0.8, "mes": 0.05,
            "medidas": {"ao_ano": 1.2, "pior_queda": 0.3, "p": 0.02}}
    base.update(k)
    return base


def test_de_risco_regras():
    assert de_risco(cofre())
    assert not de_risco(cofre(hlp=True))                                       # o HLP tem o teste dele
    assert not de_risco(cofre(filho=True))                                     # cofre-filho (do HLP): ninguém deposita direto
    assert not de_risco(cofre(aceita_deposito=False))                          # fechado para depósito
    assert not de_risco(cofre(apr=0.2))                                        # rende pouco agora
    assert not de_risco(cofre(mes=-0.01))                                      # no vermelho no último mês
    assert not de_risco(cofre(medidas={"ao_ano": 0.3, "pior_queda": 0.3, "p": 0.02}))    # histórico abaixo da régua
    assert not de_risco(cofre(medidas={"ao_ano": 1.2, "pior_queda": 0.7, "p": 0.02}))    # queda acima do risco aceito
    assert not de_risco(cofre(medidas={"ao_ano": 1.2, "pior_queda": 0.3, "p": 0.4}))      # parece sorte
    assert de_risco(cofre(beta=-1.1, nas_quedas=0.19))                         # não exige beta baixo
    assert nota_risco(cofre(apr=0.8, medidas={"ao_ano": 1.9, "pior_queda": 0.01, "p": 0.07})) == 0.8   # o menor dos dois


def test_depositar_comissao_do_proprio_cofre():
    ind = lambda x: [[0, 1.0], [D, x]]
    medidos = [{"cofre": "0xa", "nome": "A", "comissao": 0.1, "_ind": ind(1.2)}, {"cofre": "0xb", "nome": "B", "comissao": 0.0, "hlp": True, "_ind": ind(1.2)}]
    est = {"escolhidos": ["0xa", "0xb"], "pesos": {"0xa": 0.5, "0xb": 0.5}, "base": {"0xa": 1.0, "0xb": 1.0}}
    itens, total = depositar(est, medidos, {"capital": 1000.0, "comissao": 0.10}, 5 * D)
    assert [i["ganho"] for i in itens] == [90.0, 100.0] and abs(total - 1190.0) < 1e-6       # 10 % do dono; o HLP não cobra
    assert est["curva"] == [[5 * D, 1190.0]]


def test_rodar_monta_a_carteira_de_risco(tmp_path):
    import math

    import lab.rodar_cofres as R
    lista = [{"apr": a, "summary": {"vaultAddress": f"0x{i}", "name": f"c{i}", "tvl": str(1e6 - i), "isClosed": False, "createTimeMillis": 0}}
             for i, a in enumerate([0.2, 0.9, 0.9])]

    class Api:
        def _post(self, corpo, peso):
            forte = corpo["vaultAddress"] != "0x0"
            return {"name": corpo["vaultAddress"], "leaderCommission": 0.1, "followers": [1], "allowDeposits": corpo["vaultAddress"] != "0x2",
                    "portfolio": port(150, (lambda k: 20 + (k % 3)) if forte else (lambda k: 3 + (k % 3)))}

        def velas(self, moeda, iv, a, b):
            return [{"t": i * D, "c": str(100 * (1 + 0.15 * math.sin(i / 6)))} for i in range(0, 160)]
    assert R.main(tmp_path, Api(), lambda: lista) == 0
    rel = json.loads((tmp_path / "saida" / "cofres.json").read_text())
    est = json.loads((tmp_path / "lab" / "dados" / "cofres_estado.json").read_text())
    assert est["risco"]["escolhidos"] == ["0x1"]                       # 0x0 rende pouco; 0x2 não abre depósito
    assert rel["risco"]["capital"] == 1000 and rel["risco"]["itens"][0]["cofre"] == "0x1" and rel["risco"]["curva"]
    assert rel["carteira"]["itens"][-1]["hlp"] or rel["carteira"]["itens"][-1]["cofre"].startswith("0xdfc24b")
    # segunda rodada logo em seguida: não repete a chamada pesada (já passou a primeira vez do risco) e a carteira não muda
    assert R.main(tmp_path, Api(), lambda: lista) == 0
    est2 = json.loads((tmp_path / "lab" / "dados" / "cofres_estado.json").read_text())
    assert est2["risco"]["escolhidos"] == ["0x1"] and est2["risco"]["inicio"] == est["risco"]["inicio"]


def test_rodar_tira_o_cofre_filho_e_refaz_a_carteira_de_risco_antiga(tmp_path):
    import math

    import lab.rodar_cofres as R
    lista = [{"apr": a, "summary": {"vaultAddress": f"0x{i}", "name": f"c{i}", "tvl": str(1e6 - i), "isClosed": False, "createTimeMillis": 0,
                                    "leader": "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303" if i == 2 else f"0xl{i}"}}
             for i, a in enumerate([0.9, 0.9, 0.9])] + [
        {"apr": 0.25, "summary": {"vaultAddress": "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303", "name": "HLP", "tvl": "1", "isClosed": False,
                                  "createTimeMillis": 0, "leader": "0xhlp"}}]

    class Api:
        def _post(self, corpo, peso):
            rel = {"type": "child"} if corpo["vaultAddress"] == "0x1" else {"type": "normal"}
            return {"name": corpo["vaultAddress"], "leaderCommission": 0.1, "followers": [1], "allowDeposits": True, "relationship": rel,
                    "portfolio": port(150, lambda k: 20 + (k % 3))}

        def velas(self, moeda, iv, a, b):
            return [{"t": i * D, "c": str(100 * (1 + 0.15 * math.sin(i / 6)))} for i in range(0, 160)]
    # estado da versão 1 da carteira de risco (sem "versao"), com um cofre-filho escolhido
    (tmp_path / "lab" / "dados").mkdir(parents=True)
    (tmp_path / "lab" / "dados" / "cofres_estado.json").write_text(json.dumps(
        {"versao": 3, "inicio": 1, "escolhidos": ["0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"], "pesos": {}, "base": {}, "ultima": 10 ** 13,
         "risco": {"inicio": 1, "escolhidos": ["0x2"], "pesos": {"0x2": 1.0}, "base": {"0x2": 1.0}}}))
    assert R.main(tmp_path, Api(), lambda: lista) == 0
    est = json.loads((tmp_path / "lab" / "dados" / "cofres_estado.json").read_text())
    # 0x1 é filho pela API (relationship) e 0x2 porque o dono é o HLP: só 0x0 fica; a carteira do HLP continua a mesma
    assert est["risco"]["escolhidos"] == ["0x0"] and est["risco"]["versao"] == 2 and est["inicio"] == 1
    rel = json.loads((tmp_path / "saida" / "cofres.json").read_text())
    assert {x["cofre"]: x["filho"] for x in rel["cofres"]} == {"0x0": False, "0x1": True, "0x2": True,
                                                               "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303": False}
