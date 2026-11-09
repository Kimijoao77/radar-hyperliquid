import json, sys, time
from pathlib import Path
raiz = Path(sys.argv[1]); sys.path.insert(0, str(raiz))
from lab import rodar_concentradas
rodar_concentradas.main(raiz)
s = json.loads((raiz / "saida" / "concentradas.json").read_text())
for t in s["topo"]: print("topo", t)
for k, f in s["faixas"].items():
    print(k, f["patrimonio"], [(a["nome"], a["r"]) for a in f["abertas"]])
