"""Coleta (roda no GitHub Actions a cada poucas horas).

1. Uma vez por dia: baixa o leaderboard, aplica o pré-filtro e põe carteiras novas na observação.
2. Para cada carteira observada: baixa os fills novos e tira uma foto do saldo e das posições.
   Na primeira vez, baixa o histórico dos últimos dias (config: dias_de_historico_ao_entrar).
Se o tempo acabar, para e continua de onde parou na próxima rodada.
"""
from __future__ import annotations

import sys
import time

from radar import armazenamento as A
from radar.api import Hyperliquid
from radar.selecao import atualizar_lista

DIA_MS = 86400000


def main(limite_min: float = 20.0) -> int:
    inicio = time.monotonic()
    cfg = A.ler_json(A.RAIZ / "config.json", {})
    lista = A.ler_json(A.DADOS / "carteiras.json", {})
    est = A.ler_json(A.DADOS / "estado.json", {"carteiras": {}})
    est.setdefault("carteiras", {})
    api = Hyperliquid(cfg.get("peso_por_minuto", 1000))
    agora = A.agora_ms()
    log = []

    # 1. leaderboard e pré-filtro, uma vez por dia
    if agora - est.get("leaderboard_em", 0) > 20 * 3600 * 1000:
        try:
            linhas = api.leaderboard()
            r = atualizar_lista(lista, linhas, cfg, agora)
            est["leaderboard_em"] = agora
            est["ultimo_filtro"] = r
            log.append(f"leaderboard: {r['leaderboard']} carteiras, {r['passaram']} passaram no filtro, {r['novas']} novas na observação ({r['ativas']} ativas)")
            A.gravar_json(A.DADOS / "carteiras.json", lista)
        except Exception as e:  # noqa: BLE001
            log.append(f"leaderboard falhou: {e}")

    # 2. fills e fotos: primeiro as que estão há mais tempo sem coleta
    ativas = [a for a, c in lista.items() if c.get("situacao") == "observando"]
    ativas.sort(key=lambda a: est["carteiras"].get(a, {}).get("coletado_em", 0))
    feitas = erros = novos_total = 0
    for a in ativas:
        if time.monotonic() - inicio > limite_min * 60:
            log.append("tempo esgotado: o resto fica para a próxima rodada")
            break
        e = est["carteiras"].setdefault(a, {})
        desde = e.get("ultimo_t", 0) + 1 if e.get("ultimo_t") else agora - cfg.get("dias_de_historico_ao_entrar", 90) * DIA_MS
        try:
            fills = [A.compactar(f) for f in api.fills_desde(a, desde)]
            novos = A.anexar_fills(a, fills)
            if fills:
                e["ultimo_t"] = max(f["t"] for f in fills)
            novos_total += novos
            st = api.estado(a)
            ms = st.get("marginSummary") or {}
            pos = []
            for p in st.get("assetPositions") or []:
                q = p.get("position") or {}
                if float(q.get("szi") or 0):
                    pos.append([q.get("coin"), float(q["szi"]), float(q.get("entryPx") or 0), (q.get("leverage") or {}).get("value")])
            A.anexar_foto({"t": agora, "a": a, "v": round(float(ms.get("accountValue") or 0), 2),
                           "ntl": round(float(ms.get("totalNtlPos") or 0), 2), "pos": pos})
            e["coletado_em"] = agora
            feitas += 1
        except Exception as ex:  # noqa: BLE001
            erros += 1
            e["erro"] = str(ex)[:200]
    est["ultima_coleta"] = {"em": agora, "carteiras": feitas, "erros": erros, "fills_novos": novos_total,
                            "peso_gasto": api.lim.total, "minutos": round((time.monotonic() - inicio) / 60, 1)}
    A.gravar_json(A.DADOS / "estado.json", est)
    log.append(f"coleta: {feitas} carteiras, {novos_total} fills novos, {erros} erros, peso {api.lim.total}")
    print("\n".join(log))
    return 0


if __name__ == "__main__":
    sys.exit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 20.0))
