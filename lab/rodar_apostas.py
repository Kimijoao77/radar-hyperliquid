"""Roda o laboratório de apostas esportivas (a cada 3 horas): teste no passado e as apostas de mentira na bolsa."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from lab.apostas import (APOSTA, CAPITAL, COMISSAO, CONFIGS, JOGOS, JOGOS_EXTRAS, LIGAS, NOME_LIGA, RESULTADOS_EXTRAS,  # noqa: E402
                         TEMPORADA, VERSAO, achar_resultado, avaliar, chave, clv, descrever, desfecho, escolher, jogos_da_lista,
                         ler_csv, nome, resultado, temporada, medir, venceu)

MINIMO_CONFERIR = 30          # com menos apostas nesta temporada, ainda não dá para dizer que o ajuste perdeu

HORA = 3600 * 1000
DIA = 24 * HORA
S = requests.Session()
S.headers["User-Agent"] = "laboratorio-investimentos/1.0"


def _texto(url: str) -> str:
    r = S.get(url, timeout=60)
    if r.status_code == 404:
        return ""
    r.raise_for_status()
    try:
        return r.content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return r.content.decode("cp1252", errors="replace")


def rotulo(t: str) -> str:
    return f"20{t[:2]}/{t[2:]}"


def no_passado(baixar, agora: int) -> dict:
    """Versão 2: escolhe o ajuste na última temporada completa (maior lucro por aposta), exigindo lucro também na
    anterior, e confere nesta (que a escolha não viu). Sem ajuste que passe, ou com o escolhido perdendo nesta
    temporada, o teste desliga."""
    atual = temporada(agora)
    a = int(atual[:2])
    escolha, exigida = f"{a - 1:02d}{a:02d}", f"{a - 2:02d}{a - 1:02d}"
    dados = {}
    for t in (exigida, escolha, atual):
        linhas = []
        for liga in LIGAS:
            try:
                linhas += ler_csv(baixar(TEMPORADA.format(t=t, liga=liga)))
            except Exception as ex:  # noqa: BLE001
                print("apostas: sem", t, liga, str(ex)[:80])
        dados[t] = linhas
    medidas = {t: [medir(dados[t], c) for c in CONFIGS] for t in dados}
    i = escolher(medidas[escolha], medidas[exigida])
    sem = lambda m: {k: v for k, v in m.items() if k != "por_liga"}  # noqa: E731
    ordem = sorted((j for j in range(len(CONFIGS)) if medidas[escolha][j]["apostas"] >= 150), key=lambda j: -medidas[escolha][j]["roi"])
    papel = {exigida: "exigida", escolha: "escolha", atual: "até hoje"}
    out = {"versao": VERSAO, "feito": agora, "regra": CONFIGS[i] if i is not None else None, "nome": nome(CONFIGS[i]) if i is not None else "",
           "temporadas": [{"temporada": rotulo(t), "papel": papel[t], "jogos": len(dados[t]), **sem(medidas[t][i])} for t in dados] if i is not None else [],
           "ranking": [{"nome": nome(CONFIGS[j]), **sem(medidas[escolha][j]),
                        "depois": {rotulo(exigida): medidas[exigida][j]["roi"], rotulo(atual): medidas[atual][j]["roi"]}} for j in ordem[:8]],
           "por_liga": {NOME_LIGA.get(k, k): v for k, v in medidas[escolha][i]["por_liga"].items()} if i is not None else {},
           "desligado": False, "motivo": ""}
    if i is None:
        out.update(desligado=True, motivo=f"nenhum ajuste deu lucro em {rotulo(escolha)} e em {rotulo(exigida)} ao mesmo tempo")
    elif medidas[atual][i]["apostas"] >= MINIMO_CONFERIR and medidas[atual][i]["roi"] <= 0:
        out.update(desligado=True, motivo=f"o ajuste escolhido ({nome(CONFIGS[i])}) perdeu nesta temporada: "
                                         f"{medidas[atual][i]['roi']:+.1%} por aposta em {medidas[atual][i]['apostas']} apostas")
    return out


def _fechar(est: dict, a: dict, estado: str, lucro: float, agora: int, **extra) -> None:
    est["abertas"].remove(a)
    est["fechadas"].append({**a, "estado": estado, "lucro": round(lucro, 2), "fechada": agora, **extra})


def main(raiz: Path = RAIZ, baixar=_texto, agora: int | None = None) -> int:
    agora = agora or int(time.time() * 1000)
    arq = raiz / "lab" / "dados" / "apostas_estado.json"
    saida = raiz / "saida" / "apostas.json"
    est = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {}
    if est.get("versao") != VERSAO:
        est = {"versao": VERSAO}
    if saida.exists() and agora - est.get("ultima", 0) < 3 * HORA - 10 * 60 * 1000:
        print("apostas: rodou há menos de 3 h")
        return 0
    if not est.get("passado") or agora - est["passado"].get("feito", 0) > 7 * DIA:
        est["passado"] = no_passado(baixar, agora)
    cfg = est["passado"]["regra"]
    desligado = bool(est["passado"].get("desligado"))
    est.setdefault("inicio", agora)
    est.setdefault("abertas", [])
    est.setdefault("fechadas", [])

    # 1) as apostas de jogos que já acabaram: resultado e odd de fechamento
    fontes = {}
    for a in est["abertas"]:
        if agora > a["inicio"] + 150 * 60 * 1000:
            url = TEMPORADA.format(t=temporada(a["inicio"]), liga=a["liga"]) if a["liga"] in LIGAS else RESULTADOS_EXTRAS.format(cod=a["liga"])
            fontes.setdefault(url, []).append(a)
    for url, lista in fontes.items():
        try:
            linhas = ler_csv(baixar(url))
        except Exception as ex:  # noqa: BLE001
            print("apostas: resultados falharam", url[-24:], str(ex)[:80])
            continue
        for a in lista:
            r = achar_resultado(a, linhas)
            ok = venceu(a, desfecho(r["linha"])) if r else None
            if r and ok is not None:
                g = resultado(a, ok, a["valor"])
                c = clv(a, r["linha"])
                _fechar(est, a, "ganhou" if g > 0 else "perdeu", g, agora, placar=r["placar"], clv=None if c is None else round(c, 4))
            elif agora > a["inicio"] + 10 * DIA:
                _fechar(est, a, "anulada", 0.0, agora)

    # 2) os jogos da lista nova: aposta nos que passam na regra (uma vez por jogo, antes de começar)
    jogos = jogos_da_lista(ler_csv(baixar(JOGOS)), ler_csv(baixar(JOGOS_EXTRAS)))
    feitas = {a["chave"] for a in est["abertas"]} | {a["chave"] for a in est["fechadas"][-4000:]}
    saldo = CAPITAL + sum(f["lucro"] for f in est["fechadas"])
    preso = sum(a["valor"] for a in est["abertas"])
    novas = 0
    for j in sorted(jogos, key=lambda j: j["inicio"]) if not desligado else []:
        if j["inicio"] <= agora + 10 * 60 * 1000 or chave(j) in feitas:
            continue
        a = avaliar(j, cfg)
        if not a:
            continue
        if saldo - preso < APOSTA:
            break
        est["abertas"].append({"chave": chave(j), "liga": j["liga"], "casa": j["casa"], "fora": j["fora"], "data": j["data"],
                               "inicio": j["inicio"], **a, "valor": APOSTA, "feita": agora})
        feitas.add(chave(j))
        preso += APOSTA
        novas += 1

    est["curva"] = (est.get("curva") or []) + [[agora, round(saldo, 2)]]
    est["curva"] = est["curva"][-1500:]
    est["fechadas"] = est["fechadas"][-4000:]
    est["ultima"] = agora
    feitas_ok = [f for f in est["fechadas"] if f["estado"] != "anulada"]
    cs = [f["clv"] for f in feitas_ok if f.get("clv") is not None]
    leg = lambda a: {**{k: a[k] for k in a if k not in ("chave",)}, "nome_liga": NOME_LIGA.get(a["liga"], a["liga"]), "escolha": descrever(a)}  # noqa: E731
    rel = {"gerado": agora, "gerado_txt": datetime.fromtimestamp(agora / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "versao": VERSAO, "capital": CAPITAL, "aposta": APOSTA, "comissao": COMISSAO, "regra": {**(cfg or {}), "nome": est["passado"]["nome"]},
           "desligado": desligado, "motivo": est["passado"].get("motivo", ""),
           "passado": est["passado"], "jogos_na_lista": len(jogos),
           "ao_vivo": {"inicio": est["inicio"], "saldo": round(saldo, 2), "curva": est["curva"], "apostas": len(feitas_ok),
                       "acertos": sum(f["lucro"] > 0 for f in feitas_ok), "lucro": round(sum(f["lucro"] for f in feitas_ok), 2),
                       "roi": round(sum(f["lucro"] for f in feitas_ok) / (APOSTA * len(feitas_ok)), 4) if feitas_ok else 0.0,
                       "clv": round(sum(cs) / len(cs), 4) if cs else None, "bateu": round(sum(c > 0 for c in cs) / len(cs), 3) if cs else None,
                       "em_jogo": round(preso, 2), "abertas": [leg(a) for a in sorted(est["abertas"], key=lambda a: a["inicio"])],
                       "fechadas": [leg(f) for f in est["fechadas"][-60:]]}}
    saida.parent.mkdir(exist_ok=True)
    saida.write_text(json.dumps(rel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(est, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    p = est["passado"]
    print(f"apostas: {'DESLIGADO (' + p['motivo'] + ')' if desligado else 'regra ' + repr(p['nome'])}; no passado "
          + "; ".join(f"{t['temporada']} {t['apostas']} apostas ROI {t['roi']:+.1%}" for t in p["temporadas"])
          + f"; ao vivo {novas} novas, {len(est['abertas'])} abertas, saldo {saldo - CAPITAL:+.2f} US$")
    return 0


if __name__ == "__main__":
    sys.exit(main())
