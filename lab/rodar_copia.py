"""Roda a cópia fiel (lab/copia.py) de hora em hora: lê as carteiras do radar, os fills e as fotos de saldo que o
radar já coletou, busca as velas das moedas na Hyperliquid e grava saida/copia_fiel.json (o Nexus lê).
Estado em lab/dados/copia_estado.json (subcontas, curvas e as últimas ordens).

As subcontas andam juntas, hora cheia por hora cheia, até o agora: cada hora vira um ponto da curva (na primeira
rodada, que refaz os dias desde o começo, a curva já sai com a história inteira).
Quando as regras mudam (VERSAO), o estado guardado não vale mais e a cópia é refeita desde o começo."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from lab import copia as C  # noqa: E402

BRT = timezone(timedelta(hours=-3))
INICIO_PADRAO = "2026-11-03"          # o mesmo começo da cópia simulada do radar
DIA = 86_400_000
HORA = 3_600_000
LIMITE_1M = int(3.2 * DIA)            # a Hyperliquid guarda ~5000 velas por intervalo: 1 min cobre ~3,4 dias
MAX_LOG = 300
MAX_CURVA = 2000
VERSAO = 3                            # 2 (09/11): fills do mesmo instante em cadeia, sem HIP-3, curva de hora em hora
                                      # 3 (09/11): um copy trading só (o seletivo)
MAX_TERCEIROS = 0.8                   # carteira com mais que isso dos fills em mercados de terceiros fica de fora


def ms_do_dia(iso: str) -> int:
    return int(datetime.fromisoformat(iso).replace(tzinfo=BRT).timestamp() * 1000)


def reduzir(curva: list, n: int = 400) -> list:
    if len(curva) <= n:
        return curva
    passo = len(curva) / n
    return [curva[int(i * passo)] for i in range(n)] + [curva[-1]]


def buscar_velas(api, precos: C.Precos, moeda: str, de: int, ate: int, agora: int, falhas: dict) -> None:
    pedacos = []
    if de < agora - LIMITE_1M:
        pedacos.append(("5m", de, min(ate, agora - LIMITE_1M + 3_600_000)))
    pedacos.append(("1m", max(de, agora - LIMITE_1M), ate))
    for intervalo, a, b in pedacos:
        if b <= a:
            continue
        try:
            precos.juntar(moeda, api.velas(moeda, intervalo, a, b))
        except Exception as e:  # noqa: BLE001  (moeda sem velas: spot ou mercado de terceiros)
            falhas[moeda] = str(e)[:120]


def main(raiz: Path = RAIZ, api=None, agora: int | None = None) -> int:
    import os
    os.environ.setdefault("RADAR_RAIZ", str(raiz))
    from radar import armazenamento as A
    t_ini = time.monotonic()
    cfg = json.loads((raiz / "config.json").read_text(encoding="utf-8"))
    if api is None:
        from radar.api import Hyperliquid
        api = Hyperliquid(cfg.get("peso_por_minuto", 1000))
    agora = agora or int(time.time() * 1000)
    ate = (agora // C.MINUTO - 3) * C.MINUTO                      # velas já fechadas

    rel = A.ler_json(raiz / "saida" / "relatorio.json", {})
    no_radar = {c["carteira"]: c for c in rel.get("carteiras", [])}
    arq_est = raiz / "lab" / "dados" / "copia_estado.json"
    est = A.ler_json(arq_est, {})
    refeito = est.get("versao") != VERSAO
    if refeito:                                                     # regras novas: refaz desde o começo
        est = {"versao": VERSAO}
    est.setdefault("inicio", ms_do_dia(INICIO_PADRAO))
    vs = est.setdefault("variantes", {})
    ultimo_ate = est.get("ate") or est["inicio"]                    # até onde a rodada anterior chegou

    # quem cada variante segue: as carteiras do radar (as novas entram com subconta nova)
    fills = {w: A.ler_fills(w) for w in no_radar}
    for nome, var in C.VARIANTES.items():
        v = vs.setdefault(nome, {"subs": {}, "curva": [], "log": [], "pulos": {}, "fora": {}})
        for w, c in no_radar.items():
            if w in v["subs"]:
                continue
            ok, motivo = C.copiavel(c, var)
            terceiros = C.parte_terceiros(fills.get(w, []))
            if ok and terceiros > MAX_TERCEIROS:
                ok, motivo = False, (f"{round(100 * terceiros)} % das ordens em mercados de terceiros (xyz:…), "
                                     "que têm saldo separado: não dá para copiar na proporção certa")
            if not ok:
                v["fora"][w] = motivo
                continue
            v["fora"].pop(w, None)
            inicio = max(est["inicio"], ms_do_dia(c["desde"]) if c.get("desde") else est["inicio"])
            v["subs"][w] = C.nova_subconta(w, inicio, C.fator_de(c, var))

    # fills (já em eventos) e fotos que o radar coletou, e as moedas que precisam de preço
    for w in {w for v in vs.values() for w in v["subs"]} - set(fills):
        fills[w] = A.ler_fills(w)
    fotos = A.ler_fotos()
    evs = {nome: {w: C.eventos(fills.get(w, []), 0, var["atraso_s"] * 1000, fotos.get(w)) for w in vs[nome]["subs"]}
           for nome, var in C.VARIANTES.items()}
    precisa: dict[str, int] = {}
    for nome, v in vs.items():
        for w, sc in v["subs"].items():
            if not sc["vivo"]:
                continue
            for ev in evs[nome][w]:
                if ev["t"] > sc["ult"] and ev["exec"] <= ate:
                    precisa[ev["moeda"]] = min(precisa.get(ev["moeda"], ate), ev["t"])
            for m in sc["pos"]:
                precisa[m] = min(precisa.get(m, ate), ultimo_ate - HORA)
    precos, falhas = C.Precos(), {}
    for moeda, de in sorted(precisa.items()):
        buscar_velas(api, precos, moeda, de - 10 * C.MINUTO, ate, agora, falhas)

    # as subcontas andam juntas, hora cheia por hora cheia, até `ate`; cada hora vira um ponto da curva
    saldos = {w: C.Saldos(fotos.get(w, []), (no_radar.get(w, {}).get("copia") or {}).get("conta_ref"))
              for w in {w for v in vs.values() for w in v["subs"]}}
    marcos = list(range((ultimo_ate // HORA + 1) * HORA, ate, HORA)) + [ate]
    saida = {"gerado": agora, "gerado_txt": datetime.fromtimestamp(agora / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
             "inicio": est["inicio"], "ate": ate, "versao": VERSAO, "refeito": refeito, "taxa": C.TAXA,
             "escorregamento": C.ESCORREGA, "variantes": {}}
    for nome, var in C.VARIANTES.items():
        v = vs[nome]
        log = v["log"]
        for marco in marcos:
            for w, sc in v["subs"].items():
                if not sc["vivo"] or sc["inicio"] > marco:
                    continue
                if w not in no_radar:                               # saiu do radar: fecha e congela
                    C.fechar_tudo(sc, precos, marco, log, "saiu do radar")
                    sc.update(vivo=False, parou="saiu do radar", parou_em=marco, patrimonio=round(sc["colateral"], 2))
                    continue
                pulos = C.avancar(sc, fills.get(w, []), saldos[w], precos, var, marco, log, evs[nome][w])
                for kk, n in pulos.items():
                    v["pulos"][kk] = v["pulos"].get(kk, 0) + n
            ativas = [sc for sc in v["subs"].values() if sc["inicio"] <= marco]
            if ativas:
                v["curva"].append([marco, C.resumo(ativas)["retorno"]])
        v["curva"] = v["curva"][-MAX_CURVA:]
        r = C.resumo(list(v["subs"].values()))
        v["log"] = log[-MAX_LOG:]
        subs = []
        for w, sc in v["subs"].items():
            abertas = []
            for m, (q, a) in sc["pos"].items():
                p = precos.em(m, ate)
                abertas.append({"moeda": m, "lado": "long" if q > 0 else "short", "valor": round(abs(q) * (p or a), 2),
                                "resultado": round(q * ((p or a) - a), 2)})
            c = no_radar.get(w, {})
            subs.append({"w": w, "apelido": c.get("apelido", ""), "inicio": sc["inicio"], "retorno": round(sc["patrimonio"] / sc["capital"] - 1, 5),
                         "patrimonio": sc["patrimonio"], "vivo": sc["vivo"], "parou": sc["parou"], "parou_em": sc["parou_em"],
                         "ordens": sc["ordens"], "taxas": round(sc["taxas"], 2), "fator": round(sc["fator"], 3),
                         "expo_max": round(sc["expo_max"], 2), "abertas": abertas,
                         "classe": c.get("classe_nome", ""), "tipo": (c.get("operador") or {}).get("rotulo", ""),
                         "duracao_min": (c.get("geral") or {}).get("duracao_mediana_min")})
        subs.sort(key=lambda s: -s["retorno"])
        saida["variantes"][nome] = {"nome": var["nome"], "regras": {k: var[k] for k in var if k != "nome"}, **r,
                                     "curva": reduzir(v["curva"]), "subcontas": subs, "ordens_recentes": v["log"][-150:],
                                     "pulos": v["pulos"], "fora": [{"w": w, "motivo": m} for w, m in v["fora"].items()]}
    saida["sem_preco"] = falhas
    saida["coleta"] = {"moedas": len(precisa), "peso": getattr(getattr(api, "lim", None), "total", None), "segundos": round(time.monotonic() - t_ini)}
    est["ate"] = ate
    A.gravar_json(arq_est, est)
    (raiz / "saida").mkdir(exist_ok=True)
    (raiz / "saida" / "copia_fiel.json").write_text(json.dumps(saida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("cópia fiel: " + "; ".join(f"{k} {100 * x['retorno']:+.2f} % ({x['vivas']}/{x['carteiras']} vivas, {x['ordens']} ordens)"
                                      for k, x in saida["variantes"].items()) + f"; {len(precisa)} moedas, sem preço: {len(falhas)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
