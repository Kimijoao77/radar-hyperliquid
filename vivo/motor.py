"""Motor em tempo real: o processo que fica ligado 24 h na máquina (VPS em Tóquio, perto da Hyperliquid).

Versão 1 (20/11/2026): só o sinal de vida. A cada minuto mede quanto a Hyperliquid demora para responder daqui e
grava saida/maquina.json; o vivo/atualizar.sh publica esse arquivo no repositório (o Nexus e quem cuida do projeto
sabem que a máquina está de pé e a que distância ela está da corretora). Os robôs em tempo real (copy, tendência,
pools concentradas) entram aqui como itens de ROBOS, cada um com um passo(agora_ms); tudo em simulação, sem chave e
sem ordem de verdade.

    python -m vivo.motor            # roda para sempre
    python -m vivo.motor --uma-vez  # uma batida só (conferência)
"""
from __future__ import annotations

import json
import os
import socket
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(os.environ.get("RADAR_RAIZ", Path(__file__).resolve().parent.parent))
INFO = "https://api.hyperliquid.xyz/info"
VERSAO = 1
BATIDA_S = 60
HORA = 3_600_000
GUARDAR = 24 * 60                 # amostras de latência guardadas (um dia)
ROBOS: list = []                  # os robôs em tempo real; cada um tem .nome e .passo(agora_ms) -> dict (resumo)


def agora_ms() -> int:
    return int(time.time() * 1000)


def medir_latencia(sessao, n: int = 3, relogio=time.perf_counter) -> float | None:
    """Quanto a Hyperliquid demora para responder uma consulta leve (ms, mediana de n). None se nenhuma respondeu."""
    tempos = []
    for _ in range(n):
        t0 = relogio()
        try:
            r = sessao.post(INFO, json={"type": "allMids"}, timeout=10)
            if r.status_code == 200:
                tempos.append((relogio() - t0) * 1000)
        except Exception:  # noqa: BLE001  (rede fora do ar: a batida registra a falha e segue)
            pass
    return round(statistics.median(tempos), 1) if tempos else None


def resumo_latencia(amostras: list[list], agora: int) -> dict:
    """amostras = [[t_ms, ms ou None]]. Volta a última, a mediana e a pior da última hora e quantas falharam."""
    hora = [a for a in amostras if a[0] > agora - HORA]
    boas = [a[1] for a in hora if a[1] is not None]
    return {"agora": amostras[-1][1] if amostras else None,
            "mediana_1h": round(statistics.median(boas), 1) if boas else None,
            "pior_1h": max(boas) if boas else None,
            "falhas_1h": len(hora) - len(boas)}


def gravar(caminho: Path, obj) -> None:
    """Grava inteiro ou não grava: escreve num arquivo ao lado e troca."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(caminho)


def batida(sessao, estado: dict, agora: int | None = None) -> dict:
    """Uma volta do motor: mede a latência, roda os robôs e devolve o que vai em saida/maquina.json."""
    agora = agora or agora_ms()
    estado.setdefault("ligado_desde", agora)
    amostras = estado.setdefault("amostras", [])
    amostras.append([agora, medir_latencia(sessao)])
    del amostras[:-GUARDAR]
    robos = []
    for r in ROBOS:
        try:
            robos.append({"nome": r.nome, **(r.passo(agora) or {})})
        except Exception as e:  # noqa: BLE001  (um robô com erro não derruba os outros nem o sinal de vida)
            robos.append({"nome": getattr(r, "nome", "?"), "erro": str(e)[:200]})
    return {"versao": VERSAO, "maquina": socket.gethostname(), "modo": "simulação (sem dinheiro, sem chave)",
            "ligado_desde": estado["ligado_desde"], "batida": agora,
            "batida_txt": datetime.fromtimestamp(agora / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "latencia_ms": resumo_latencia(amostras, agora), "robos": robos}


def main(argv: list[str] | None = None) -> int:
    import requests
    argv = sys.argv[1:] if argv is None else argv
    sessao, estado = requests.Session(), {}
    saida = RAIZ / "saida" / "maquina.json"
    while True:
        inicio = time.monotonic()
        try:
            gravar(saida, batida(sessao, estado))
        except Exception as e:  # noqa: BLE001
            print(f"batida falhou: {e}", flush=True)
        if "--uma-vez" in argv:
            print(saida.read_text(encoding="utf-8") if saida.exists() else "sem saída")
            return 0
        time.sleep(max(1.0, BATIDA_S - (time.monotonic() - inicio)))


if __name__ == "__main__":
    sys.exit(main())
