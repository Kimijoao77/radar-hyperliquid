"""E se a máquina 24 h existisse desde o começo? (pedido do João em 20/11/2026: "tentar simular quanto seria se desde o
início tivéssemos nossa host"). Só leitura: não mexe no estado nem no resultado de nenhum teste.

Refaz a cópia fiel desde o começo (03/11) com os mesmos fills, as mesmas carteiras de hoje e as mesmas regras de cada
cópia, mudando só a execução:

  normal        o que o laboratório faz: a ordem sai `atraso_s` depois (60 s, ou 10 s na rápida), no preço da vela
                daquele instante, com 0,05 % de escorregamento
  host_vela     2 s depois, no preço da vela daquele instante (antes dos últimos 3 dias só há velas de 5 min, então
                esta conta enxerga pouco da diferença entre 2 s e 60 s)
  host          2 s depois, no preço que a própria carteira pegou (o do fill dela), com 0,05 % de escorregamento:
                o que a máquina faria se copiasse sem custo extra de atraso
  host_prudente o mesmo, com 0,20 % de escorregamento (perto do que a máquina mediu nas primeiras horas: a cópia saiu
                0,13 % a 0,18 % pior que a carteira)

Os quatro são refeitos do mesmo jeito (com as carteiras que estão no radar hoje), então dá para comparar entre eles. O
resultado guardado do teste normal (saida/copia_fiel.json) foi montado hora a hora, com as carteiras que estavam no
radar em cada momento, e por isso não é igual ao "normal" refeito aqui; ele vai junto, só como referência.

    python lab/simular_host.py        # grava saida/simulacao_host.json e imprime a tabela
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from lab import copia as C  # noqa: E402
from lab.rodar_copia import HORA, INICIO_PADRAO, MAX_TERCEIROS, buscar_velas, ms_do_dia, reduzir  # noqa: E402

ATRASO_HOST_S = 2
CENARIOS = {            # nome → (atraso em s; None = o da regra da cópia, preço "vela" ou "dela", escorregamento)
    "normal": (None, "vela", C.ESCORREGA),
    "host_vela": (ATRASO_HOST_S, "vela", C.ESCORREGA),
    "host": (ATRASO_HOST_S, "dela", C.ESCORREGA),
    "host_prudente": (ATRASO_HOST_S, "dela", 0.0020),
}


class PrecosDela:
    """Os preços das velas, menos na hora de executar uma ordem copiada: aí vale o preço que a carteira pegou."""

    def __init__(self, base: C.Precos):
        self.base, self.fixo = base, {}

    def em(self, moeda: str, t: int):
        return self.fixo.get((moeda, t)) or self.base.em(moeda, t)

    def ultimo(self, moeda: str, t: int):
        return self.base.ultimo(moeda, t)


def simular(no_radar: dict, fills: dict, fotos: dict, precos: C.Precos, var: dict, inicio: int, ate: int,
            atraso_s: int | None, preco: str, escorrega: float) -> dict:
    """Uma cópia do começo até `ate` num cenário de execução. Volta o resumo, a curva e o que foi pulado."""
    var = {**var, "atraso_s": var["atraso_s"] if atraso_s is None else atraso_s}
    subs = {}
    for w, c in no_radar.items():
        ok, _ = C.copiavel(c, var)
        if ok and C.parte_terceiros(fills.get(w, [])) > MAX_TERCEIROS:
            ok = False
        if ok:
            subs[w] = C.nova_subconta(w, max(inicio, ms_do_dia(c["desde"]) if c.get("desde") else inicio), C.fator_de(c, var))
    evs = {w: C.eventos(fills.get(w, []), 0, var["atraso_s"] * 1000, fotos.get(w)) for w in subs}
    px = precos
    if preco == "dela":
        px = PrecosDela(precos)
        for lista in evs.values():
            for ev in lista:
                if ev.get("px"):
                    px.fixo[(ev["moeda"], ev["exec"])] = ev["px"]
    saldos = {w: C.Saldos(fotos.get(w, []), (no_radar[w].get("copia") or {}).get("conta_ref")) for w in subs}
    pulos: dict[str, int] = {}
    curva = []
    guardado, C.ESCORREGA = C.ESCORREGA, escorrega
    try:
        for marco in list(range((inicio // HORA + 1) * HORA, ate, HORA)) + [ate]:
            for w, sc in subs.items():
                if not sc["vivo"] or sc["inicio"] > marco:
                    continue
                for k, n in C.avancar(sc, fills.get(w, []), saldos[w], px, var, marco, None, evs[w]).items():
                    pulos[k] = pulos.get(k, 0) + n
            ativas = [sc for sc in subs.values() if sc["inicio"] <= marco]
            if ativas:
                curva.append([marco, C.resumo(ativas)["retorno"]])
    finally:
        C.ESCORREGA = guardado
    r = C.resumo(list(subs.values()))
    return {**r, "paradas": sum(1 for s in subs.values() if s["parou"] and s["parou"].startswith("parada")),
            "pulos": pulos, "curva": reduzir(curva, 200)}


def main(raiz: Path = RAIZ, api=None, agora: int | None = None) -> int:
    import os
    os.environ.setdefault("RADAR_RAIZ", str(raiz))
    from radar import armazenamento as A
    t0 = time.monotonic()
    if api is None:
        from radar.api import Hyperliquid
        api = Hyperliquid(1000)
    agora = agora or int(time.time() * 1000)
    ate = (agora // C.MINUTO - 3) * C.MINUTO
    inicio = ms_do_dia(INICIO_PADRAO)
    rel = A.ler_json(raiz / "saida" / "relatorio.json", {})
    no_radar = {c["carteira"]: c for c in rel.get("carteiras", [])}
    fills = {w: A.ler_fills(w) for w in no_radar}
    fotos = A.ler_fotos()

    # as velas de todas as moedas que alguma carteira operou desde o começo (uma vez só, para todos os cenários)
    precisa: dict[str, int] = {}
    for w in no_radar:
        for f in fills[w]:
            if f["t"] > inicio and "z" in f and C.copiavel_mercado(f["c"]):
                precisa[f["c"]] = min(precisa.get(f["c"], ate), f["t"])
    precos, falhas = C.Precos(), {}
    for n, (moeda, de) in enumerate(sorted(precisa.items()), 1):
        buscar_velas(api, precos, moeda, de - 10 * C.MINUTO, ate, agora, falhas)
        if n % 20 == 0:
            print(f"velas: {n} de {len(precisa)} moedas ({time.monotonic() - t0:.0f} s)", flush=True)

    guardado = A.ler_json(raiz / "saida" / "copia_fiel.json", {})
    saida = {"gerado": agora, "gerado_txt": datetime.fromtimestamp(agora / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
             "inicio": inicio, "ate": ate, "atraso_host_s": ATRASO_HOST_S, "moedas": len(precisa), "sem_preco": falhas,
             "cenarios": {k: {"atraso_s": v[0], "preco": v[1], "escorregamento": v[2]} for k, v in CENARIOS.items()},
             "copias": {}}
    for nome, var in C.VARIANTES.items():
        linha = {"nome": var["nome"], "teste_guardado": (guardado.get("variantes") or {}).get(nome, {}).get("retorno")}
        for cen, (atraso, preco, esc) in CENARIOS.items():
            linha[cen] = simular(no_radar, fills, fotos, precos, var, inicio, ate, atraso, preco, esc)
        saida["copias"][nome] = linha
        print(f"{var['nome']}: " + "; ".join(f"{cen} {100 * linha[cen]['retorno']:+.2f} %" for cen in CENARIOS)
              + (f"; teste guardado {100 * linha['teste_guardado']:+.2f} %" if linha["teste_guardado"] is not None else ""), flush=True)
    (raiz / "saida").mkdir(exist_ok=True)
    (raiz / "saida" / "simulacao_host.json").write_text(json.dumps(saida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"simulação: {len(precisa)} moedas, sem preço: {len(falhas)}, {time.monotonic() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
