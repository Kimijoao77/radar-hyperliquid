"""Roda o laboratório de memecoins (de hora em hora): compra moedas novas da pump.fun pelas duas estratégias e vende por
alvo, parada ou prazo, com dinheiro de mentira. Leva 1 a 2 minutos (o GeckoTerminal grátis aceita poucas chamadas)."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from lab.memecoins import (CAPITAL, ESTRATEGIAS, GT, MIN5, REGRAS, VERSAO, andar, candidatos, comprar, patrimonio,  # noqa: E402
                           por_estrategia, resultado, resumo_fechada, tracao)

S = requests.Session()
S.headers.update({"User-Agent": "laboratorio-investimentos/1.0", "Accept": "application/json;version=20230302"})
PAGINAS = 5                 # 5 páginas de 20 pools novas: uns 2 a 3 minutos de lançamentos (a pump.fun lança dezenas por minuto)


class Gecko:
    """GeckoTerminal sem chave: uma chamada a cada 4,5 s e, se responder 429 (limite), espera e tenta de novo."""

    def __init__(self, intervalo: float = 4.5, dormir=time.sleep, relogio=time.monotonic, limite_espera: float = 120):
        self.intervalo, self.dormir, self.relogio, self.limite_espera = intervalo, dormir, relogio, limite_espera
        self.ultima, self.chamadas, self.esperou = -1e9, 0, 0.0

    def get(self, caminho: str, **params):
        for tentativa in range(4):
            espera = self.intervalo - (self.relogio() - self.ultima)
            if espera > 0:
                self.dormir(espera)
            self.ultima = self.relogio()
            self.chamadas += 1
            r = S.get(GT + caminho, params=params, timeout=30)
            if r.status_code == 429:
                if self.esperou >= self.limite_espera:     # não segura a rodada dos robôs: desiste nesta hora
                    break
                self.esperou += 15 * (tentativa + 1)
                self.dormir(15 * (tentativa + 1))
                continue
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        raise RuntimeError("GeckoTerminal: limite de chamadas")


def _novo(agora: int) -> dict:
    return {"versao": VERSAO, "inicio": agora, "caixa": CAPITAL, "abertas": [], "fechadas": [], "curva": [], "vistas": 0, "watch": [],
            "n_fechadas": 0, "n_dobraram": 0, "n_despencaram": 0, "melhor": None, "pior": None}


def _fechar(est: dict, p: dict, agora: int) -> None:
    est["abertas"].remove(p)
    f = resumo_fechada(p, agora)
    est["fechadas"].append(f)
    est["n_fechadas"] += 1
    est["n_dobraram"] += bool(f["dobrou"])
    est["n_despencaram"] += f["motivo"] == "despencou"
    for k, melhor in (("melhor", True), ("pior", False)):
        atual = est.get(k)
        if atual is None or (f["r"] > atual["r"]) == melhor:
            est[k] = {"simbolo": f["simbolo"], "r": f["r"], "token": f["token"]}


def _comprar_melhor(est: dict, medidos: list, tipo: str, t: int) -> int:
    """Compra a mais disputada que passou no filtro (até o limite por hora e de abertas da estratégia)."""
    feitas = 0
    for c, m in sorted((x for x in medidos if x[1]["passa"]), key=lambda x: -x[1]["compradores"]):
        if feitas >= REGRAS["por_hora"] or sum(1 for p in est["abertas"] if p.get("tipo") == tipo) >= REGRAS["max_abertas"]:
            break
        if any(p["token"] == c["token"] for p in est["abertas"]):
            continue
        if comprar(est, c, m, t, tipo):
            feitas += 1
    return feitas


def main(raiz: Path = RAIZ, gecko=None, relogio=time.time) -> int:
    g = gecko or Gecko()
    agora = lambda: int(relogio() * 1000)  # noqa: E731
    t0 = agora()
    arq = raiz / "lab" / "dados" / "memecoins_estado.json"
    saida = raiz / "saida" / "memecoins.json"
    est = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    if est.get("versao") != VERSAO:
        est = _novo(t0)
    if saida.exists() and t0 - est.get("ultima", 0) < 50 * 60 * 1000:
        print("memecoins: rodou há menos de 50 min")
        return 0

    # 1) as moedas que nasceram nos últimos minutos
    cands, vistos = [], set()
    for pg in range(1, PAGINAS + 1):
        try:
            for c in candidatos(g.get("/networks/solana/new_pools", page=pg, include="dex,base_token"), agora()):
                if c["pool"] not in vistos:
                    vistos.add(c["pool"])
                    cands.append(c)
        except Exception as ex:  # noqa: BLE001
            print("memecoins: pools novas falharam", str(ex)[:100])
            break
    est["vistas"] += len(cands)

    # 2) as abertas: segue a pool principal da moeda (quando forma, ela sai da curva da pump.fun para a PumpSwap) e
    #    passa as velas de 5 minutos desde a última rodada
    for i in range(0, len(est["abertas"]), 30):
        try:
            j = g.get("/networks/solana/tokens/multi/" + ",".join(p["token"] for p in est["abertas"][i:i + 30]), include="top_pools")
            for d in (j or {}).get("data") or []:
                tops = ((d.get("relationships") or {}).get("top_pools") or {}).get("data") or []
                addr = (d.get("attributes") or {}).get("address")
                for p in est["abertas"]:
                    if tops and p["token"] == addr:
                        p["pool"] = tops[0]["id"].split("_", 1)[-1]
        except Exception as ex:  # noqa: BLE001
            print("memecoins: pools principais falharam", str(ex)[:100])
    for p in list(est["abertas"]):
        velas = []
        try:
            n = max(2, min(1000, int((agora() - p["ult_t"]) / MIN5) + 2))
            j = g.get(f"/networks/solana/pools/{p['pool']}/ohlcv/minute", aggregate=5, limit=n, currency="usd", token=p["token"])
            velas = (((j or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
        except Exception as ex:  # noqa: BLE001
            print("memecoins: velas falharam", p["simbolo"], str(ex)[:100])
        if andar(est, p, velas, agora()):
            _fechar(est, p, agora())

    # 3) no lançamento: decide com os números da descoberta
    t = agora()
    med_l = [(c, tracao(c, c["_a"], t, ESTRATEGIAS["lancamento"])) for c in cands]
    compradas = {"lancamento": _comprar_melhor(est, med_l, "lancamento", t)}

    # 4) depois da 1ª hora: as moedas vistas na rodada anterior, de novo
    watch = [c for c in est.get("watch") or [] if 40 <= (t - c["criada"]) / 60000 <= 180][:60]
    por = {}
    for i in range(0, len(watch), 30):
        try:
            j = g.get("/networks/solana/pools/multi/" + ",".join(c["pool"] for c in watch[i:i + 30]))
            por.update({d["attributes"]["address"]: d["attributes"] for d in (j or {}).get("data") or [] if d.get("attributes")})
        except Exception as ex:  # noqa: BLE001
            print("memecoins: segunda olhada falhou", str(ex)[:100])
    t = agora()
    med_h = [(c, tracao(c, por[c["pool"]], t, ESTRATEGIAS["hora"])) for c in watch if c["pool"] in por]
    compradas["hora"] = _comprar_melhor(est, med_h, "hora", t)
    est["watch"] = [{k: v for k, v in c.items() if k != "_a"} for c in cands]
    amostra = lambda ms: [{"simbolo": c["simbolo"], **{k: m[k] for k in ("compradores", "compras", "vendas", "volume", "subiu", "idade_min", "passa")}}  # noqa: E731
                          for c, m in sorted(ms, key=lambda x: -x[1]["compradores"])[:12]]
    est["amostra"] = {"lancamento": amostra(med_l), "hora": amostra(med_h)}

    t = agora()
    pat = patrimonio(est)
    est["curva"] = (est["curva"] + [[t, round(pat, 2)]])[-1500:]
    est["fechadas"] = est["fechadas"][-200:]
    est["ultima"] = t
    sem_vendas = lambda f: {k: v for k, v in f.items() if k != "vendas"}  # noqa: E731
    estr = por_estrategia(est)
    rel = {"gerado": t, "gerado_txt": datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "versao": VERSAO, "capital": CAPITAL, "regras": REGRAS, "estrategias": ESTRATEGIAS, "chamadas": g.chamadas,
           "ao_vivo": {"inicio": est["inicio"], "patrimonio": round(pat, 2), "caixa": round(est["caixa"], 2), "curva": est["curva"],
                       "compras": sum(x["compras"] for x in estr), "por_estrategia": estr, "fechadas_total": est["n_fechadas"],
                       "dobraram": est["n_dobraram"], "despencaram": est["n_despencaram"], "melhor": est["melhor"], "pior": est["pior"],
                       "vistas": est["vistas"],
                       "abertas": [{"tipo": p.get("tipo"), "simbolo": p["simbolo"], "token": p["token"], "pool": p["pool"], "entrou": p["entrou"],
                                    "valor": round(p["valor"], 2), "r": round(resultado(p), 4), "max": round(p["max"], 2), "dobrou": p["alvo1"],
                                    "medidas": p["medidas"], "vendas": p["vendas"]} for p in est["abertas"]],
                       "fechadas": [sem_vendas(f) | {"vendas": f["vendas"][-3:]} for f in est["fechadas"][-60:]]},
           "amostra": est["amostra"]}
    saida.parent.mkdir(exist_ok=True)
    saida.write_text(json.dumps(rel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(est, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"memecoins: {len(cands)} moedas novas; compradas no lançamento {compradas['lancamento']}, depois da 1ª hora {compradas['hora']} "
          f"(de {len(med_h)} revistas); {len(est['abertas'])} abertas; patrimônio {pat - CAPITAL:+.2f} US$ ({g.chamadas} chamadas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
