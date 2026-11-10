"""Roda o laboratório de moedas recém-listadas (de hora em hora): acha a estreia de cada moeda nova da Hyperliquid,
refaz as operações do passado (uma vez por moeda) e acompanha ao vivo as que estrearem daqui para frente."""
from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from lab.listagens import (ALAVS, CAPITAL, ESPERA_H, HORA, MAXIMO, PARADA, PARTE, PRAZO_H, VERSAO, carteira, estreia_de,  # noqa: E402
                           resumo_op, simular)
from radar.api import Hyperliquid  # noqa: E402

JANELA = 90                  # as últimas moedas da lista da Hyperliquid (a lista cresce no fim: as novas ficam lá)
IDADE_MAX = 460 * 24 * HORA  # o passado vai até ~15 meses atrás
VELAS_1H = 4900 * HORA       # a Hyperliquid guarda as últimas 5.000 velas de cada tamanho: antes disso, velas de 4 h
TEMPO_MAX = 6 * 60           # segundos por rodada buscando moedas (o resto fica para a próxima hora)


def _funding(api, moeda: str, desde: int, ate: int | None = None) -> list[dict]:
    corpo = {"type": "fundingHistory", "coin": moeda, "startTime": int(desde)}
    if ate:
        corpo["endTime"] = int(ate)
    pag = api._post(corpo, 20) or []
    if hasattr(api, "lim"):
        api.lim.gastar(math.ceil(len(pag) / 20))
    return pag


def _por_hora(lista: list[dict]) -> dict[int, float]:
    return {int(f["time"]) // HORA * HORA: float(f["fundingRate"]) for f in lista}


def _operacao(api, nome: str, info: dict, agora: int, fund_lista: list[dict] | None = None) -> dict | None:
    """Refaz a operação da moeda com as velas e o funding da janela (entrada às 24 h, até 14 dias)."""
    e = info["estreia"]
    t_e = e + ESPERA_H * HORA
    fim = min(agora, t_e + PRAZO_H * HORA + 8 * HORA)
    iv = HORA if e >= agora - VELAS_1H else 4 * HORA
    velas = api.velas(nome, "1h" if iv == HORA else "4h", e, fim)
    velas = [{"t": int(v["t"]), "o": float(v["o"]), "h": float(v["h"]), "l": float(v["l"]), "c": float(v["c"])} for v in velas
             if int(v["t"]) + iv <= agora]                       # só velas fechadas
    if fund_lista is None or not fund_lista or max(int(f["time"]) for f in fund_lista) < fim - 2 * HORA:
        fund_lista = _funding(api, nome, t_e, fim)
    return simular(nome, e, velas, _por_hora(fund_lista), iv, fora=info.get("fora", False), alav_max=info.get("alav_max", 3))


def main(raiz: Path = RAIZ, api=None, agora: int | None = None) -> int:
    agora = agora or int(time.time() * 1000)
    arq = raiz / "lab" / "dados" / "listagens_estado.json"
    saida = raiz / "saida" / "listagens.json"
    est = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    if est.get("versao") != VERSAO:
        est = {"versao": VERSAO, "inicio": agora // HORA * HORA, "moedas": {}, "passado": {}, "vivo": {}}
    if saida.exists() and agora - est.get("ultima", 0) < 50 * 60 * 1000:
        print("listagens: rodou há menos de 50 min")
        return 0
    api = api or Hyperliquid(1000)
    t0 = time.time()
    univ = (api._post({"type": "meta"}, 20) or {}).get("universe", [])
    recentes = univ[-JANELA:]
    inicio, conferidas, faltam = est["inicio"], 0, 0
    for m in recentes:
        nome = m["name"]
        info = est["moedas"].setdefault(nome, {})
        info["fora"] = bool(m.get("isDelisted"))
        info["alav_max"] = m.get("maxLeverage", 3)
        if "estreia" not in info:                             # a estreia: o primeiro funding da moeda (uma vez por moeda)
            if time.time() - t0 > TEMPO_MAX:
                faltam += 1
                continue
            lista = _funding(api, nome, 0)
            info["estreia"] = estreia_de(lista)
            info["_lista"] = lista                            # só nesta rodada (não vai para o arquivo)
            conferidas += 1
        e = info.get("estreia")
        if not e or e < agora - IDADE_MAX:
            continue
        t_e = e + ESPERA_H * HORA
        if t_e >= inicio:                                     # ao vivo: entrou (ou entra) depois do começo do teste
            if t_e > agora:
                continue
            op = est["vivo"].get(nome)
            if op and op.get("saida") is not None:
                continue                                      # já fechou: não muda mais
            if time.time() - t0 > TEMPO_MAX + 120:
                faltam += 1
                continue
            try:
                op = _operacao(api, nome, info, agora)
            except Exception as ex:  # noqa: BLE001
                print("listagens: ao vivo falhou", nome, str(ex)[:100])
                continue
            if op:
                est["vivo"][nome] = op
        elif nome not in est["passado"] and agora >= t_e + PRAZO_H * HORA + 8 * HORA:   # passado: só a janela inteira
            if time.time() - t0 > TEMPO_MAX:
                faltam += 1
                continue
            try:
                op = _operacao(api, nome, info, agora, info.get("_lista"))
            except Exception as ex:  # noqa: BLE001
                print("listagens: passado falhou", nome, str(ex)[:100])
                continue
            if op and op.get("saida") is not None:
                est["passado"][nome] = op
    for info in est["moedas"].values():
        info.pop("_lista", None)

    passado = list(est["passado"].values())
    vivo = list(est["vivo"].values())
    esperando = sorted(({"moeda": n, "estreia": i["estreia"], "entra": i["estreia"] + ESPERA_H * HORA} for n, i in est["moedas"].items()
                        if i.get("estreia") and i["estreia"] + ESPERA_H * HORA > agora and not i.get("fora")), key=lambda x: x["entra"])
    est["ultima"] = agora
    rel = {"gerado": agora, "gerado_txt": datetime.fromtimestamp(agora / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "versao": VERSAO, "capital": CAPITAL, "parte": PARTE, "maximo": MAXIMO, "parada": PARADA, "prazo_dias": PRAZO_H // 24,
           "espera_h": ESPERA_H, "alavs": list(ALAVS),
           "regra": "vende 24 h depois da estreia, 10 % do patrimônio de margem por moeda; sai se subir 30 % ou em 14 dias",
           "passado": {"moedas": len(passado), "de": min((o["entrada"] for o in passado), default=None),
                       "ate": max((o["saida"] for o in passado), default=None),
                       "variantes": {str(a): carteira(passado, a) for a in ALAVS} if passado else {},
                       "operacoes": [resumo_op(o) for o in sorted(passado, key=lambda o: -o["entrada"])][:80]},
           "ao_vivo": {"inicio": inicio, "variantes": {str(a): carteira(vivo, a, inicio=inicio) for a in ALAVS},
                       "operacoes": [resumo_op(o) for o in sorted(vivo, key=lambda o: -o["entrada"])], "esperando": esperando},
           "conhecidas": sum(1 for i in est["moedas"].values() if i.get("estreia")), "faltam": faltam}
    saida.parent.mkdir(exist_ok=True)
    saida.write_text(json.dumps(rel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(est, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    v = rel["passado"]["variantes"]
    print(f"listagens: {len(passado)} moedas no passado"
          + "".join(f"; {a}× {v[a]['retorno']:+.1%} (pior queda {v[a]['pior_queda']:.0%})" for a in v)
          + f"; ao vivo {len(vivo)} operações, {len(esperando)} esperando as 24 h; {conferidas} estreias conferidas, {faltam} para a próxima rodada")
    return 0


if __name__ == "__main__":
    sys.exit(main())
