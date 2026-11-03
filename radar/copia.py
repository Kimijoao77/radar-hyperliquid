"""Números para copiar (e para projetar a cópia) no Nexus.

Nada aqui opera. Gera, para cada carteira:
- o resultado de cada dia (US$), para o app simular "se eu tivesse copiado desde tal dia" e projetar o futuro
  sorteando dias do passado (Monte Carlo);
- o saldo de referência da conta (para transformar o resultado do dia em % da conta);
- quanto do lucro vem de operações que duram mais que um atraso (o que sobra para quem copia atrasado);
- giro por dia e taxa média (o custo extra de copiar);
- a alavancagem: a configurada nas posições e a exposição real (posições abertas ÷ saldo), pelas fotos da conta.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import median

from .trades import Operacao

BRT = timezone(timedelta(hours=-3))
LIMIARES_S = [5, 30, 120, 600]   # atrasos testados (segundos)
DIAS_MAX = 150


def _dia(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, BRT).date().isoformat()


def _q(v: list[float], p: float) -> float:
    s = sorted(v)
    return s[min(len(s) - 1, int(p * (len(s) - 1) + 0.5))]


def perfil_copia(ops: list[Operacao], fotos: list[dict] | None, conta_entrada: float | None, agora_ms: int) -> dict:
    fs = [o for o in ops if o.fechada and not o.parcial]
    fotos = fotos or []
    # saldo de referência: o maior entre a mediana das fotos e o saldo ao entrar no radar (quem saca dinheiro
    # fica com saldo pequeno e o lucro antigo pareceria enorme em %; o maior deixa a % mais conservadora)
    vs = [f["v"] for f in fotos if f.get("v", 0) > 0]
    cands = [x for x in (median(vs) if vs else None, conta_entrada) if x]
    conta = round(max(cands), 2) if cands else None

    out: dict = {"conta_ref": conta}
    # alavancagem
    exp = [f["ntl"] / f["v"] for f in fotos if f.get("v", 0) > 0 and f.get("ntl", 0) > 0]
    conf = [p[3] for f in fotos for p in f.get("pos", []) if len(p) > 3 and p[3]]
    com_saldo = [f for f in fotos if f.get("v", 0) > 0]
    out["alavancagem"] = {
        "exposicao_mediana": round(median(exp), 2) if exp else None,
        "exposicao_p90": round(_q(exp, 0.9), 2) if exp else None,
        "exposicao_max": round(max(exp), 2) if exp else None,
        "configurada_mediana": round(median(conf), 1) if conf else None,
        "configurada_max": max(conf) if conf else None,
        "posicionado": round(sum(1 for f in com_saldo if f.get("ntl", 0) > 0) / len(com_saldo), 3) if com_saldo else None,
        "fotos": len(fotos),
    }
    if not fs:
        return out

    # resultado por dia (horário de Brasília), dias sem operação = 0
    por_dia: dict[str, float] = {}
    for o in fs:
        d = _dia(o.t1)
        por_dia[d] = por_dia.get(d, 0.0) + o.resultado
    fim = datetime.fromtimestamp(agora_ms / 1000, BRT).date()
    ini = max(min(datetime.fromisoformat(d).date() for d in por_dia), fim - timedelta(days=DIAS_MAX - 1))
    dias = [(ini + timedelta(days=i)).isoformat() for i in range((fim - ini).days + 1)]
    out["dia0"] = dias[0]
    out["pnl_dia"] = [round(por_dia.get(d, 0.0), 2) for d in dias]

    # o que sobra para quem copia atrasado: lucro das operações que duram mais que o atraso
    total = sum(o.resultado for o in fs)
    out["total"] = round(total, 2)
    out["por_atraso"] = {str(s): {"resultado": round(sum(o.resultado for o in fs if o.duracao_min * 60 >= s), 2),
                                  "n": sum(1 for o in fs if o.duracao_min * 60 >= s)} for s in LIMIARES_S}
    # custo: giro e taxa
    noc = sum(o.nocional_max for o in fs)
    t0, t1 = min(o.t0 for o in fs), max(o.t1 for o in fs)
    ndias = max(1.0, (t1 - t0) / 86400000)
    out["giro_dia"] = round(noc / ndias, 2)                       # US$ abertos por dia (soma das posições)
    out["taxa_lado"] = round(sum(o.taxas for o in fs) / (2 * noc), 6) if noc else None
    out["n"] = len(fs)
    return out
