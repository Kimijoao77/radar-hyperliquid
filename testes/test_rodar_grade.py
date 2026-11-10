"""O executor da grade/DCA/tendência de ponta a ponta, com velas e funding de mentira."""
import json
import random
import time

import lab.rodar_grade as R
from lab.grade import HORA


class Api:
    def __init__(self, n=900, funding=True):
        self.n, self.funding, self.chamadas = n, funding, []

    def velas(self, moeda, iv, a, b):
        agora = int(time.time() * 1000) // HORA * HORA
        rnd, p, out = random.Random(sum(map(ord, moeda))), 100.0, []
        for i in range(self.n):
            t = agora - (self.n - i) * HORA
            o, p = p, p * (1 + rnd.gauss(0.0003, 0.01))
            out.append({"t": t, "T": t + HORA - 1, "o": str(o), "c": str(p), "h": str(max(o, p) * 1.003), "l": str(min(o, p) * 0.997)})
        return out

    def _post(self, corpo, peso):
        self.chamadas.append(corpo["type"])
        if not self.funding:
            raise RuntimeError("sem funding")
        h, out = (corpo["startTime"] // HORA + 1) * HORA, []
        while h < corpo["endTime"] and len(out) < 500:
            out.append({"coin": corpo["coin"], "fundingRate": "0.0000125", "premium": "0", "time": h + 13})
            h += HORA
        return out


def test_rodar_grade_com_funding_e_tendencia(tmp_path):
    api = Api()
    assert R.main(tmp_path, api) == 0
    rel = json.loads((tmp_path / "saida" / "grade.json").read_text())
    assert rel["versao"] == 4 and rel["testados"] == 4 * 53
    assert set(rel["funding"]) == {"BTC", "ETH", "SOL", "HYPE"} and abs(rel["funding"]["BTC"]["ao_ano"] - 0.1095) < 0.001
    tipos = [a["config"]["tipo"] for a in rel["ao_vivo"]]
    assert tipos.count("tendencia") == 3 and len(tipos) - tipos.count("tendencia") == 3
    assert all(a["moeda"] in R.MOEDAS for a in rel["ao_vivo"])
    # o arquivo do app não leva as 212 linhas do ranking: só as melhores
    assert len(rel["passado"]) <= 40 and any(r["config"]["tipo"] == "tendencia" for r in rel["passado"])
    cache = json.loads((tmp_path / "lab" / "dados" / "grade_funding.json").read_text())
    assert set(cache) == {"BTC", "ETH", "SOL", "HYPE"} and len(cache["BTC"]["r"]) > 800
    # 2ª rodada: o funding só acrescenta o que falta e as escolhidas continuam as mesmas
    api2 = Api()
    escolhidas = json.loads((tmp_path / "lab" / "dados" / "grade_estado.json").read_text())["escolhidas"]
    assert R.main(tmp_path, api2) == 0
    assert json.loads((tmp_path / "lab" / "dados" / "grade_estado.json").read_text())["escolhidas"] == escolhidas
    assert len(api2.chamadas) <= 4


def test_rodar_grade_sem_funding_nao_quebra(tmp_path):
    assert R.main(tmp_path, Api(funding=False)) == 0                # o funding falha: as contas seguem sem ele
    rel = json.loads((tmp_path / "saida" / "grade.json").read_text())
    assert rel["versao"] == 4 and rel["funding"] == {} and rel["ao_vivo"]


def test_versao_nova_guarda_o_historico_das_anteriores(tmp_path):
    (tmp_path / "lab" / "dados").mkdir(parents=True)
    (tmp_path / "saida").mkdir()
    (tmp_path / "lab" / "dados" / "grade_estado.json").write_text(json.dumps(
        {"versao": 2, "anterior": [{"moeda": "HYPE", "nome": "v1", "retorno": -0.36}], "escolhidas": [], "inicio": 1}))
    (tmp_path / "saida" / "grade.json").write_text(json.dumps(
        {"inicio_ao_vivo": 5, "gerado": 9, "ao_vivo": [{"moeda": "BTC", "nome": "v2", "resultado": {"retorno": 0.01, "pior_queda": 0.02, "segurar_moeda": 0.0}}]}))
    assert R.main(tmp_path, Api()) == 0
    est = json.loads((tmp_path / "lab" / "dados" / "grade_estado.json").read_text())
    assert [a["nome"] for a in est["anterior"]] == ["v1", "v2"] and est["versao"] == 4
