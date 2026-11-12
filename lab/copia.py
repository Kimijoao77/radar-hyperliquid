"""Cópia fiel (laboratório, sem dinheiro): o que aconteceria com quem copiasse de verdade as carteiras do radar.

A estimativa antiga do radar (radar/copia.py) pega o resultado do dia da carteira e desconta uma fração para o atraso.
Ela não sabe em que preço o copiador teria entrado e saído. Aqui cada mudança de posição da carteira vira uma ordem do
copiador, executada com atraso (1 min), no preço daquele minuto (velas da Hyperliquid), pagando a taxa de quem compra a
mercado (0,045 %) e um escorregamento. O copiador segue a carteira em proporção da conta: se ela põe 30 % do saldo
vendido em ETH, a subconta põe 30 % do saldo dela também (vezes o fator de alavancagem da variante).

Cada carteira ganha uma subconta de US$ 1.000 quando entra na cópia; o teste é a soma das subcontas.
A cópia começa sem posição e entra na primeira mudança de cada moeda (seguindo a posição inteira da carteira dali em diante).
Funding não entra na conta (é pequeno perto do resto em operações de horas).

Dois cuidados com os dados (versão 2, 09/11):
- Fills do mesmo instante (uma ordem grande que pega vários preços) chegam da API em qualquer ordem. A posição depois do
  minuto é o fim da cadeia "posição antes (sp) → posição depois", não o último fill da lista. Antes disso a cópia às
  vezes ficava com um resto de posição que a carteira já tinha fechado.
- Mercados de terceiros (HIP-3, "xyz:GOLD", "para:…") têm conta e saldo separados, que a foto do radar não vê. Sem o
  saldo certo não dá para copiar na proporção certa, então ficam de fora (como spot).

Variantes (VARIANTES):
- todas    todas as carteiras do radar, com a alavancagem delas (no máximo 10× por subconta)
- seletiva só as que dá para copiar (mediana de 30 min ou mais segurando a posição e o radar diz que dá), com
           a alavancagem reduzida para 2× a exposição típica delas e uma parada de proteção: caiu 25 % do pico, para.
"""
from __future__ import annotations

import bisect
import math

TAXA = 0.00045              # taxa de quem executa a mercado na Hyperliquid
ESCORREGA = 0.0005          # escorregamento por ordem (sobre o preço do minuto)
MINIMO = 10.0               # ordem mínima da Hyperliquid (US$)
CAPITAL = 1000.0            # cada subconta
MINUTO = 60_000

# Um copy trading só (pedido do João em 09/11/2026): o seletivo. O "todas" (todas as carteiras, na alavancagem delas, até
# 10×) ficou como regra de comparação nos testes; de 03/11 a 09/11 ele deu +5,7 % e o seletivo +8,1 % (sem a melhor
# carteira: −6,8 % e +0,7 %).
TODAS = {"nome": "Cópia fiel: todas", "atraso_s": 60, "teto": 10.0, "alvo": None, "parada": None, "filtro": False}
# 12/11/2026: vários copy tradings lado a lado (pedido do João), cada um mudando UMA coisa do seletivo, para saber o que
# pesa: o atraso, a alavancagem, quem é copiado e por quanto tempo a carteira segura a posição.
VARIANTES = {
    "seletiva": {"nome": "Copy trading", "atraso_s": 60, "teto": 3.0, "alvo": 2.0, "parada": 0.25,
                 "filtro": True, "duracao_minima_min": 30},
    "rapida": {"nome": "Copy rápido (10 s)", "atraso_s": 10, "teto": 3.0, "alvo": 2.0, "parada": 0.25,
               "filtro": True, "duracao_minima_min": 30},
    "agressiva": {"nome": "Copy agressivo (4×)", "atraso_s": 60, "teto": 6.0, "alvo": 4.0, "parada": 0.35,
                  "filtro": True, "duracao_minima_min": 30},
    "habilidade": {"nome": "Copy só das de habilidade", "atraso_s": 60, "teto": 3.0, "alvo": 2.0, "parada": 0.25,
                   "filtro": True, "duracao_minima_min": 30, "classes": ["Habilidade provável"]},
    "longas": {"nome": "Copy de quem segura horas", "atraso_s": 60, "teto": 3.0, "alvo": 2.0, "parada": 0.25,
               "filtro": True, "duracao_minima_min": 180},
    "todas": {**TODAS, "nome": "Copy de todas (sem filtro)"},
}


# ---------------------------------------------------------------- preços (velas)
class Precos:
    """Preço de cada moeda em qualquer instante, interpolando dentro da vela (abertura → fechamento)."""

    def __init__(self):
        self.v: dict[str, list[tuple[int, int, float, float]]] = {}   # moeda → [(t0, t1, abre, fecha)] ordenado
        self._t: dict[str, list[int]] = {}

    def juntar(self, moeda: str, velas: list[dict]) -> None:
        atual = {x[0]: x for x in self.v.get(moeda, [])}
        for c in velas or []:
            try:
                t0, t1 = int(c["t"]), int(c["T"])
                atual[t0] = (t0, t1, float(c["o"]), float(c["c"]))
            except (KeyError, TypeError, ValueError):
                continue
        lista = sorted(atual.values())
        # vela de 1 min por cima da de 5 min: tira as de 5 min que se sobrepõem às menores
        limpa: list[tuple[int, int, float, float]] = []
        for x in lista:
            while limpa and limpa[-1][1] > x[0] and (limpa[-1][1] - limpa[-1][0]) > (x[1] - x[0]):
                limpa.pop()
            if limpa and limpa[-1][1] > x[0]:
                continue
            limpa.append(x)
        self.v[moeda] = limpa
        self._t[moeda] = [x[0] for x in limpa]

    def tem(self, moeda: str) -> bool:
        return bool(self.v.get(moeda))

    def ultimo_t(self, moeda: str) -> int:
        return self.v[moeda][-1][1] if self.v.get(moeda) else 0

    def ultimo(self, moeda: str, t: int) -> float | None:
        """O último fechamento até `t`, mesmo velho (mercado encerrado): só para zerar uma posição que sobrou."""
        vs = self.v.get(moeda)
        if not vs:
            return None
        i = bisect.bisect_right(self._t[moeda], t) - 1
        return vs[i][3] if i >= 0 else None

    def em(self, moeda: str, t: int) -> float | None:
        vs = self.v.get(moeda)
        if not vs:
            return None
        i = bisect.bisect_right(self._t[moeda], t) - 1
        if i < 0:
            return None
        t0, t1, a, f = vs[i]
        if t >= t1:                                     # depois da vela (buraco ou fim): usa o fechamento
            if i + 1 < len(vs) or t - t1 < 10 * MINUTO:
                return f
            return None
        return a + (f - a) * (t - t0) / max(1, t1 - t0)


# ---------------------------------------------------------------- a carteira copiada
def posicao_apos(f: dict) -> float:
    """Posição da carteira na moeda depois do fill (sp = antes; B = compra)."""
    return float(f.get("sp", 0.0)) + (float(f["z"]) if f.get("s") == "B" else -float(f["z"]))


def copiavel_mercado(moeda: str) -> bool:
    """Só os perpétuos da Hyperliquid: spot ("@n", "A/B") e mercados de terceiros ("xyz:GOLD") ficam de fora."""
    return not (moeda.startswith("@") or "/" in moeda or ":" in moeda)


def _perto(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def em_ordem(fills: list[dict]) -> list[dict]:
    """Os fills de UMA moeda em ordem: por tempo e, no mesmo instante (a API não garante a ordem), seguindo a cadeia
    posição antes (sp) → posição depois."""
    fs = sorted(fills, key=lambda f: f["t"])
    out: list[dict] = []
    pos = None
    i = 0
    while i < len(fs):
        j = i
        while j < len(fs) and fs[j]["t"] == fs[i]["t"]:
            j += 1
        resto = fs[i:j]
        while resto:
            k = None
            if pos is not None:                       # continua a cadeia de onde parou
                k = next((n for n, f in enumerate(resto) if _perto(float(f.get("sp", 0.0)), pos)), None)
            if k is None:                             # começo da cadeia: o "antes" que não é o "depois" de outro fill
                depois = [posicao_apos(f) for f in resto]
                k = next((n for n, f in enumerate(resto)
                          if not any(_perto(float(f.get("sp", 0.0)), d) for m, d in enumerate(depois) if m != n)), 0)
            f = resto.pop(k)
            out.append(f)
            pos = posicao_apos(f)
        i = j
    return out


def parte_terceiros(fills: list[dict]) -> float:
    """Que fração dos fills em perpétuos foi em mercados de terceiros (HIP-3)."""
    perps = [f for f in fills if not (f["c"].startswith("@") or "/" in f["c"])]
    return sum(1 for f in perps if ":" in f["c"]) / len(perps) if perps else 0.0


def eventos(fills: list[dict], depois_de: int, atraso_ms: int, fotos: list[dict] | None = None) -> list[dict]:
    """Junta os fills de cada moeda por minuto (o copiador olha a posição dela e age `atraso` depois do último fill do
    minuto). Só fills com t > depois_de e só os perpétuos da Hyperliquid (copiavel_mercado).
    Com `fotos` (as fotos da conta), uma posição que some da foto sem fill de fechamento (mercado encerrado, ajuste da
    bolsa) vira um evento "zerou" na hora da foto, para a cópia não ficar com um resto que a carteira já não tem.
    Volta [{t (do último fill), exec, moeda, pos, px}] em ordem de execução."""
    por_moeda: dict[str, list[dict]] = {}
    for f in fills:
        if "z" in f and copiavel_mercado(f["c"]):
            por_moeda.setdefault(f["c"], []).append(f)
    evs = []
    caminho: dict[str, tuple[list[int], list[float]]] = {}
    for moeda, fs in por_moeda.items():
        ordem = em_ordem(fs)                          # a história toda, para a cadeia saber a posição de antes
        caminho[moeda] = ([f["t"] for f in ordem], [posicao_apos(f) for f in ordem])
        ultimo: dict[int, dict] = {}
        for f in ordem:
            if f["t"] > depois_de:
                ultimo[f["t"] // MINUTO] = f          # na ordem da cadeia, o último do minuto fica
        for f in ultimo.values():
            evs.append({"t": f["t"], "moeda": moeda, "pos": posicao_apos(f), "px": float(f["p"]),
                        "exec": f["t"] + atraso_ms})
    zerado: dict[str, int] = {}
    for ft in sorted(fotos or [], key=lambda x: x["t"]):
        tem = {p[0] for p in ft.get("pos") or []}
        for moeda, (ts, ps) in caminho.items():
            i = bisect.bisect_right(ts, ft["t"]) - 1
            if i < 0 or moeda in tem or _perto(ps[i], 0.0) or zerado.get(moeda) == ts[i]:
                continue
            zerado[moeda] = ts[i]                     # um "zerou" por posição sumida
            if ft["t"] > depois_de:
                evs.append({"t": ft["t"], "moeda": moeda, "pos": 0.0, "px": None, "exec": ft["t"] + atraso_ms,
                            "obs": "sumiu da conta dela"})
    return sorted(evs, key=lambda e: (e["exec"], e["moeda"]))


class Saldos:
    """Saldo da carteira copiada ao longo do tempo (fotos de hora em hora do radar)."""

    def __init__(self, fotos: list[dict], reserva: float | None = None):
        fs = sorted((f["t"], f["v"]) for f in fotos or [] if f.get("v", 0) > 0)
        self.t = [x[0] for x in fs]
        self.v = [x[1] for x in fs]
        self.reserva = reserva                      # saldo de referência do radar, para contas sem foto com saldo

    def em(self, t: int) -> float | None:
        if not self.t:
            return self.reserva
        i = bisect.bisect_right(self.t, t) - 1
        return self.v[max(i, 0)]


# ---------------------------------------------------------------- a subconta do copiador
def nova_subconta(w: str, inicio: int, fator: float) -> dict:
    return {"w": w, "inicio": inicio, "capital": CAPITAL, "colateral": CAPITAL, "pos": {}, "pico": CAPITAL,
            "vivo": True, "parou": None, "parou_em": None, "taxas": 0.0, "ordens": 0, "ult": inicio, "fator": fator,
            "patrimonio": CAPITAL, "expo_max": 0.0}


def patrimonio(sc: dict, precos: Precos, t: int) -> float:
    total = sc["colateral"]
    for m, (q, a) in sc["pos"].items():
        p = precos.em(m, t)
        if p is not None:
            total += q * (p - a)
    return total


def exposicao(sc: dict, precos: Precos, t: int, sem: str | None = None) -> float:
    s = 0.0
    for m, (q, _) in sc["pos"].items():
        if m == sem:
            continue
        p = precos.em(m, t)
        if p is not None:
            s += abs(q) * p
    return s


def negociar(sc: dict, moeda: str, delta: float, preco: float, t: int, log: list | None, motivo: str = "") -> None:
    """Executa `delta` (com sinal) a `preco` (já com escorregamento): preço médio, lucro realizado e taxa."""
    q, a = sc["pos"].get(moeda, (0.0, 0.0))
    taxa = abs(delta) * preco * TAXA
    realizado = 0.0
    if q == 0 or q * delta > 0:
        nq = q + delta
        na = (q * a + delta * preco) / nq if nq else 0.0
    else:
        fecha = min(abs(delta), abs(q))
        realizado = fecha * (preco - a) * (1 if q > 0 else -1)
        nq = q + delta
        if abs(nq) < 1e-12:
            nq, na = 0.0, 0.0
        elif nq * q < 0:                                  # virou de lado: o resto abre no preço de agora
            na = preco
        else:
            na = a
    sc["colateral"] += realizado - taxa
    sc["taxas"] += taxa
    sc["ordens"] += 1
    if nq == 0:
        sc["pos"].pop(moeda, None)
    else:
        sc["pos"][moeda] = (nq, na)
    if log is not None:
        log.append({"t": t, "w": sc["w"], "moeda": moeda, "lado": "compra" if delta > 0 else "venda",
                    "valor": round(abs(delta) * preco, 2), "px": round(preco, 6), "realizado": round(realizado, 2),
                    "resultado": round(realizado - taxa, 2),
                    **({"obs": motivo} if motivo else {})})


def fechar_tudo(sc: dict, precos: Precos, t: int, log: list | None, motivo: str) -> None:
    for m, (q, _) in list(sc["pos"].items()):
        p = precos.em(m, t)
        if p is None:
            continue
        negociar(sc, m, -q, p * (1 - ESCORREGA if q > 0 else 1 + ESCORREGA), t, log, motivo)


def aplicar(sc: dict, ev: dict, saldo_carteira: float, precos: Precos, var: dict, log: list | None) -> str | None:
    """Ajusta a subconta para a nova posição da carteira. Volta None (ok) ou o motivo de ter pulado."""
    t, m = ev["exec"], ev["moeda"]
    q = sc["pos"].get(m, (0.0, 0.0))[0]
    if ev["pos"] == 0 and q == 0:
        return None                                               # ela zerou uma posição que a cópia não tinha
    p = precos.em(m, t)
    if p is None and ev["pos"] == 0:
        p = precos.ultimo(m, t)                                   # para zerar, serve o último preço conhecido
    if p is None:
        return "sem preço"
    if not saldo_carteira or saldo_carteira <= 0:
        return "sem saldo da carteira"
    pat = patrimonio(sc, precos, t)
    if pat <= 0:
        return "subconta zerada"
    fracao = ev["pos"] * ev["px"] / saldo_carteira if ev["pos"] else 0.0   # quanto do saldo dela está na moeda
    alvo_valor = fracao * sc["fator"] * pat
    teto = var["teto"] * pat - exposicao(sc, precos, t, sem=m)     # o que ainda cabe sem passar do teto
    if abs(alvo_valor) > max(0.0, teto):
        alvo_valor = math.copysign(max(0.0, teto), alvo_valor)
    alvo = alvo_valor / p
    delta = alvo - q
    if abs(delta) * p < MINIMO and not (alvo == 0 and q != 0):
        return "ordem pequena"
    preco = p * (1 + ESCORREGA) if delta > 0 else p * (1 - ESCORREGA)
    negociar(sc, m, delta, preco, t, log, ev.get("obs", ""))
    sc["expo_max"] = max(sc["expo_max"], exposicao(sc, precos, t) / max(1e-9, patrimonio(sc, precos, t)))
    return None


def conferir(sc: dict, precos: Precos, t: int, var: dict, log: list | None) -> None:
    """Liquidação (zerou) e parada de proteção (caiu X % do pico)."""
    pat = patrimonio(sc, precos, t)
    sc["pico"] = max(sc["pico"], pat)
    if pat <= 0:
        sc.update(colateral=0.0, pos={}, vivo=False, parou="liquidada: a subconta zerou", parou_em=t)
    elif var.get("parada") and pat < (1 - var["parada"]) * sc["pico"]:
        fechar_tudo(sc, precos, t, log, "parada de proteção")
        sc.update(vivo=False, parou=f"parada: caiu {round(100 * var['parada'])} % do pico", parou_em=t)
    sc["patrimonio"] = round(patrimonio(sc, precos, t) if sc["vivo"] else sc["colateral"], 2)


def copiavel(c: dict, var: dict) -> tuple[bool, str]:
    """Para a variante seletiva: dá para copiar com atraso de 1 min?"""
    if not var.get("filtro"):
        return True, ""
    if var.get("classes") and c.get("classe_nome") not in var["classes"]:
        return False, f"é {c.get('classe_nome') or 'sem classe'}: esta cópia só segue {', '.join(var['classes']).lower()}"
    g = c.get("geral") or {}
    dur = g.get("duracao_mediana_min")
    if dur is None or dur < var["duracao_minima_min"]:
        return False, f"segura as posições {dur} min (mediana): curto demais para copiar com atraso"
    if not (c.get("copiavel") or {}).get("ok", False):
        return False, (c.get("copiavel") or {}).get("motivo") or "o radar diz que não dá para copiar"
    return True, ""


def fator_de(c: dict, var: dict) -> float:
    """Quanto da fração da carteira a subconta copia: 1 = igual; na seletiva, leva a exposição típica dela para `alvo`."""
    if not var.get("alvo"):
        return 1.0
    x = ((c.get("copia") or {}).get("alavancagem") or {}).get("exposicao_mediana") or (c.get("estilo") or {}).get("alavancagem_mediana")
    if not x or x <= 0:
        return 1.0
    return max(0.05, min(1.0, var["alvo"] / x))


def avancar(sc: dict, fills: list[dict], saldos: Saldos, precos: Precos, var: dict, ate: int, log: list | None,
            evs: list[dict] | None = None) -> dict:
    """Processa os fills novos da carteira cuja execução cai até `ate`. Volta a contagem do que foi pulado.
    `evs`: os eventos já prontos (eventos(fills, 0, atraso)), para não refazer a cada hora de uma rodada longa."""
    pulos: dict[str, int] = {}
    if not sc["vivo"]:
        return pulos
    if evs is None:
        evs = eventos(fills, 0, var["atraso_s"] * 1000)
    for ev in evs[bisect.bisect_right(evs, sc["ult"], key=lambda e: e["t"]):]:
        if ev["exec"] > ate:
            break
        motivo = aplicar(sc, ev, saldos.em(ev["t"]), precos, var, log)
        if motivo:
            pulos[motivo] = pulos.get(motivo, 0) + 1
        sc["ult"] = ev["t"] if ev["t"] > sc["ult"] else sc["ult"]
        conferir(sc, precos, ev["exec"], var, log)
        if not sc["vivo"]:
            break
    if sc["vivo"]:
        conferir(sc, precos, ate, var, log)
    return pulos


def resumo(subs: list[dict]) -> dict:
    cap = sum(s["capital"] for s in subs)
    pat = sum(s["patrimonio"] for s in subs)
    return {"capital": round(cap, 2), "saldo": round(pat, 2), "retorno": round(pat / cap - 1, 5) if cap else 0.0,
            "carteiras": len(subs), "vivas": sum(1 for s in subs if s["vivo"]),
            "taxas": round(sum(s["taxas"] for s in subs), 2), "ordens": sum(s["ordens"] for s in subs)}
