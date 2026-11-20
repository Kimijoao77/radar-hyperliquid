"""Os gêmeos ao vivo dos laboratórios (pedido do João em 20/11/2026: "quero que faça com todos os investimentos" e
"que faça as mesmas ordens que faz no normal, para poder comparar").

Cada teste que roda de hora em hora no GitHub (o "normal") ganha um gêmeo na máquina 24 h: o MESMO código, partindo
do MESMO estado (uma cópia do estado do normal no instante da partida), mas rodando no ritmo da máquina e guardando o
estado e o resultado numa pasta só dele (vivo/gemeo/). Como o código e o ponto de partida são os mesmos, as ordens são
as mesmas; o que pode mudar é a hora em que cada decisão é tomada (minutos em vez de até uma hora ou mais).

O copy trading tem um gêmeo próprio, em tempo real de verdade (vivo/copia.py). Os outros rodam aqui:

  grade          robôs de grade, DCA, tendência e reversão. Decidem em velas de 1 hora já fechadas: o gêmeo roda logo
                 depois de cada hora cheia. As ordens e o resultado são iguais aos do normal por construção.
  cofres         depósitos nos cofres da Hyperliquid. O normal olha a cada 6 h; o gêmeo, de hora em hora.
  concentradas   pools concentradas da Meteora. O normal olha de hora em hora; o gêmeo, a cada 10 minutos (sai e
                 reabre mais cedo).
  listagens      venda de moeda recém-listada (refeita das velas a cada rodada): o gêmeo roda a cada 30 minutos.
  previsoes      mercados de previsão do Polymarket. A regra limita as apostas novas por rodada, então o gêmeo mantém
                 o ritmo do normal (uma rodada a cada ~50 minutos) para fazer as mesmas apostas.

Um laboratório por vez, cada um num processo separado (se um travar ou quebrar, o motor e o copy trading continuam),
com um teto menor de consultas à Hyperliquid (RADAR_PESO_TETO), porque o limite dela é por IP.

    python -m vivo.gemeos grade     # roda um gêmeo uma vez (é o que o motor chama)

Arquivos (tudo dentro de vivo/gemeo/): lab/dados/*.json (estado), saida/*.json (resultado, mesmo formato do normal) e
gemeos.json (quando cada um partiu e como foi a última rodada; o Nexus lê).
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

CODIGO = Path(__file__).resolve().parent.parent
RAIZ = Path(os.environ.get("RADAR_RAIZ", CODIGO))
MIN = 60_000
PESO_TETO = 300               # peso por minuto dos laboratórios gêmeos na Hyperliquid (o copy trading usa o resto)
TEMPO_MAX_S = 20 * 60         # um laboratório que passar disso é interrompido
# cada_min: de quanto em quanto tempo o gêmeo é chamado. no_minuto: chamado uma vez por hora, nesse minuto (velas de
# 1 h fechadas). sem_espera: desliga o intervalo mínimo que o próprio laboratório tem (lab.sem_espera).
LABS = {
    "grade": {"no_minuto": 2, "sem_espera": False},
    "cofres": {"cada_min": 60, "sem_espera": True},
    "concentradas": {"cada_min": 10, "sem_espera": True},
    "listagens": {"cada_min": 30, "sem_espera": True},
    "previsoes": {"cada_min": 10, "sem_espera": False},
}


def pasta(raiz: Path) -> Path:
    return Path(raiz) / "vivo" / "gemeo"


def _ler(caminho: Path, padrao):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return padrao


def _gravar(caminho: Path, obj) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(caminho)


def versao_de(arq: Path):
    return (_ler(arq, {}) or {}).get("versao")


def semear(raiz: Path, lab: str) -> bool:
    """Copia o estado e o resultado do normal para a pasta do gêmeo. Volta False se o normal ainda não tem estado."""
    raiz, g = Path(raiz), pasta(raiz)
    estados = sorted((raiz / "lab" / "dados").glob(f"{lab}_*.json"))
    if not estados:
        return False
    (g / "lab" / "dados").mkdir(parents=True, exist_ok=True)
    (g / "saida").mkdir(parents=True, exist_ok=True)
    for arq in estados:
        shutil.copyfile(arq, g / "lab" / "dados" / arq.name)
    resultado = raiz / "saida" / f"{lab}.json"
    if resultado.exists():
        shutil.copyfile(resultado, g / "saida" / resultado.name)
    return True


def precisa_semear(raiz: Path, lab: str, semente: dict) -> bool:
    """Na primeira vez, e de novo quando as regras do normal mudam de versão (aí o normal recomeça, e o gêmeo com ele)."""
    if lab not in semente:
        return True
    normal = versao_de(Path(raiz) / "lab" / "dados" / f"{lab}_estado.json")
    return normal is not None and normal != versao_de(pasta(raiz) / "lab" / "dados" / f"{lab}_estado.json")


def devido(cfg: dict, ultima: int | None, agora: int) -> bool:
    """Está na hora de chamar o gêmeo? `ultima` = quando a última rodada começou."""
    if "no_minuto" in cfg:
        marca = agora // (60 * MIN) * (60 * MIN) + cfg["no_minuto"] * MIN     # o minuto certo desta hora
        return agora >= marca and (ultima or 0) < marca
    return ultima is None or agora - ultima >= cfg["cada_min"] * MIN


class Gemeos:
    nome = "gemeos"

    def __init__(self, raiz: Path, relogio, abrir=subprocess.Popen):
        self.raiz, self.relogio, self.abrir = Path(raiz), relogio, abrir
        self.arq = pasta(self.raiz) / "gemeos.json"
        est = _ler(self.arq, {})
        self.semente: dict = est.get("semente") or {}      # lab → {t, versao}
        self.labs: dict = est.get("labs") or {}            # lab → {inicio, fim, ok, msg, rodadas}
        self.rodando = None                                # (lab, processo, início, arquivo do registro)
        self.proximo = 0

    def passo(self, agora: int) -> None:
        if agora < self.proximo:
            return
        self.proximo = agora + 5000
        if self.rodando:
            lab, proc, inicio, log = self.rodando
            fim = proc.poll()
            if fim is None:
                if agora - inicio > TEMPO_MAX_S * 1000:
                    proc.kill()
                    self._terminou(lab, inicio, agora, False, f"passou de {TEMPO_MAX_S // 60} min: interrompido")
                return
            self._terminou(lab, inicio, agora, fim == 0, self._ultima_linha(log))
        for lab, cfg in LABS.items():
            if not devido(cfg, (self.labs.get(lab) or {}).get("inicio"), agora):
                continue
            if precisa_semear(self.raiz, lab, self.semente):
                if not semear(self.raiz, lab):
                    continue                                # o normal ainda não rodou: tenta na próxima
                self.semente[lab] = {"t": agora, "versao": versao_de(pasta(self.raiz) / "lab" / "dados" / f"{lab}_estado.json")}
            self._chamar(lab, cfg, agora)
            return                                          # um por vez

    def _chamar(self, lab: str, cfg: dict, agora: int) -> None:
        log = pasta(self.raiz) / "registros" / f"{lab}.txt"
        log.parent.mkdir(parents=True, exist_ok=True)
        amb = {**os.environ, "RADAR_PESO_TETO": str(PESO_TETO), "PYTHONUNBUFFERED": "1", "RADAR_RAIZ": str(self.raiz)}
        amb.pop("LAB_SEM_ESPERA", None)
        if cfg.get("sem_espera"):
            amb["LAB_SEM_ESPERA"] = "1"
        with log.open("w", encoding="utf-8") as h:
            # com prioridade baixa: a máquina tem um processador só, e o copy trading não pode esperar
            cmd = (["nice", "-n", "10"] if shutil.which("nice") else []) + [sys.executable, "-m", "vivo.gemeos", lab]
            proc = self.abrir(cmd, cwd=str(CODIGO), env=amb, stdout=h, stderr=subprocess.STDOUT)
        self.rodando = (lab, proc, agora, log)
        self.labs.setdefault(lab, {})["inicio"] = agora
        self._gravar(agora)

    def _ultima_linha(self, log: Path) -> str:
        try:
            linhas = [x for x in log.read_text(encoding="utf-8", errors="replace").splitlines() if x.strip()]
        except OSError:
            return ""
        return linhas[-1][:240] if linhas else ""

    def _terminou(self, lab: str, inicio: int, agora: int, ok: bool, msg: str) -> None:
        d = self.labs.setdefault(lab, {})
        d.update(inicio=inicio, fim=agora, ok=ok, msg=msg, rodadas=d.get("rodadas", 0) + 1)
        self.rodando = None
        self._gravar(agora)

    def _gravar(self, agora: int) -> None:
        _gravar(self.arq, {"gerado": agora, "semente": self.semente, "labs": self.labs,
                           "ritmo": {k: ({"no_minuto": v["no_minuto"]} if "no_minuto" in v else {"cada_min": v["cada_min"]})
                                     for k, v in LABS.items()}})

    def resumo(self, agora: int) -> dict:
        return {"rodando": self.rodando[0] if self.rodando else None,
                "labs": {lab: {"ha_min": round((agora - d["fim"]) / MIN) if d.get("fim") else None, "ok": d.get("ok")}
                         for lab, d in self.labs.items()}}

    def fechar(self) -> None:
        if self.rodando:
            try:
                self.rodando[1].terminate()                 # o estado do laboratório só é gravado no fim: nada fica pela metade
            except Exception:  # noqa: BLE001
                pass
            self.labs.get(self.rodando[0], {}).pop("inicio", None)   # volta a rodar assim que o motor subir
            self.rodando = None
        self._gravar(self.relogio())


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] not in LABS:
        print("uso: python -m vivo.gemeos <" + "|".join(LABS) + ">")
        return 2
    sys.path.insert(0, str(CODIGO))
    mod = importlib.import_module(f"lab.rodar_{argv[0]}")
    return int(mod.main(pasta(RAIZ)) or 0)


if __name__ == "__main__":
    sys.exit(main())
