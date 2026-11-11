"""Confere os testes novos das ideias dos vídeos (marcados com "conferir": true em lab/ideias/indice.json): roda cada um
uma vez com os dados de verdade, sem gravar nada. Deu certo → liga ("ativo": true). Deu erro → fica desligado e o erro
vai para "erro_conferencia" (o Claude corrige na próxima leitura). Roda no GitHub (fluxo "Ideias: conferir")."""
from __future__ import annotations

import contextlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from lab import rodar_ideias  # noqa: E402

def _b3() -> str:
    """O arquivo público de cotações da B3 (série histórica), plano B se o Yahoo recusar."""
    import io as _io
    import zipfile
    from datetime import timedelta
    import requests
    d = datetime.now(timezone.utc) - timedelta(days=1)
    for _ in range(6):
        nome = f"COTAHIST_D{d:%d%m%Y}.ZIP"
        r = requests.get(f"https://bvmf.bmfbovespa.com.br/InstDados/SerHist/{nome}", timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200 and r.content[:2] == b"PK":
            linhas = zipfile.ZipFile(_io.BytesIO(r.content)).read(zipfile.ZipFile(_io.BytesIO(r.content)).namelist()[0]).decode("latin-1").splitlines()
            hg = [x for x in linhas if x[12:24].strip() == "HGLG11"]
            return f"{nome}: {len(linhas)} linhas; HGLG11 fechou {int(hg[0][108:121]) / 100 if hg else '?'}"
        d -= timedelta(days=1)
    return f"sem arquivo (último status {r.status_code})"


if "--fontes" in sys.argv:
    # confere se cada fonte de dados responde daqui (o GitHub); o proxy da sessão do Claude bloqueia quase todas
    from lab.ideias.base import DadosBR, DadosHL, DadosLlama
    br, hl, ll = DadosBR(), DadosHL(), DadosLlama()
    for nome, f in [("Hyperliquid (preços)", lambda: f"{len(hl.precos())} moedas, BTC {hl.precos().get('BTC')}"),
                    ("Hyperliquid (velas)", lambda: f"{len(hl.velas('ETH', '1h', 24))} velas de ETH"),
                    ("DefiLlama (pools)", lambda: f"{len(ll.pools())} pools"),
                    ("Banco Central (CDI)", lambda: str(br.juros('cdi', 2))),
                    ("Banco Central (IPCA)", lambda: str(br.juros('ipca', 1))),
                    ("Yahoo (HGLG11)", lambda: f"preço {br.preco('HGLG11.SA')}, {len(br.proventos('HGLG11.SA'))} proventos em 2 anos"),
                    ("Yahoo (dólar)", lambda: f"BRL=X {br.preco('BRL=X')}"),
                    ("B3 (cotações do dia)", lambda: _b3())]:
        try:
            print(f"ok   {nome}: {f()}")
        except Exception as ex:  # noqa: BLE001
            print(f"ERRO {nome}: {type(ex).__name__}: {ex}")
    sys.exit(0)

indice = json.loads(rodar_ideias.INDICE.read_text(encoding="utf-8"))
mudou = False
for item in indice:
    if not item.get("conferir"):
        continue
    saida = io.StringIO()
    with contextlib.redirect_stdout(saida), contextlib.redirect_stderr(saida):
        try:
            cod = rodar_ideias.main(["--so", item["id"], "--seco"])
        except Exception as ex:  # noqa: BLE001
            print(f"{type(ex).__name__}: {ex}")
            cod = 1
    txt = saida.getvalue()
    print(f"== {item['id']} ==\n{txt}")
    item["conferir"] = False
    item["conferido_em"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if cod == 0:
        item["ativo"] = True
        item.pop("erro_conferencia", None)
    else:
        item["ativo"] = False
        item["erro_conferencia"] = txt.strip()[-800:]
    mudou = True
if mudou:
    rodar_ideias.INDICE.write_text(json.dumps(indice, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
