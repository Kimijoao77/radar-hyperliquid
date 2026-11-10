"""Roda o laboratório de grade, DCA, tendência e reversão: teste no passado (~200 dias de velas de 1 h) e ao vivo das
escolhidas. Desde a versão 4 as contas descontam o funding real da Hyperliquid (guardado em lab/dados/grade_funding.json)."""
from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from lab.grade import FAMILIAS, HORA, MEDIA_H, TODAS, escolher, familia, nome, nota_honesta, nota_lucro, rodar  # noqa: E402
from radar.api import Hyperliquid  # noqa: E402

# 10/11 (versão 6): mais 4 moedas entre as mais negociadas da Hyperliquid (kPEPE é memecoin: mais movimento e mais risco)
MOEDAS = ["BTC", "ETH", "SOL", "HYPE", "XRP", "AVAX", "kPEPE", "NEAR"]
VERSAO = 7          # 7 (10/11/2026): versão nova não zera mais os robôs ao vivo (cada um tem o próprio começo); os da versão 5 voltam
                    # 6 (10/11/2026): mais 4 moedas e a família reversão (3 ao vivo, só com nota > 0)
                    # 5 (10/11/2026): ao vivo não repete a mesma estratégia na mesma moeda com outra alavancagem (a versão 4 pôs HYPE 3× e 2× do mesmo sinal)
                    # 4 (10/11/2026): funding real nas contas e robôs de tendência (comprado e vendido); ao vivo 3 de grade/DCA + 3 de tendência
                    # 3 (10/11/2026): o máximo de lucro (pedido do João), com 2× e 3×; escolhe os 4 de maior lucro ao ano no pior dos dois pedaços do passado
                    # 2 (09/11/2026): só 1×, DCA com pausa na queda, escolha pela pior nota dentro/fora da amostra
REF_INICIO = 1793674800000   # 03/11/2026 00:00 em Brasília: o começo dos testes
ANTES = 700                  # velas de antes do começo de um pedaço, para as médias e os canais da tendência já valerem


def baixar_funding(api, moeda: str, desde: int, agora: int) -> dict[int, float]:
    """Funding pago por hora (fundingHistory, 500 por chamada): {hora_em_ms: taxa por hora}."""
    out, t = {}, int(desde)
    while t < agora:
        pag = api._post({"type": "fundingHistory", "coin": moeda, "startTime": t, "endTime": int(agora)}, 20) or []
        if hasattr(api, "lim"):
            api.lim.gastar(math.ceil(len(pag) / 20))
        for r in pag:
            out[int(r["time"]) // HORA * HORA] = float(r["fundingRate"])
        if len(pag) < 500:
            break
        t = max(int(r["time"]) for r in pag) + 1
    return out


def ler_funding(arq: Path) -> dict[str, dict[int, float]]:
    try:
        bruto = json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {m: {int(d["h0"]) + i * HORA: float(x) for i, x in enumerate(d.get("r", [])) if x is not None} for m, d in bruto.items()}


def gravar_funding(arq: Path, fund: dict[str, dict[int, float]]) -> None:
    bruto = {}
    for m, d in fund.items():
        if d:
            h0, h1 = min(d), max(d)
            bruto[m] = {"h0": h0, "r": [None if d.get(h0 + i * HORA) is None else round(d[h0 + i * HORA], 9) for i in range((h1 - h0) // HORA + 1)]}
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(bruto, separators=(",", ":")), encoding="utf-8")


def continuar(est: dict, versao: int) -> dict:
    """Versão nova não zera os robôs ao vivo (pedido do João em 10/11: "os robôs voltaram para o zero"): cada robô guarda
    o próprio começo e continua contando dele; a versão nova só escolhe robôs para as famílias que estiverem vazias.
    As contas do ao vivo saem das velas desde o começo de cada robô, então quem continua fica como se nunca tivesse parado.

    Uma vez só, vindo da versão 6: a troca da 5 para a 6 (10/11 às 19 h) zerou os robôs e guardou o resultado deles em
    "anterior". Esses robôs voltam do começo deles; das escolhas da versão 6 fica só a família que não estava ao vivo (a
    reversão)."""
    for e in est.get("escolhidas", []):
        e.setdefault("inicio", est.get("inicio"))
    if est.get("versao") == 6:
        ant = list(est.get("anterior") or [])
        de = max((a.get("de") or 0) for a in ant) if ant else 0
        lote = [a for a in ant if de and a.get("de") == de]
        por_nome = {(m, nome(c)): c for m in MOEDAS for c in TODAS}
        voltam = [{"moeda": a["moeda"], "config": por_nome[(a["moeda"], a["nome"])], "inicio": de} for a in lote if (a["moeda"], a["nome"]) in por_nome]
        if voltam:
            fams = {familia(v["config"]) for v in voltam}
            est["escolhidas"] = voltam + [e for e in est.get("escolhidas", []) if familia(e["config"]) not in fams]
            est["anterior"] = [a for a in ant if a not in lote]
    est["versao"] = versao
    return est


def _fechamentos(vs: list[dict]) -> list[float]:
    return [float(v["c"]) for v in vs]


def main(raiz: Path = RAIZ, api=None) -> int:
    api = api or Hyperliquid(1000)
    agora = int(time.time() * 1000)
    arq = raiz / "lab" / "dados" / "grade_estado.json"
    est = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    velas = {}
    for m in MOEDAS:
        vs = api.velas(m, "1h", agora - 5000 * HORA, agora)
        velas[m] = [v for v in vs if int(v["T"] if "T" in v else v["t"]) <= agora]   # só velas fechadas
        if velas[m] and int(velas[m][-1].get("T", velas[m][-1]["t"] + HORA)) > agora:
            velas[m] = velas[m][:-1]
        # números de uma vez (a API manda texto): as ~2.000 simulações por rodada não convertem o mesmo preço de novo
        velas[m] = [{"t": int(v["t"]), "o": float(v["o"]), "h": float(v["h"]), "l": float(v["l"]), "c": float(v["c"])} for v in velas[m]]
    arq_f = raiz / "lab" / "dados" / "grade_funding.json"      # funding por hora de cada moeda (só acrescenta o que falta)
    fund = ler_funding(arq_f)
    try:
        for m in MOEDAS:
            d = fund.setdefault(m, {})
            desde = max(d) + 1 if d else agora - 5000 * HORA
            if agora - desde >= HORA:
                d.update(baixar_funding(api, m, desde, agora))
            for h in [h for h in d if h < agora - 5100 * HORA]:
                del d[h]
        gravar_funding(arq_f, fund)
    except Exception as ex:  # noqa: BLE001
        print("grade: o funding falhou (as contas usam o que já estava guardado):", str(ex)[:100])
    passado = []
    for m in MOEDAS:
        if len(velas[m]) < 24 * 14:
            continue
        corte = len(velas[m]) * 2 // 3                     # 2/3 para escolher, 1/3 que a escolha não vê
        dentro_v, fora_v = velas[m][:corte], velas[m][corte:]
        fd = fund.get(m) or None
        for c in TODAS:
            r = rodar(c, velas[m], funding=fd)
            dentro = rodar(c, dentro_v, funding=fd)
            fora = rodar(c, fora_v, historico=_fechamentos(dentro_v)[-MEDIA_H:], antes=dentro_v[-ANTES:], funding=fd)
            passado.append({"moeda": m, "config": c, "nome": nome(c), **r, "nota": round(nota_lucro(dentro, fora), 3),
                            "nota_risco": round(nota_honesta(dentro, fora), 3),
                            "dentro": {"retorno": dentro["retorno"], "pior_queda": dentro["pior_queda"], "dias": dentro["dias"]},
                            "fora": {"retorno": fora["retorno"], "pior_queda": fora["pior_queda"], "dias": fora["dias"],
                                     "segurar_moeda": fora["segurar_moeda"]}})
    passado.sort(key=lambda r: -r["nota"])
    if est.get("versao") != VERSAO:                     # regras novas: os robôs ao vivo continuam (versão 7)
        est = continuar(est, VERSAO) if est.get("escolhidas") else {"versao": VERSAO, "anterior": list(est.get("anterior") or [])}
    tem = {familia(e["config"]) for e in est.get("escolhidas", [])}
    if passado and len(tem) < len(FAMILIAS):
        # família sem robô ao vivo: escolhe agora (até 3 de cada: grade/DCA e reversão só com nota > 0, a tendência mesmo no
        # vermelho; até 2 por moeda; sem repetir a mesma estratégia na mesma moeda com outra alavancagem); começa nesta hora
        novos = [{"moeda": r["moeda"], "config": r["config"], "inicio": agora // HORA * HORA} for r in escolher(passado)
                 if familia(r["config"]) not in tem]
        est["escolhidas"] = list(est.get("escolhidas") or []) + novos
    est["inicio"] = min((e["inicio"] for e in est.get("escolhidas", []) if e.get("inicio")), default=None)
    ao_vivo = []
    for e in est.get("escolhidas", []):
        ini = e.get("inicio") or est["inicio"]
        todas = velas.get(e["moeda"], [])
        vs = [v for v in todas if int(v["t"]) >= ini]
        velas_antes = [v for v in todas if int(v["t"]) < ini][-ANTES:]
        antes = _fechamentos(velas_antes)[-MEDIA_H:]
        ops: list = []
        r = rodar(e["config"], vs, ops, historico=antes, antes=velas_antes, funding=fund.get(e["moeda"]) or None) if len(vs) >= 2 else None
        if r is not None:
            r["ops"] = ops[-150:]
        ao_vivo.append({"moeda": e["moeda"], "config": e["config"], "nome": nome(e["config"]), "inicio": ini, "resultado": r})
    for r in passado:   # o app só precisa da curva das melhores
        if r is not passado[0] and r not in passado[:6]:
            r.pop("curva", None)
    # no arquivo ficam as 30 melhores e as 10 melhores de tendência e de reversão (o app baixa este arquivo a cada vez)
    vistos = ([r for r in passado[:30]] + [r for r in passado[30:] if r["config"]["tipo"] == "tendencia"][:10]
              + [r for r in passado[30:] if r["config"]["tipo"] == "reversao"][:10])
    # "só segurar a moeda" desde o começo dos testes (03/11): o app compara cada teste com ela, desde o começo dele
    segurar, desde = {}, min(est.get("inicio") or REF_INICIO, REF_INICIO)
    for m in ("BTC", "ETH"):
        vs = [v for v in velas.get(m, []) if int(v["t"]) >= desde]
        if vs:
            p0 = float(vs[0]["o"])
            segurar[m] = [[desde, 0.0]] + [[int(v["t"]) + HORA, round(float(v["c"]) / p0 - 1, 5)] for v in vs]
    rel = {"gerado": agora, "gerado_txt": datetime.fromtimestamp(agora / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "versao": VERSAO, "inicio_ao_vivo": est.get("inicio"), "moedas": MOEDAS, "capital": 1000, "passado": vistos, "testados": len(passado),
           "ao_vivo": ao_vivo, "segurar": segurar, "anterior": est.get("anterior", []),
           "funding": {m: {"horas": len(d), "ao_ano": round(sum(d.values()) / len(d) * 24 * 365, 4)} for m, d in fund.items() if d}}
    (raiz / "saida").mkdir(exist_ok=True)
    (raiz / "saida" / "grade.json").write_text(json.dumps(rel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding="utf-8")
    m = passado[0] if passado else None
    print(f"grade/DCA: {len(passado)} testes; melhor: {m['moeda']} {m['nome']} {m['retorno']:+.1%}" if m else "grade/DCA: sem velas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
