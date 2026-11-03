"""Análise (roda depois de cada coleta): monta as operações, mede, testa sorte x habilidade,
descreve o estilo e grava saida/relatorio.json (o Nexus lê esse arquivo) e saida/relatorio.md.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone

from radar import armazenamento as A
from radar.estilo import impressao
from radar.operador import CRITERIOS, avaliar as avaliar_operador
from radar.metricas import benjamini_hochberg, classificar, copiavel, numeros
from radar.trades import montar

ORDEM = {"habilidade": 0, "promissora": 1, "observando": 2, "sorte": 3, "perdendo": 4}
NOMES = {"habilidade": "Habilidade provável", "promissora": "Promissora", "observando": "Em observação",
         "sorte": "Sorte provável", "perdendo": "Perdendo"}
DIA_MS = 86400000


def reduzir(curva: list, pontos: int = 60) -> list:
    if len(curva) <= pontos:
        return curva
    passo = len(curva) / pontos
    return [curva[int(i * passo)] for i in range(pontos - 1)] + [curva[-1]]


def main() -> int:
    cfg = A.ler_json(A.RAIZ / "config.json", {})
    cc, cp = cfg["classificacao"], cfg["copiavel"]
    lista = A.ler_json(A.DADOS / "carteiras.json", {})
    est = A.ler_json(A.DADOS / "estado.json", {})
    fotos = A.ler_fotos()
    agora = A.agora_ms()

    base = {}
    for a, c in lista.items():
        fills = A.ler_fills(a)
        if not fills:
            continue
        ops = montar(fills)
        desde = c.get("desde", 0)
        geral = numeros(ops)
        antes = numeros([o for o in ops if o.t1 is not None and o.t1 < desde])
        depois = numeros([o for o in ops if o.t0 >= desde])
        base[a] = (c, ops, geral, antes, depois, copiavel(geral, cp), avaliar_operador(fills))

    # q-valores só entre as que dá para julgar (assim o "desconto" é justo)
    ps = {a: b[2]["p"] for a, b in base.items() if b[2].get("n", 0) >= cc["min_operacoes"]}
    qs = benjamini_hochberg(ps) if ps else {}

    saida = []
    for a, (c, ops, geral, antes, depois, ok, operador) in base.items():
        classe, motivo = classificar(geral, depois, qs.get(a), cc)
        dias_obs = (agora - c.get("desde", agora)) / DIA_MS
        # libera a vaga: não copiáveis na hora; perdedoras e sortudas depois de um tempo observando
        if c.get("situacao") == "observando":
            if classe in ("perdendo", "sorte") and dias_obs >= cc["dias_para_descartar"]:
                c["situacao"], c["descartada_em"], c["motivo"] = "descartada", agora, motivo
        nd = depois.get("n", 0)
        nota = (geral.get("t", 0) or 0) + (depois.get("t", 0) if nd >= 10 else 0)
        recentes = [o.resumo() for o in sorted([o for o in ops if o.fechada and not o.parcial], key=lambda o: o.t1)[-15:]]
        abertas = [o.resumo() for o in ops if not o.fechada and not o.parcial][-5:]
        f = fotos.get(a, [])
        saida.append({
            "carteira": a, "apelido": c.get("apelido", ""), "situacao": c.get("situacao"), "desde": c.get("desde_data"),
            "dias_observada": round(dias_obs, 1), "classe": classe, "classe_nome": NOMES[classe], "motivo": motivo,
            "q": round(qs[a], 4) if a in qs else None, "nota": round(nota, 2),
            "saldo": f[-1]["v"] if f else c.get("na_entrada", {}).get("conta"),
            "na_entrada": c.get("na_entrada", {}),
            "geral": {k: v for k, v in geral.items() if k != "curva"},
            "antes": {k: v for k, v in antes.items() if k != "curva"},
            "depois": {k: v for k, v in depois.items() if k != "curva"},
            "curva": reduzir(geral.get("curva", [])),
            "estilo": impressao(ops, f),
            "operador": operador,
            "copiavel": {"ok": ok[0], "motivo": ok[1]},
            "recentes": recentes, "abertas": abertas,
        })
    saida.sort(key=lambda s: (ORDEM[s["classe"]], -s["nota"]))
    cont = {}
    for s in saida:
        cont[s["classe"]] = cont.get(s["classe"], 0) + 1
    rel = {
        "gerado": agora,
        "gerado_txt": datetime.fromtimestamp(agora / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "observando": sum(1 for c in lista.values() if c.get("situacao") == "observando"),
        "descartadas": sum(1 for c in lista.values() if c.get("situacao") == "descartada"),
        "por_classe": cont, "nomes": NOMES,
        "ultimo_filtro": est.get("ultimo_filtro"), "ultima_coleta": est.get("ultima_coleta"),
        "carteiras": saida,
        "config": {k: v for k, v in cfg.items() if not k.startswith("_")},
        "criterios_operador": CRITERIOS,
    }
    A.gravar_json(A.SAIDA / "relatorio.json", rel)
    A.gravar_json(A.DADOS / "carteiras.json", lista)
    (A.SAIDA / "relatorio.md").write_text(markdown(rel), encoding="utf-8")
    print(f"análise: {len(saida)} carteiras com dados; " + ", ".join(f"{NOMES[k]}: {v}" for k, v in sorted(cont.items(), key=lambda kv: ORDEM[kv[0]])))
    return 0


def markdown(rel: dict) -> str:
    l = [f"# Radar Hyperliquid — {rel['gerado_txt']}", "",
         f"Observando {rel['observando']} carteiras ({rel['descartadas']} já descartadas).", ""]
    for s in rel["carteiras"][:40]:
        g = s["geral"]
        l.append(f"- **{s['classe_nome']}** `{s['carteira']}` {s['apelido']} — {g.get('n', 0)} operações, "
                 f"resultado US$ {g.get('resultado', 0):,.0f}, acerto {100 * g.get('acerto', 0):.0f} %, q = {s['q']}. {s['motivo']}")
    return "\n".join(l) + "\n"


if __name__ == "__main__":
    sys.exit(main())
