"""Onde os dados ficam (tudo em texto, para o Git guardar só o que mudou):

dados/carteiras.json            lista de observação: quando entrou, de onde veio, situação
dados/estado.json               até onde já coletamos de cada carteira
dados/fills/<carteira>/AAAA-MM.jsonl   cada execução (fill), uma por linha, campos curtos
dados/contas/AAAA-MM.jsonl      fotos do saldo e das posições abertas a cada coleta
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(os.environ.get("RADAR_RAIZ", Path(__file__).resolve().parent.parent))
DADOS = RAIZ / "dados"
SAIDA = RAIZ / "saida"


def agora_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def mes_de(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m")


def ler_json(caminho: Path, padrao):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao


def gravar_json(caminho: Path, obj) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(caminho)


# ---------- fills ----------
def compactar(f: dict) -> dict:
    """Só o que a análise usa, com nomes curtos (o arquivo fica bem menor)."""
    c = {
        "t": int(f["time"]), "c": f["coin"], "s": f["side"], "p": float(f["px"]), "z": float(f["sz"]),
        "sp": float(f.get("startPosition") or 0), "pnl": float(f.get("closedPnl") or 0),
        "f": float(f.get("fee") or 0), "x": 1 if f.get("crossed") else 0,
        "o": f.get("oid"), "id": f.get("tid"), "d": f.get("dir", ""),
    }
    if f.get("liquidation"):
        c["liq"] = 1
    return c


def anexar_fills(carteira: str, fills: list[dict]) -> int:
    """Grava os fills novos (já compactados) no arquivo do mês. Devolve quantos gravou."""
    por_mes: dict[str, list[dict]] = {}
    for f in fills:
        por_mes.setdefault(mes_de(f["t"]), []).append(f)
    n = 0
    for mes, lista in por_mes.items():
        arq = DADOS / "fills" / carteira.lower() / f"{mes}.jsonl"
        arq.parent.mkdir(parents=True, exist_ok=True)
        ja = set()
        if arq.exists():
            for linha in arq.read_text(encoding="utf-8").splitlines():
                try:
                    ja.add(json.loads(linha).get("id"))
                except json.JSONDecodeError:
                    pass
        novos = [f for f in lista if f.get("id") not in ja or f.get("id") is None]
        if novos:
            with arq.open("a", encoding="utf-8") as h:
                for f in novos:
                    h.write(json.dumps(f, separators=(",", ":")) + "\n")
            n += len(novos)
    return n


def ler_fills(carteira: str) -> list[dict]:
    pasta = DADOS / "fills" / carteira.lower()
    out = []
    if pasta.exists():
        for arq in sorted(pasta.glob("*.jsonl")):
            for linha in arq.read_text(encoding="utf-8").splitlines():
                if linha.strip():
                    out.append(json.loads(linha))
    out.sort(key=lambda f: (f["t"], f.get("id") or 0))
    return out


# ---------- fotos da conta ----------
def anexar_foto(foto: dict) -> None:
    arq = DADOS / "contas" / f"{mes_de(foto['t'])}.jsonl"
    arq.parent.mkdir(parents=True, exist_ok=True)
    with arq.open("a", encoding="utf-8") as h:
        h.write(json.dumps(foto, separators=(",", ":")) + "\n")


def ler_fotos() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    pasta = DADOS / "contas"
    if pasta.exists():
        for arq in sorted(pasta.glob("*.jsonl")):
            for linha in arq.read_text(encoding="utf-8").splitlines():
                if linha.strip():
                    f = json.loads(linha)
                    out.setdefault(f["a"], []).append(f)
    return out
