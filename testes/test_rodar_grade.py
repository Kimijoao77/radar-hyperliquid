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


def _estado(tmp_path, est):
    (tmp_path / "lab" / "dados").mkdir(parents=True)
    (tmp_path / "lab" / "dados" / "grade_estado.json").write_text(json.dumps(est))


def _vivo(tmp_path):
    rel = json.loads((tmp_path / "saida" / "grade.json").read_text())
    est = json.loads((tmp_path / "lab" / "dados" / "grade_estado.json").read_text())
    return rel, est


def test_versao_nova_nao_zera_os_robos_ao_vivo(tmp_path):
    agora = int(time.time() * 1000) // HORA * HORA
    ini = agora - 40 * HORA
    dca = {"tipo": "dca", "passo": 0.02, "alvo": 0.03, "alav": 3, "pausa": True}
    tend = {"tipo": "tendencia", "modo": "medias", "a": 48, "b": 168, "alav": 3}
    _estado(tmp_path, {"versao": 5, "inicio": ini, "anterior": [{"moeda": "HYPE", "nome": "v1", "retorno": -0.36, "de": 1, "ate": 2}],
                       "escolhidas": [{"moeda": "HYPE", "config": dca}, {"moeda": "SOL", "config": tend}]})
    assert R.main(tmp_path, Api()) == 0
    rel, est = _vivo(tmp_path)
    assert est["versao"] == R.VERSAO and [a["nome"] for a in est["anterior"]] == ["v1"]
    velhos = [e for e in est["escolhidas"] if e["config"] in (dca, tend)]
    assert len(velhos) == 2 and all(e["inicio"] == ini for e in velhos)          # continuam do começo deles
    assert all(e["inicio"] == agora for e in est["escolhidas"] if e not in velhos)  # famílias que faltavam começam agora
    assert {R.familia(e["config"]) for e in est["escolhidas"]} >= {"reverter", "tendencia"}
    a = next(x for x in rel["ao_vivo"] if x["config"] == dca)
    assert a["inicio"] == ini and a["resultado"]["dias"] >= 1.5 and rel["inicio_ao_vivo"] == ini


def test_volta_os_robos_que_a_versao_6_zerou(tmp_path):
    agora = int(time.time() * 1000) // HORA * HORA
    de5, ini6 = agora - 30 * HORA, agora - 3 * HORA
    from lab.grade import nome
    dca = {"tipo": "dca", "passo": 0.03, "alvo": 0.015, "alav": 3, "pausa": False}
    tend = {"tipo": "tendencia", "modo": "rompe", "a": 240, "alav": 2}
    rev = {"tipo": "reversao", "gatilho": 0.08, "alvo": 0.02, "lados": "ambos", "alav": 3}
    novo = {"tipo": "dca", "passo": 0.02, "alvo": 0.015, "alav": 3, "pausa": False}
    _estado(tmp_path, {"versao": 6, "inicio": ini6,
                       "anterior": [{"moeda": "HYPE", "nome": "v1", "retorno": -0.36, "de": 5, "ate": 6},
                                    {"moeda": "ETH", "nome": nome(dca), "retorno": 0.0037, "de": de5, "ate": ini6},
                                    {"moeda": "SOL", "nome": nome(tend), "retorno": 0.026, "de": de5, "ate": ini6}],
                       "escolhidas": [{"moeda": "NEAR", "config": novo}, {"moeda": "kPEPE", "config": rev}]})
    assert R.main(tmp_path, Api()) == 0
    rel, est = _vivo(tmp_path)
    por = {(e["moeda"], json.dumps(e["config"], sort_keys=True)): e["inicio"] for e in est["escolhidas"]}
    assert por[("ETH", json.dumps(dca, sort_keys=True))] == de5 and por[("SOL", json.dumps(tend, sort_keys=True))] == de5
    assert por[("kPEPE", json.dumps(rev, sort_keys=True))] == ini6            # a reversão da versão 6 fica, com o começo dela
    assert ("NEAR", json.dumps(novo, sort_keys=True)) not in por              # o DCA novo da 6 sai: a família já tem os robôs de volta
    assert [a["nome"] for a in est["anterior"]] == ["v1"]                     # quem voltou sai de "versões anteriores"
    assert rel["inicio_ao_vivo"] == de5
