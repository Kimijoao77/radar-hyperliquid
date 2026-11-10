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
    assert rel["versao"] == R.VERSAO and rel["testados"] == len(R.MOEDAS) * (53 + 36) and len(R.MOEDAS) == 8
    assert set(rel["funding"]) == set(R.MOEDAS) and abs(rel["funding"]["BTC"]["ao_ano"] - 0.1095) < 0.001
    tipos = [a["config"]["tipo"] for a in rel["ao_vivo"]]
    assert tipos.count("tendencia") == 3 and sum(t in ("grade", "dca") for t in tipos) == 3 and tipos.count("reversao") <= 3
    assert all(a["moeda"] in R.MOEDAS for a in rel["ao_vivo"])
    # o arquivo do app não leva as 712 linhas do ranking: só as melhores
    assert len(rel["passado"]) <= 50 and any(r["config"]["tipo"] == "tendencia" for r in rel["passado"])
    cache = json.loads((tmp_path / "lab" / "dados" / "grade_funding.json").read_text())
    assert set(cache) == set(R.MOEDAS) and len(cache["BTC"]["r"]) > 800
    # 2ª rodada: o funding só acrescenta o que falta e as escolhidas continuam as mesmas
    api2 = Api()
    escolhidas = json.loads((tmp_path / "lab" / "dados" / "grade_estado.json").read_text())["escolhidas"]
    assert R.main(tmp_path, api2) == 0
    assert json.loads((tmp_path / "lab" / "dados" / "grade_estado.json").read_text())["escolhidas"] == escolhidas
    assert len(api2.chamadas) <= len(R.MOEDAS)


def test_rodar_grade_sem_funding_nao_quebra(tmp_path):
    assert R.main(tmp_path, Api(funding=False)) == 0                # o funding falha: as contas seguem sem ele
    rel = json.loads((tmp_path / "saida" / "grade.json").read_text())
    assert rel["versao"] == R.VERSAO and rel["funding"] == {} and rel["ao_vivo"]


def _estado_antigo(tmp_path, horas_ao_vivo):
    (tmp_path / "lab" / "dados").mkdir(parents=True)
    (tmp_path / "saida").mkdir()
    (tmp_path / "lab" / "dados" / "grade_estado.json").write_text(json.dumps(
        {"versao": 2, "anterior": [{"moeda": "HYPE", "nome": "v1", "retorno": -0.36}], "escolhidas": [], "inicio": 1}))
    (tmp_path / "saida" / "grade.json").write_text(json.dumps(
        {"inicio_ao_vivo": 5 * HORA, "gerado": (5 + horas_ao_vivo) * HORA,
         "ao_vivo": [{"moeda": "BTC", "nome": "v2", "resultado": {"retorno": 0.01, "pior_queda": 0.02, "segurar_moeda": 0.0}}]}))


def test_versao_nova_guarda_o_historico_das_anteriores(tmp_path):
    _estado_antigo(tmp_path, 30)
    assert R.main(tmp_path, Api()) == 0
    est = json.loads((tmp_path / "lab" / "dados" / "grade_estado.json").read_text())
    assert [a["nome"] for a in est["anterior"]] == ["v1", "v2"] and est["versao"] == R.VERSAO


def test_versao_nova_nao_guarda_quem_ficou_poucas_horas_ao_vivo(tmp_path):
    _estado_antigo(tmp_path, 2)                         # 2 h ao vivo: ainda não diz nada
    assert R.main(tmp_path, Api()) == 0
    est = json.loads((tmp_path / "lab" / "dados" / "grade_estado.json").read_text())
    assert [a["nome"] for a in est["anterior"]] == ["v1"] and est["versao"] == R.VERSAO
