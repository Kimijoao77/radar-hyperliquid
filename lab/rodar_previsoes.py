"""Roda o teste de mercados de previsão (de hora em hora): fecha as apostas de mentira que já resolveram, marca as
abertas no preço de agora, faz as apostas novas de cada jeito e, aos poucos, mede os mesmos jeitos nos mercados que já
fecharam (o passado e a calibração). Só lê a API pública do Polymarket: não tem conta nem ordem de verdade."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from lab.previsoes import (APOSTA, CAPITAL, DIA, HORA, NOVAS_POR_HORA, POR_EVENTO, VARIANTES, VERSAO, candidatos,  # noqa: E402
                           categoria, cotas_por, evento, fim_esperado, lista, ms_de, no_passado, resolucao, resumo_passado, taxa,
                           CURTISSIMOS)

PAGINAS = 4                  # até 4 × 500 mercados abertos por rodada
PASSADO_POR_RODADA = 80      # mercados fechados medidos por rodada (cada um pede o preço de cada hora)
PASSADO_DIAS = 30            # o passado olha os mercados que fecharam nos últimos 30 dias
PASSADO_GUARDA = 45 * DIA
VOLUME_PASSADO = 20000       # só mercados fechados com pelo menos US$ 20 mil negociados
TEMPO_MAX = 4 * 60           # segundos por rodada no passado (o resto fica para a próxima hora)
FECHADAS_GUARDA = 300


class Polymarket:
    G = "https://gamma-api.polymarket.com"
    C = "https://clob.polymarket.com"

    def __init__(self):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "laboratorio-investimentos/1.0"

    def _get(self, url, params):
        for i in range(3):
            try:
                r = self.s.get(url, params=params, timeout=40)
                if r.status_code == 429:
                    time.sleep(5 * (i + 1))
                    continue
                r.raise_for_status()
                return r.json()
            except requests.RequestException as ex:
                if i == 2:
                    raise
                print("previsoes: tentando de novo", str(ex)[:80])
                time.sleep(3)
        return None

    def mercados(self, **params) -> list[dict]:
        out = []
        lim = int(params.pop("limit", 500))
        for pag in range(int(params.pop("paginas", 1))):
            r = self._get(f"{self.G}/markets", {**params, "limit": lim, "offset": pag * lim}) or []
            out += r
            if len(r) < lim:
                break
        return out

    def por_id(self, ids: list[str]) -> dict[str, dict]:
        out = {}
        for i in range(0, len(ids), 50):
            parte = ids[i:i + 50]
            base = [("id", x) for x in parte] + [("limit", "100"), ("include_tag", "true")]
            try:
                r = self._get(f"{self.G}/markets", base + [("closed", "any")]) or []
            except requests.RequestException:                      # sem o "any": abertos e fechados em separado
                r = (self._get(f"{self.G}/markets", base + [("closed", "false")]) or []) + (self._get(f"{self.G}/markets", base + [("closed", "true")]) or [])
            out.update({str(m.get("id")): m for m in r})
        return out

    def historico(self, token: str, ini_ms: int, fim_ms: int) -> list[tuple[int, float]]:
        r = self._get(f"{self.C}/prices-history", {"market": token, "startTs": ini_ms // 1000, "endTs": fim_ms // 1000, "fidelity": 60}) or {}
        return sorted((int(p["t"]) * 1000, float(p["p"])) for p in r.get("history", []) if p.get("p") is not None)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _nova_carteira() -> dict:
    return {"caixa": CAPITAL, "abertas": [], "fechadas": [], "curva": [], "apostas": 0, "acertos": 0, "lucro": 0.0, "taxas": 0.0}


def _fechar(c: dict, a: dict, res: list[float], agora: int) -> None:
    valor = a["cotas"] * res[a["lado"]]
    lucro = valor - a["custo"]
    c["caixa"] += valor
    c["abertas"].remove(a)
    estado = "empate" if res[a["lado"]] == 0.5 else "ganhou" if res[a["lado"]] > 0.5 else "perdeu"
    c["fechadas"].append({**a, "estado": estado, "lucro": round(lucro, 4), "fechada": agora, "agora": res[a["lado"]]})
    c["fechadas"] = c["fechadas"][-FECHADAS_GUARDA:]
    c["apostas"] += 1
    c["acertos"] += 1 if estado == "ganhou" else 0
    c["lucro"] = round(c["lucro"] + lucro, 4)


def _apostar(c: dict, cand: dict, vid: str, agora: int) -> None:
    m = cand["m"]
    cat = categoria(m)
    tx = taxa(m, cat)
    cotas, fee = cotas_por(APOSTA, cand["preco"], tx)
    nomes = lista(m.get("outcomes"))
    c["caixa"] -= APOSTA
    c["taxas"] = round(c["taxas"] + fee, 4)
    c["abertas"].append({"id": str(m.get("id")), "evento": evento(m), "q": str(m.get("question") or "")[:160], "slug": m.get("slug"),
                         "cat": cat, "lado": cand["lado"], "nome_lado": str(nomes[cand["lado"]]) if len(nomes) == 2 else "",
                         "preco": round(cand["preco"], 4), "cotas": round(cotas, 4), "custo": APOSTA, "taxa": round(fee, 4),
                         "desde": agora, "acaba": cand["fim"], "agora": round(cand["preco"], 4), "jeito": vid})


def _patrimonio(c: dict) -> float:
    return c["caixa"] + sum(a["cotas"] * a.get("agora", a["preco"]) for a in c["abertas"])


def _afinar(curva: list, agora: int) -> list:
    """Uma marca por hora nos últimos 3 dias e uma a cada 6 h antes disso."""
    out = []
    for t, v in curva:
        if t < agora - 3 * DIA and out and t - out[-1][0] < 6 * HORA:
            continue
        out.append([t, v])
    return out[-1500:]


def main(raiz: Path = RAIZ, api=None, agora: int | None = None) -> int:
    agora = agora or int(time.time() * 1000)
    arq = raiz / "lab" / "dados" / "previsoes_estado.json"
    saida = raiz / "saida" / "previsoes.json"
    est = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    if est.get("versao") != VERSAO:
        est = {"versao": VERSAO, "inicio": agora // HORA * HORA, "carteiras": {v: _nova_carteira() for v in VARIANTES},
               "passado": {}, "vistos": {}}
    for v in VARIANTES:
        est["carteiras"].setdefault(v, _nova_carteira())
    if saida.exists() and agora - est.get("ultima", 0) < 50 * 60 * 1000:
        print("previsoes: rodou há menos de 50 min")
        return 0
    api = api or Polymarket()
    t0 = time.time()

    # 1) as apostas abertas: resolveu? fecha. Senão, marca no preço de agora
    ids = sorted({a["id"] for c in est["carteiras"].values() for a in c["abertas"]})
    vistos_agora = api.por_id(ids) if ids else {}
    fechou = 0
    for c in est["carteiras"].values():
        for a in list(c["abertas"]):
            m = vistos_agora.get(a["id"])
            if not m:
                continue
            res = resolucao(m)
            if res:
                _fechar(c, a, res, agora)
                fechou += 1
                continue
            ps = lista(m.get("outcomePrices"))
            if len(ps) == 2:
                try:
                    a["agora"] = round(float(ps[a["lado"]]), 4)
                except (TypeError, ValueError):
                    pass

    # 2) apostas novas de cada jeito
    abertos = api.mercados(closed="false", end_date_min=_iso(agora - 3 * DIA), end_date_max=_iso(agora + 10 * DIA),
                           liquidity_num_min=2000, order="volume24hr", ascending="false", include_tag="true", paginas=PAGINAS)
    novas = {}
    for vid, var in VARIANTES.items():
        c = est["carteiras"][vid]
        ja = {a["id"] for a in c["abertas"]} | {f["id"] for f in c["fechadas"]}
        por_ev = {}
        for a in c["abertas"]:
            por_ev[a["evento"]] = por_ev.get(a["evento"], 0) + 1
        n = 0
        for cand in candidatos(abertos, var, agora):
            if n >= NOVAS_POR_HORA or c["caixa"] < APOSTA - 1e-9:
                break
            mid, ev = str(cand["m"].get("id")), evento(cand["m"])
            if mid in ja or por_ev.get(ev, 0) >= POR_EVENTO:
                continue
            _apostar(c, cand, vid, agora)
            ja.add(mid)
            por_ev[ev] = por_ev.get(ev, 0) + 1
            n += 1
        novas[vid] = n
        c["curva"] = _afinar(c["curva"] + [[agora, round(_patrimonio(c), 4)]], agora)

    # 3) o passado, aos poucos: os mesmos jeitos nos mercados que já fecharam
    medidos = 0
    try:
        filtro = dict(closed="true", end_date_min=_iso(agora - PASSADO_DIAS * DIA), end_date_max=_iso(agora), volume_num_min=VOLUME_PASSADO,
                      include_tag="true", paginas=PAGINAS)
        try:
            fechados = api.mercados(**filtro, order="volumeNum", ascending="false")
        except requests.RequestException:                           # se a ordem por volume não valer, sem ordem
            fechados = api.mercados(**filtro)
    except Exception as ex:  # noqa: BLE001
        print("previsoes: sem a lista de fechados", str(ex)[:100])
        fechados = []
    for m in fechados:
        mid = str(m.get("id"))
        if mid in est["passado"] or mid in est["vistos"]:
            continue
        if medidos >= PASSADO_POR_RODADA or time.time() - t0 > TEMPO_MAX:
            break
        toks = lista(m.get("clobTokenIds"))
        fech = ms_de(m.get("closedTime")) or ms_de(m.get("endDate"))
        fim = fim_esperado(m)
        if len(toks) != 2 or len(lista(m.get("outcomes"))) != 2 or not fech or not fim or CURTISSIMOS.search(str(m.get("question") or "")) \
                or not resolucao(m):
            est["vistos"][mid] = agora
            continue
        try:
            hist = api.historico(str(toks[0]), min(fech, fim) - 8 * DIA, fech)
        except Exception as ex:  # noqa: BLE001
            print("previsoes: sem histórico", mid, str(ex)[:80])
            continue
        medidos += 1
        r = no_passado(m, hist)
        if r:
            est["passado"][mid] = r
        else:
            est["vistos"][mid] = agora
    est["passado"] = {k: v for k, v in est["passado"].items() if v["fech"] >= agora - PASSADO_GUARDA}
    est["vistos"] = {k: t for k, t in est["vistos"].items() if t >= agora - PASSADO_GUARDA}

    # 4) o relatório para o app
    est["ultima"] = agora
    passado = resumo_passado(list(est["passado"].values()))
    datas = [v["fech"] for v in est["passado"].values()]
    passado.update({"de": min(datas, default=None), "ate": max(datas, default=None)})
    vars_out = {}
    for vid, var in VARIANTES.items():
        c = est["carteiras"][vid]
        pat = _patrimonio(c)
        vars_out[vid] = {"nome": var["nome"], "curta": var["curta"], "min": var["min"], "max": var["max"], "horas": var["horas"], "lado": var["lado"],
                         "caixa": round(c["caixa"], 2), "patrimonio": round(pat, 2), "retorno": round(pat / CAPITAL - 1, 5),
                         "apostas": c["apostas"], "acertos": c["acertos"], "lucro": round(c["lucro"], 2), "taxas": round(c["taxas"], 2),
                         "abertas": sorted(c["abertas"], key=lambda a: a["acaba"]),
                         "fechadas": sorted(c["fechadas"], key=lambda f: -f["fechada"])[:60],
                         "curva": c["curva"]}
    rel = {"gerado": agora, "gerado_txt": datetime.fromtimestamp(agora / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "versao": VERSAO, "inicio": est["inicio"], "capital": CAPITAL, "aposta": APOSTA, "fonte": "Polymarket (API pública, só leitura)",
           "variantes": vars_out, "passado": passado, "mercados_vistos": len(abertos)}
    saida.parent.mkdir(exist_ok=True)
    saida.write_text(json.dumps(rel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(est, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    print(f"previsoes: {len(abertos)} mercados abertos vistos; {fechou} apostas resolvidas; novas "
          + ", ".join(f"{v} {n}" for v, n in novas.items())
          + "; " + "; ".join(f"{v} {o['retorno']:+.2%} ({len(o['abertas'])} abertas)" for v, o in vars_out.items())
          + f"; passado: {passado['mercados']} mercados ({medidos} novos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
