"""O motor da máquina 24 h (vivo/motor.py): sinal de vida e latência, sem rede."""
import json

from vivo import motor as M


class Resp:
    def __init__(self, codigo=200):
        self.status_code = codigo


class Sessao:
    """Finge a Hyperliquid: cada chamada "demora" o próximo valor da lista (ms); None = a rede caiu."""

    def __init__(self, demoras):
        self.demoras, self.t, self.chamadas = list(demoras), 0.0, 0

    def post(self, url, json=None, timeout=None):  # noqa: A002
        self.chamadas += 1
        d = self.demoras.pop(0)
        if d is None:
            raise OSError("sem rede")
        self.t += d / 1000
        return Resp()

    def relogio(self):
        return self.t


def test_latencia_e_a_mediana_das_respostas():
    s = Sessao([10, 300, 20])
    assert M.medir_latencia(s, 3, s.relogio) == 20.0
    s = Sessao([None, 50, None])
    assert M.medir_latencia(s, 3, s.relogio) == 50.0
    s = Sessao([None, None, None])
    assert M.medir_latencia(s, 3, s.relogio) is None


def test_resumo_so_olha_a_ultima_hora_e_conta_as_falhas():
    agora = 10 * M.HORA
    amostras = [[agora - 2 * M.HORA, 999.0], [agora - 1000, 12.0], [agora - 500, None], [agora, 30.0]]
    assert M.resumo_latencia(amostras, agora) == {"agora": 30.0, "mediana_1h": 21.0, "pior_1h": 30.0, "falhas_1h": 1}
    assert M.resumo_latencia([], agora) == {"agora": None, "mediana_1h": None, "pior_1h": None, "falhas_1h": 0}


def test_batida_guarda_desde_quando_esta_ligado_e_um_robo_com_erro_nao_derruba(monkeypatch):
    class Bom:
        nome = "bom"

        def passo(self, agora):
            return {"ordens": 3}

    class Ruim:
        nome = "ruim"

        def passo(self, agora):
            raise RuntimeError("quebrou")

    monkeypatch.setattr(M, "ROBOS", [Bom(), Ruim()])
    monkeypatch.setattr(M, "medir_latencia", lambda sessao: 5.0)
    est = {}
    a = M.batida(None, est, 1_000_000)
    b = M.batida(None, est, 1_060_000)
    assert a["ligado_desde"] == b["ligado_desde"] == 1_000_000 and b["batida"] == 1_060_000
    assert b["robos"] == [{"nome": "bom", "ordens": 3}, {"nome": "ruim", "erro": "quebrou"}]
    assert b["latencia_ms"]["agora"] == 5.0 and len(est["amostras"]) == 2
    assert "simulação" in b["modo"]


def test_gravar_troca_o_arquivo_inteiro(tmp_path):
    alvo = tmp_path / "saida" / "maquina.json"
    M.gravar(alvo, {"a": 1})
    M.gravar(alvo, {"a": 2})
    assert json.loads(alvo.read_text(encoding="utf-8")) == {"a": 2}
    assert not list(alvo.parent.glob("*.tmp"))
