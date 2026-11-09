"""Roda o laboratório de funding (GitHub Actions, de hora em hora): coleta e grava saida/funding.json (o Nexus lê)."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from lab.funding import COM_SPOT, DIA, HORA, Banco, cfg_de, coletar, ranking, simular, universo  # noqa: E402
from radar.api import Hyperliquid  # noqa: E402


def main(raiz: Path = RAIZ, api=None) -> int:
    inicio_relogio = time.monotonic()
    cfg = json.loads((raiz / "config.json").read_text(encoding="utf-8"))
    p = cfg_de(cfg)
    api = api or Hyperliquid(cfg.get("peso_por_minuto", 1000))
    banco = Banco(raiz / "lab" / "dados" / "funding")
    arq_est = raiz / "lab" / "dados" / "funding_estado.json"
    est = json.loads(arq_est.read_text(encoding="utf-8")) if arq_est.exists() else {}
    agora = int(time.time() * 1000)

    uni = universo(api._post({"type": "metaAndAssetCtxs"}, 20), p)
    nomes = [u["moeda"] for u in uni]
    # continua coletando as que saíram do universo há pouco (a simulação pode estar com posição nelas)
    recentes = [m for m in banco.s if m not in nomes and agora - banco.ultima(m) < 3 * DIA]
    novas = coletar(api, banco, nomes + recentes, agora, p["dias_passado"])

    ult = max((banco.ultima(m) for m in banco.s), default=0)
    if not ult:
        print("funding: sem dados ainda")
        return 0
    est.setdefault("inicio_ao_vivo", ult)
    moedas = sorted(m for m in banco.s if not p.get("so_com_spot") or m in COM_SPOT)
    ao_vivo = simular(banco, moedas, est["inicio_ao_vivo"], ult, p)
    passado = simular(banco, moedas, ult - p["dias_passado"] * DIA, ult, p)
    rel = {
        "gerado": agora, "gerado_txt": datetime.fromtimestamp(agora / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "versao": 2, "ultima_hora": ult, "parametros": p, "moedas_acompanhadas": len(nomes),
        "ranking": ranking(banco, uni, ult)[:20],
        "ao_vivo": ao_vivo, "passado": passado,
        "coleta": {"horas_novas": novas, "peso": api.lim.total, "segundos": round(time.monotonic() - inicio_relogio)},
    }
    (raiz / "saida").mkdir(exist_ok=True)
    (raiz / "saida" / "funding.json").write_text(json.dumps(rel, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    arq_est.parent.mkdir(parents=True, exist_ok=True)
    arq_est.write_text(json.dumps(est, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"funding: {len(nomes)} moedas, {novas} horas novas; ao vivo {ao_vivo['lucro']:+.2f} US$, "
          f"últimos {p['dias_passado']} dias {passado['lucro']:+.2f} US$ ({passado['ao_ano']} ao ano); peso {api.lim.total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
