"""Roda os testes que nasceram das ideias dos vídeos (lab/ideias/, desde 11/11/2026) e grava saida/ideias.json.

Cada teste listado em lab/ideias/indice.json (ativo) roda no intervalo dele, com até 2 min por rodada; se um falha,
os outros continuam e o erro aparece no app. Uso:
    python lab/rodar_ideias.py                 # todos (o laboratório de hora em hora chama assim)
    python lab/rodar_ideias.py --so ID         # só um (para conferir um teste novo)
    python lab/rodar_ideias.py --so ID --seco  # roda sem gravar nada (o Claude confere antes de ligar)
"""
from __future__ import annotations

import importlib
import json
import signal
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from lab.ideias.base import Contexto, DadosBR, DadosHL, DadosLlama  # noqa: E402

INDICE = RAIZ / "lab" / "ideias" / "indice.json"
ESTADOS = RAIZ / "lab" / "dados" / "ideias"
SAIDA = RAIZ / "saida" / "ideias.json"
LIMITE_S = 120


class Demorou(Exception):
    pass


def _alarme(*_):
    raise Demorou(f"passou de {LIMITE_S} s")


def _ler(p: Path, padrao):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return padrao


def _curva_curta(curva: list, maximo: int = 400) -> list:
    """Até `maximo` pontos para o app (mantém o primeiro e o último)."""
    if len(curva) <= maximo:
        return curva
    passo = len(curva) / maximo
    out = [curva[int(i * passo)] for i in range(maximo - 1)]
    return out + [curva[-1]]


def rodar_um(item: dict, hl: DadosHL, llama: DadosLlama, agora: int, seco: bool = False, br: DadosBR | None = None) -> dict:
    tid = item["id"]
    mod = importlib.import_module(f"lab.ideias.{tid}")
    capital = float(getattr(mod, "CAPITAL", 1000.0))
    arq = ESTADOS / f"{tid}.json"
    estado = _ler(arq, {}) or {}
    estado.setdefault("inicio", agora)
    intervalo = float(getattr(mod, "INTERVALO_H", 1)) * 3600 * 1000
    if seco or agora - int(estado.get("ultima", 0)) >= intervalo - 5 * 60 * 1000:
        ctx = Contexto(tid, estado, capital, agora, hl, llama, br)
        signal.signal(signal.SIGALRM, _alarme)
        signal.alarm(LIMITE_S)
        try:
            mod.rodar(ctx)
            estado.pop("erro", None)
        except Exception as ex:  # noqa: BLE001
            estado["erro"] = f"{type(ex).__name__}: {str(ex)[:200]}"
            print(f"--- ideia {tid} falhou ---")
            traceback.print_exc()
        finally:
            signal.alarm(0)
        if ctx.texto_nota:
            estado["nota"] = ctx.texto_nota
        try:
            valor = ctx.carteira.valor(ctx.precos())
        except Exception as ex:  # noqa: BLE001
            valor = None
            estado["erro"] = estado.get("erro") or f"sem preço para avaliar: {type(ex).__name__}"
        if valor is not None:
            curva = estado.setdefault("curva", [])
            if curva and agora - curva[-1][0] < 50 * 60 * 1000:
                curva[-1] = [agora, round(valor, 4)]
            else:
                curva.append([agora, round(valor, 4)])
            del curva[:-3000]
        estado["ultima"] = agora
        if not seco:
            ESTADOS.mkdir(parents=True, exist_ok=True)
            arq.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")
    curva = estado.get("curva") or [[estado["inicio"], capital]]
    saldo = curva[-1][1]
    cart = estado.get("carteira", {})
    return {"id": tid, "nome": getattr(mod, "NOME", tid), "como": getattr(mod, "COMO", ""), "origem": item.get("origem") or {},
            "moeda": getattr(mod, "MOEDA", "US$"),
            "desde": estado["inicio"], "capital": capital, "saldo": round(saldo, 2), "retorno": round(saldo / capital - 1, 6),
            "curva": _curva_curta(curva), "posicoes": cart.get("posicoes", {}), "taxas": round(cart.get("taxas", 0), 2),
            "creditos": round(cart.get("creditos", 0), 2), "ops": (estado.get("ops") or [])[-15:], "nota": estado.get("nota", ""),
            "erro": estado.get("erro", ""), "ultima": estado.get("ultima"), "guia": _guia(mod)}


def _guia(mod) -> dict:
    """O texto da página do teste no app (opcional no módulo): risco 1 a 4, como ganha, como perde, as regras e o que
    precisaria para fazer de verdade."""
    g = {}
    for k in ("RISCO", "GANHA", "PERDE", "REGRAS", "ONDE", "PRECISA", "PASSOS", "FONTE", "RITMO"):
        if hasattr(mod, k):
            g[k.lower()] = getattr(mod, k)
    return g


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    so = argv[argv.index("--so") + 1] if "--so" in argv else None
    seco = "--seco" in argv
    indice = _ler(INDICE, [])
    agora = int(time.time() * 1000)
    hl, llama, br = DadosHL(), DadosLlama(), DadosBR()
    resultados, falhas = [], 0
    lista = ([x for x in indice if x.get("id") == so] or [{"id": so, "origem": {}}]) if so else [x for x in indice if x.get("ativo", True)]
    for item in lista:
        try:
            r = rodar_um(item, hl, llama, agora, seco, br)
            resultados.append(r)
            print(f"ideia {r['id']}: {r['saldo']:.2f} ({r['retorno'] * 100:+.2f}%){' — ' + r['erro'] if r['erro'] else ''}")
        except Exception:  # noqa: BLE001 — o módulo nem carregou
            falhas += 1
            print(f"--- ideia {item.get('id')} não carregou ---")
            traceback.print_exc()
            resultados.append({"id": item.get("id"), "nome": item.get("nome", item.get("id")), "erro": "o código do teste não carregou", "origem": item.get("origem") or {}})
    if seco or so:
        return 1 if falhas or any(r.get("erro") for r in resultados) else 0
    # os desligados continuam aparecendo (com o último resultado), marcados como parados
    for item in indice:
        if not item.get("ativo", True):
            est = _ler(ESTADOS / f"{item['id']}.json", None)
            if est and est.get("curva"):
                cap = float(item.get("capital") or 1000.0)
                resultados.append({"id": item["id"], "nome": item.get("nome", item["id"]), "como": item.get("como", ""), "origem": item.get("origem") or {},
                                   "moeda": item.get("moeda", "US$"), "desde": est["inicio"], "capital": cap, "saldo": est["curva"][-1][1],
                                   "retorno": est["curva"][-1][1] / cap - 1,
                                   "curva": _curva_curta(est["curva"]), "ops": (est.get("ops") or [])[-15:], "nota": item.get("motivo_parada", "parado"), "parado": True})
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps({"gerado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "testes": resultados}, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
