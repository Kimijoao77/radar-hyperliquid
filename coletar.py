"""Coleta (roda no GitHub Actions de hora em hora).

1. Uma vez por semana: baixa o leaderboard, aplica o pré-filtro e monta a fila de triagem.
2. Para cada carteira no radar: baixa os fills novos e tira uma foto do saldo e das posições.
3. Triagem (com o tempo que sobrar): baixa os últimos 90 dias de cada carteira da fila e mede.
   Só entra no radar quem já é promissora; as outras são recusadas (e podem ser testadas de novo
   depois de 30 dias). Se o tempo acabar, a fila continua na próxima rodada.
"""
from __future__ import annotations

import sys
import time

from radar import armazenamento as A
from radar.api import Hyperliquid
from radar.metricas import benjamini_hochberg, classificar, numeros
from radar.selecao import entrar, montar_fila
from radar.trades import montar

DIA_MS = 86400000
ATIVAS = ("observando", "aprovada")
RECUSA = {"observando": "poucas operações em 90 dias", "perdendo": "no prejuízo", "sorte": "lucro de sorte (cabe no acaso ou vem de poucas tacadas)"}


def foto(api: Hyperliquid, a: str, agora: int) -> None:
    st = api.estado(a)
    ms = st.get("marginSummary") or {}
    pos = []
    for p in st.get("assetPositions") or []:
        q = p.get("position") or {}
        if float(q.get("szi") or 0):
            pos.append([q.get("coin"), float(q["szi"]), float(q.get("entryPx") or 0), (q.get("leverage") or {}).get("value")])
    A.anexar_foto({"t": agora, "a": a, "v": round(float(ms.get("accountValue") or 0), 2),
                   "ntl": round(float(ms.get("totalNtlPos") or 0), 2), "pos": pos})


def triar(api: Hyperliquid, item: dict, lista: dict, est: dict, cfg: dict, agora: int) -> tuple[bool, str]:
    """Mede uma candidata com os últimos 90 dias. Entra no radar só se for promissora."""
    a = item["a"]
    brutos = api.fills_desde(a, agora - cfg.get("dias_de_historico_ao_entrar", 90) * DIA_MS)
    fills = [A.compactar(f) for f in brutos]
    geral = numeros(montar(sorted(fills, key=lambda f: (f["t"], f.get("id") or 0))))
    ps = dict(est.get("ps", {}))
    q = None
    if geral.get("n", 0) >= cfg["classificacao"]["min_operacoes"]:
        ps[a] = geral["p"]
        q = benjamini_hochberg(ps)[a]
    classe, motivo = classificar(geral, {"n": 0}, q, cfg["classificacao"])
    if classe not in ("promissora", "habilidade"):
        lista[a] = {"situacao": "recusada", "em": agora, "motivo": motivo, "apelido": item.get("apelido", "")}
        return False, RECUSA[classe]
    entrar(lista, item, agora)
    A.anexar_fills(a, fills)
    e = est["carteiras"].setdefault(a, {})
    if fills:
        e["ultimo_t"] = max(f["t"] for f in fills)
    est.setdefault("ps", {})[a] = geral["p"]
    foto(api, a, agora)
    e["coletado_em"] = agora
    return True, motivo


def main(limite_min: float = 20.0) -> int:
    inicio = time.monotonic()
    cfg = A.ler_json(A.RAIZ / "config.json", {})
    lista = A.ler_json(A.DADOS / "carteiras.json", {})
    est = A.ler_json(A.DADOS / "estado.json", {"carteiras": {}})
    est.setdefault("carteiras", {})
    api = Hyperliquid(cfg.get("peso_por_minuto", 1000))
    agora = A.agora_ms()
    log = []
    tempo = lambda: time.monotonic() - inicio < limite_min * 60  # noqa: E731

    # 1. leaderboard e fila de triagem, uma vez por semana
    if "fila" not in est or agora - est.get("leaderboard_em", 0) > 7 * DIA_MS - 2 * 3600 * 1000:   # sem "fila": 1ª rodada do plano
        try:
            linhas = api.leaderboard()
            fila, r = montar_fila(lista, linhas, cfg, agora)
            est["leaderboard_em"] = agora
            est["fila"] = fila
            est["ultimo_filtro"] = r
            est["triagem"] = {"inicio": agora, "testadas": 0, "entraram": 0, "recusas": {}}
            log.append(f"leaderboard: {r['leaderboard']} carteiras, {r['passaram']} passaram no filtro, {len(fila)} na fila de triagem")
        except Exception as e:  # noqa: BLE001
            log.append(f"leaderboard falhou: {e}")

    # 2. fills e fotos das carteiras no radar: primeiro as que estão há mais tempo sem coleta
    ativas = [a for a, c in lista.items() if c.get("situacao") in ATIVAS]
    ativas.sort(key=lambda a: est["carteiras"].get(a, {}).get("coletado_em", 0))
    feitas = erros = novos_total = 0
    for a in ativas:
        if not tempo():
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
            foto(api, a, agora)
            e["coletado_em"] = agora
            feitas += 1
        except Exception as ex:  # noqa: BLE001
            erros += 1
            e["erro"] = str(ex)[:200]

    # 3. triagem das novas (com o tempo que sobrar)
    tr = est.setdefault("triagem", {"testadas": 0, "entraram": 0, "recusas": {}})
    fila = est.get("fila", [])
    while fila and tempo():
        if sum(1 for c in lista.values() if c.get("situacao") in ATIVAS) >= cfg["max_carteiras"]:
            log.append("radar cheio: a triagem espera vaga")
            break
        item = fila.pop(0)
        try:
            ok, motivo = triar(api, item, lista, est, cfg, agora)
        except Exception as ex:  # noqa: BLE001
            log.append(f"triagem de {item['a'][:10]} falhou: {str(ex)[:120]}")
            continue
        tr["testadas"] += 1
        if ok:
            tr["entraram"] += 1
        else:
            tr["recusas"][motivo] = tr["recusas"].get(motivo, 0) + 1
    est["fila"] = fila

    est["ultima_coleta"] = {"em": agora, "carteiras": feitas, "erros": erros, "fills_novos": novos_total,
                            "peso_gasto": api.lim.total, "minutos": round((time.monotonic() - inicio) / 60, 1),
                            "fila": len(fila)}
    A.gravar_json(A.DADOS / "carteiras.json", lista)
    A.gravar_json(A.DADOS / "estado.json", est)
    log.append(f"coleta: {feitas} carteiras, {novos_total} fills novos, {erros} erros; triagem: {tr['testadas']} testadas, "
               f"{tr['entraram']} entraram, {len(fila)} na fila; peso {api.lim.total}")
    print("\n".join(log))
    return 0


if __name__ == "__main__":
    sys.exit(main(float(sys.argv[1]) if len(sys.argv) > 1 else 20.0))
