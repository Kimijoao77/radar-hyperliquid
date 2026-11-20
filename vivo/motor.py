"""Motor em tempo real: o processo que fica ligado 24 h na máquina (VPS em Tóquio, perto da Hyperliquid).

Sinal de vida (versão 1, 20/11/2026): a cada minuto mede quanto a Hyperliquid demora para responder daqui e grava
saida/maquina.json; o vivo/atualizar.sh publica esse arquivo no repositório (o Nexus e quem cuida do projeto sabem que
a máquina está de pé e a que distância ela está da corretora).

Robôs em tempo real (versão 2, 20/11/2026): cada item de ROBOS tem .nome, .passo(agora_ms) (chamado várias vezes por
segundo: o robô decide quando é hora de agir), .resumo(agora_ms) (o que aparece no sinal de vida) e, se quiser,
.fechar() (guardar o estado quando o motor é desligado). São dois: o copy trading em tempo real (vivo/copia.py) e os
gêmeos dos outros laboratórios (vivo/gemeos.py, versão 3). Tudo em simulação, sem chave e sem ordem de verdade.

    python -m vivo.motor            # roda para sempre
    python -m vivo.motor --uma-vez  # uma batida só (conferência)
"""
from __future__ import annotations

import json
import os
import signal
import socket
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(os.environ.get("RADAR_RAIZ", Path(__file__).resolve().parent.parent))
INFO = "https://api.hyperliquid.xyz/info"
VERSAO = 3
BATIDA_S = 60
TIQUE_S = 0.25                    # de quanto em quanto tempo os robôs são chamados
HORA = 3_600_000
GUARDAR = 24 * 60                 # amostras de latência guardadas (um dia)
ROBOS: list = []                  # os robôs em tempo real (ver o texto do começo)


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


def montar_robos(raiz: Path) -> list:
    """Os robôs desta máquina. Consultas com uma tentativa só e poucos segundos de espera: quem opera ao vivo não
    pode ficar parado esperando uma resposta."""
    from radar.api import Hyperliquid
    from vivo.copia import CopiaAoVivo
    from vivo.gemeos import Gemeos
    api = Hyperliquid(850, tentativas=1, timeout=5)     # o resto do limite (1200 por IP) fica para os laboratórios gêmeos
    return [CopiaAoVivo(raiz, api, agora_ms), Gemeos(raiz, agora_ms)]


def girar(estado: dict, agora: int | None = None) -> None:
    """Chama o passo de cada robô. Um robô com erro não derruba os outros nem o sinal de vida: o erro fica anotado."""
    agora = agora or agora_ms()
    erros = estado.setdefault("erros", {})
    for r in ROBOS:
        try:
            r.passo(agora)
            erros.pop(r.nome, None)
        except Exception as e:  # noqa: BLE001
            erros[getattr(r, "nome", "?")] = f"{type(e).__name__}: {e}"[:200]


def batida(sessao, estado: dict, agora: int | None = None) -> dict:
    """A volta de um minuto: mede a latência e devolve o que vai em saida/maquina.json (com o resumo dos robôs)."""
    agora = agora or agora_ms()
    estado.setdefault("ligado_desde", agora)
    amostras = estado.setdefault("amostras", [])
    amostras.append([agora, medir_latencia(sessao)])
    del amostras[:-GUARDAR]
    robos = []
    for r in ROBOS:
        nome = getattr(r, "nome", "?")
        try:
            item = {"nome": nome, **(r.resumo(agora) or {})}
        except Exception as e:  # noqa: BLE001
            item = {"nome": nome, "erro": f"{type(e).__name__}: {e}"[:200]}
        if estado.get("erros", {}).get(nome):
            item["erro"] = estado["erros"][nome]
        robos.append(item)
    return {"versao": VERSAO, "maquina": socket.gethostname(), "modo": "simulação (sem dinheiro, sem chave)",
            "ligado_desde": estado["ligado_desde"], "batida": agora,
            "batida_txt": datetime.fromtimestamp(agora / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "latencia_ms": resumo_latencia(amostras, agora), "robos": robos}


def main(argv: list[str] | None = None) -> int:
    import requests
    argv = sys.argv[1:] if argv is None else argv
    sessao, estado = requests.Session(), {}
    saida = RAIZ / "saida" / "maquina.json"
    try:
        ROBOS.extend(montar_robos(RAIZ))
    except Exception as e:  # noqa: BLE001  (sem robôs, o sinal de vida continua e mostra o erro)
        estado["erros"] = {"motor": f"robôs não subiram: {type(e).__name__}: {e}"[:200]}
        print(estado["erros"]["motor"], flush=True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))      # o systemd desliga assim: sai pelo finally
    proxima = 0.0
    try:
        while True:
            girar(estado)
            if time.monotonic() >= proxima:
                proxima = time.monotonic() + BATIDA_S
                try:
                    gravar(saida, batida(sessao, estado))
                except Exception as e:  # noqa: BLE001
                    print(f"batida falhou: {e}", flush=True)
                if "--uma-vez" in argv:
                    print(saida.read_text(encoding="utf-8") if saida.exists() else "sem saída")
                    return 0
            time.sleep(TIQUE_S)
    finally:
        for r in ROBOS:
            try:
                getattr(r, "fechar", lambda: None)()
            except Exception as e:  # noqa: BLE001
                print(f"{getattr(r, 'nome', '?')}: não guardou o estado: {e}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
