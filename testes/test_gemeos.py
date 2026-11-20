"""Os gêmeos ao vivo dos laboratórios (vivo/gemeos.py): a partida do mesmo estado do normal e a agenda."""
import json

from vivo import gemeos as G

H = 3_600_000


class Proc:
    def __init__(self):
        self.fim, self.morto = None, False

    def poll(self):
        return self.fim

    def kill(self):
        self.morto = True

    terminate = kill


class Mundo:
    def __init__(self, tmp_path):
        self.raiz, self.t, self.chamadas, self.procs = tmp_path, 500 * H + 10 * G.MIN, [], []
        (tmp_path / "lab" / "dados").mkdir(parents=True)
        (tmp_path / "saida").mkdir()
        for lab in G.LABS:
            self.normal(lab, 3)
        self.robo = self.novo()

    def normal(self, lab, versao, extra=None):
        (self.raiz / "lab" / "dados" / f"{lab}_estado.json").write_text(json.dumps({"versao": versao, "x": extra}), encoding="utf-8")
        (self.raiz / "saida" / f"{lab}.json").write_text(json.dumps({"de": "normal", "versao": versao}), encoding="utf-8")

    def abrir(self, cmd, cwd=None, env=None, stdout=None, stderr=None):
        self.chamadas.append((cmd[-1], env.get("LAB_SEM_ESPERA"), env.get("RADAR_PESO_TETO"), env.get("RADAR_RAIZ")))
        stdout.write("linha do meio\nlistagens: tudo certo\n")
        self.procs.append(Proc())
        return self.procs[-1]

    def novo(self):
        return G.Gemeos(self.raiz, lambda: self.t, abrir=self.abrir)

    def passo(self, depois_min=0.0):
        self.t += int(depois_min * G.MIN)
        self.robo.proximo = 0
        self.robo.passo(self.t)

    def terminar(self, codigo=0):
        self.procs[-1].fim = codigo
        self.passo(0.1)


def test_devido_por_intervalo_e_no_minuto_certo_da_hora():
    cada = {"cada_min": 10}
    assert G.devido(cada, None, 5) and not G.devido(cada, 0, 9 * G.MIN) and G.devido(cada, 0, 10 * G.MIN)
    hora = {"no_minuto": 2}
    assert not G.devido(hora, None, 7 * H + 1 * G.MIN)                 # antes do minuto 2: a vela ainda pode não ter fechado
    assert G.devido(hora, None, 7 * H + 2 * G.MIN)
    assert not G.devido(hora, 7 * H + 2 * G.MIN, 7 * H + 50 * G.MIN)   # uma vez por hora
    assert G.devido(hora, 7 * H + 2 * G.MIN, 8 * H + 3 * G.MIN)
    assert G.devido(hora, 6 * H + 40 * G.MIN, 7 * H + 30 * G.MIN)      # perdeu o minuto (motor reiniciando): roda quando der


def test_parte_do_estado_do_normal_e_roda_um_por_vez(tmp_path):
    m = Mundo(tmp_path)
    (tmp_path / "lab" / "dados" / "grade_funding.json").write_text("{}", encoding="utf-8")
    m.passo()
    g = G.pasta(tmp_path)
    assert m.chamadas == [("grade", None, str(G.PESO_TETO), str(tmp_path))]      # a grade mantém a espera dela (não tem)
    assert json.loads((g / "lab" / "dados" / "grade_estado.json").read_text()) == {"versao": 3, "x": None}
    assert (g / "lab" / "dados" / "grade_funding.json").exists() and json.loads((g / "saida" / "grade.json").read_text())["de"] == "normal"
    assert not (g / "lab" / "dados" / "cofres_estado.json").exists()            # cada um parte na vez dele
    m.passo(1)
    assert len(m.chamadas) == 1                                                  # a grade ainda está rodando
    m.terminar()
    assert [c[0] for c in m.chamadas] == ["grade", "cofres"] and m.chamadas[1][1] == "1"   # cofres sem a espera de 6 h
    for _ in range(3):
        m.terminar()
    assert [c[0] for c in m.chamadas] == ["grade", "cofres", "concentradas", "listagens", "previsoes"]
    m.terminar(1)                                                                # previsões falhou
    arq = json.loads((g / "gemeos.json").read_text())
    assert set(arq["semente"]) == set(G.LABS) and arq["semente"]["grade"] == {"t": 500 * H + 10 * G.MIN, "versao": 3}
    assert arq["labs"]["listagens"]["ok"] and arq["labs"]["listagens"]["msg"] == "listagens: tudo certo" and arq["labs"]["listagens"]["rodadas"] == 1
    assert arq["labs"]["previsoes"]["ok"] is False
    assert arq["ritmo"]["grade"] == {"no_minuto": 2} and arq["ritmo"]["concentradas"] == {"cada_min": 10}
    assert len(m.chamadas) == 5                                                  # ninguém devido ainda
    m.passo(10)
    assert m.chamadas[-1][0] == "concentradas" and len(m.chamadas) == 6          # 10 min depois: só as pools (e as previsões na fila)


def test_nao_mexe_no_estado_do_gemeo_nas_rodadas_seguintes_mas_parte_de_novo_se_a_versao_do_normal_muda(tmp_path):
    m = Mundo(tmp_path)
    for _ in range(5):
        m.passo() if not m.procs else m.terminar()
    m.terminar()
    g = G.pasta(tmp_path) / "lab" / "dados" / "concentradas_estado.json"
    g.write_text(json.dumps({"versao": 3, "x": "do gêmeo"}), encoding="utf-8")
    m.normal("concentradas", 3, "normal andou")
    partiu = m.robo.semente["concentradas"]["t"]
    m.passo(10)
    m.terminar()
    assert json.loads(g.read_text())["x"] == "do gêmeo" and m.robo.semente["concentradas"]["t"] == partiu
    m.normal("concentradas", 4, "regras novas")
    while m.chamadas[-1][0] != "concentradas" or m.procs[-1].fim is not None:
        m.passo(10) if m.procs[-1].fim is not None or not m.robo.rodando else m.terminar()
        if m.robo.semente["concentradas"]["t"] != partiu:
            break
    assert json.loads(g.read_text()) == {"versao": 4, "x": "regras novas"}
    assert m.robo.semente["concentradas"] == {"t": m.t, "versao": 4}


def test_laboratorio_travado_e_interrompido_e_o_motor_reiniciado_retoma(tmp_path):
    m = Mundo(tmp_path)
    m.passo()
    m.passo(G.TEMPO_MAX_S / 60 + 1)
    assert m.procs[0].morto and m.robo.labs["grade"]["ok"] is False and "interrompido" in m.robo.labs["grade"]["msg"]
    m.passo(0.1)
    assert m.chamadas[-1][0] == "cofres"
    m.robo.fechar()                                                              # o motor vai reiniciar com os cofres no meio
    assert m.procs[-1].morto
    m.robo = m.novo()
    assert m.robo.semente.keys() == {"grade", "cofres"}
    m.passo(0.2)
    assert m.chamadas[-1][0] == "cofres" and len(m.chamadas) == 3                # roda de novo, sem partir de novo
    assert m.robo.resumo(m.t)["rodando"] == "cofres"


def test_sem_estado_do_normal_espera(tmp_path):
    m = Mundo(tmp_path)
    (tmp_path / "lab" / "dados" / "grade_estado.json").unlink()
    m.passo()
    assert m.chamadas[0][0] == "cofres" and "grade" not in m.robo.semente


def test_uso_errado_nao_roda_nada():
    assert G.main([]) == 2 and G.main(["copia"]) == 2
