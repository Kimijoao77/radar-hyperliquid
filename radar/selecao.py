"""Pré-filtro do leaderboard e lista de observação.

A ideia do vídeo: olhar milhares de carteiras, separar poucas que valem a pena e acompanhar.
Aqui o pré-filtro só usa o que o leaderboard já traz (saldo, PnL, ROI e volume por janela),
sem gastar consultas. O teste de verdade (sorte x habilidade) vem depois, nos fills.
"""
from __future__ import annotations

from datetime import datetime, timezone


def janelas(linha: dict) -> dict:
    out = {}
    for nome, v in linha.get("windowPerformances") or []:
        out[nome] = {k: float(v.get(k) or 0) for k in ("pnl", "roi", "vlm")}
    return out


def avaliar_linha(linha: dict, f: dict) -> tuple[bool, str, float]:
    """(passa, motivo se não passa, nota para ordenar)."""
    conta = float(linha.get("accountValue") or 0)
    j = janelas(linha)
    mes, sem, tot = j.get("month", {}), j.get("week", {}), j.get("allTime", {})
    if conta < f["conta_minima"]:
        return False, "conta pequena", 0
    if mes.get("vlm", 0) < f["volume_mes_minimo"]:
        return False, "pouco volume no mês", 0
    roi = mes.get("roi", 0)
    if roi < f["roi_mes_minimo"]:
        return False, "ROI do mês baixo", 0
    if roi > f["roi_mes_maximo"]:
        return False, "ROI do mês alto demais (cara de aposta única)", 0
    if f.get("exigir_pnl_total_positivo") and tot.get("pnl", 0) <= 0:
        return False, "prejuízo no total", 0
    giro = mes.get("vlm", 0) / conta if conta else 0
    if giro > f["giro_mes_maximo"]:
        return False, "giro altíssimo (market maker ou robô de alta frequência)", 0
    # nota: ROI do mês pesa mais, semana confirma, total (limitado) mostra histórico
    nota = 0.5 * min(roi, 1.5) + 0.2 * max(-0.5, min(sem.get("roi", 0), 0.5)) + 0.3 * max(-1, min(tot.get("roi", 0), 3)) / 3
    return True, "", nota


def candidatas(linhas: list[dict], f: dict) -> tuple[list[tuple[float, dict]], dict]:
    """Linhas que passam no filtro, da melhor para a pior, e a contagem dos motivos de corte."""
    ok, motivos = [], {}
    for l in linhas:
        passa, motivo, nota = avaliar_linha(l, f)
        if passa:
            ok.append((nota, l))
        else:
            motivos[motivo] = motivos.get(motivo, 0) + 1
    ok.sort(key=lambda x: -x[0])
    return ok, motivos


def atualizar_lista(lista: dict, linhas: list[dict], cfg: dict, hoje_ms: int) -> dict:
    """Coloca carteiras novas na observação até o limite. Devolve um resumo do que fez."""
    ok, motivos = candidatas(linhas, cfg["filtro"])
    ativas = [a for a, c in lista.items() if c.get("situacao") == "observando"]
    vagas = max(0, cfg["max_carteiras"] - len(ativas))
    novas = 0
    data = datetime.fromtimestamp(hoje_ms / 1000, timezone.utc).strftime("%Y-%m-%d")
    for nota, l in ok:
        if novas >= min(vagas, cfg["novas_por_dia"]):
            break
        a = l["ethAddress"].lower()
        if a in lista:
            continue
        j = janelas(l)
        lista[a] = {
            "situacao": "observando", "desde": hoje_ms, "desde_data": data,
            "apelido": l.get("displayName") or "", "nota_entrada": round(nota, 4),
            "na_entrada": {"conta": round(float(l.get("accountValue") or 0), 2),
                           **{f"{k}_{c}": round(v[c], 4) for k, v in j.items() for c in ("pnl", "roi")}},
        }
        novas += 1
    # apelido pode mudar
    por_end = {l["ethAddress"].lower(): l for l in linhas}
    for a, c in lista.items():
        if a in por_end and por_end[a].get("displayName"):
            c["apelido"] = por_end[a]["displayName"]
    return {"leaderboard": len(linhas), "passaram": len(ok), "novas": novas, "ativas": len(ativas) + novas, "cortes": motivos}
