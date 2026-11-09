"""Memecoins da pump.fun com moedas e velas de mentira."""
import json

import pytest

from lab import rodar_memecoins
from lab.memecoins import CAPITAL, ESTRATEGIAS, MIN5, andar, candidatos, comprar, patrimonio, por_estrategia, resultado, tracao

T0 = 1_762_700_000_000 - 1_762_700_000_000 % MIN5     # um começo de vela de 5 min


def iso(ms):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pool(addr, nome="BONK2 / SOL", dex="pump-fun", px=0.00001, criada=T0, janela="m5", **m):
    tx = {"buys": m.get("buys", 0), "sells": m.get("sells", 0), "buyers": m.get("buyers", 0)}
    return {"id": f"solana_{addr}", "attributes": {"address": addr, "name": nome, "base_token_price_usd": str(px), "pool_created_at": iso(criada),
                                                    "fdv_usd": "5000", "reserve_in_usd": "2500", "volume_usd": {janela: str(m.get("vol", 0))},
                                                    "transactions": {janela: tx}},
            "relationships": {"dex": {"data": {"id": dex}}, "base_token": {"data": {"id": f"solana_tok{addr}"}}}}


def test_candidatos_so_pump_fun_com_sol():
    resp = {"data": [pool("a"), pool("b", dex="raydium"), pool("c", nome="X / USDC"), pool("d", px=0)]}
    cs = candidatos(resp, T0)
    assert [c["pool"] for c in cs] == ["a"] and cs[0]["token"] == "toka" and cs[0]["simbolo"] == "BONK2" and cs[0]["_a"]


def test_tracao_das_duas_estrategias():
    c = {"px0": 1e-5, "criada": T0}
    a = pool("a", px=1e-5, buys=40, sells=20, buyers=25, vol=3000)["attributes"]
    assert tracao(c, a, T0 + 2 * 60000, ESTRATEGIAS["lancamento"])["passa"]
    assert not tracao(c, {**a, "transactions": {"m5": {"buys": 10, "sells": 20, "buyers": 25}}}, T0 + 60000, ESTRATEGIAS["lancamento"])["passa"]
    assert not tracao(c, a, T0 + 20 * 60000, ESTRATEGIAS["lancamento"])["passa"]                        # velha demais
    h = pool("a", px=3e-5, janela="h1", buys=300, sells=200, buyers=80, vol=25000)["attributes"]
    m = tracao(c, h, T0 + 60 * 60000, ESTRATEGIAS["hora"])
    assert m["passa"] and m["subiu"] == 3.0
    assert not tracao(c, {**h, "base_token_price_usd": "1.5e-5"}, T0 + 60 * 60000, ESTRATEGIAS["hora"])["passa"]   # não dobrou


def est_com_compra(px=1.0, tipo="lancamento"):
    est = {"caixa": CAPITAL, "abertas": []}
    p = comprar(est, {"token": "t", "pool": "p", "simbolo": "X"}, {"px": px, "compradores": 20, "compras": 30, "vendas": 10, "volume": 2000,
                                                                      "subiu": 1.3, "idade_min": 3, "fdv": 5000}, T0 + 60000, tipo)
    return est, p


def vela(i, o, h, lo, c):
    return [(T0 + i * MIN5) / 1000, o, h, lo, c, 100]


def test_compra_paga_custo_e_parada():
    est, p = est_com_compra()
    assert p["valor"] == pytest.approx(10) and est["caixa"] == pytest.approx(990)
    assert patrimonio(est) == pytest.approx(990 + 10 / 1.03 * 0.97)
    # a vela da compra (começou antes) não conta; a seguinte cai 60 %: vende na parada (−50 %)
    assert andar(est, p, [vela(0, 1, 9, 0.1, 1), vela(1, 1, 1.1, 0.4, 0.45)], T0 + 3 * MIN5)
    assert p["vendas"][-1]["motivo"] == "parada" and p["vendas"][-1]["px"] == 0.5
    assert resultado(p) == pytest.approx(0.5 / 1.03 * 0.97 - 1)
    e = {x["id"]: x for x in por_estrategia(est)}
    assert e["lancamento"]["compras"] == 1 and e["lancamento"]["r"] == pytest.approx(resultado(p), abs=1e-4) and e["hora"]["r"] is None


def test_dobra_e_depois_volta_ao_preco():
    est, p = est_com_compra(tipo="hora")
    assert not andar(est, p, [vela(1, 1, 2.2, 0.9, 2.0)], T0 + 2 * MIN5)          # dobrou: vende metade
    assert p["alvo1"] and p["vendas"][0]["motivo"] == "dobrou"
    assert andar(est, p, [vela(2, 2, 2.1, 0.95, 1.0)], T0 + 3 * MIN5)              # voltou ao preço de compra: sai
    assert p["vendas"][-1]["motivo"] == "voltou ao preço"
    assert resultado(p) == pytest.approx((0.5 * 2 + 0.5 * 1) / 1.03 * 0.97 - 1)
    assert {x["id"]: x for x in por_estrategia(est)}["hora"]["r"] == pytest.approx(resultado(p), abs=1e-4)


def test_cinco_vezes_despencou_e_prazo():
    est, p = est_com_compra()
    assert andar(est, p, [vela(1, 1, 6, 0.9, 5.5)], T0 + 2 * MIN5)                  # 2× e 5× na mesma vela
    assert [v["motivo"] for v in p["vendas"]] == ["dobrou", "5×"]
    est, p = est_com_compra()
    assert andar(est, p, [vela(1, 1, 1.2, 0.01, 0.02)], T0 + 2 * MIN5)              # despencou numa vela só: sai no fundo
    assert p["vendas"][-1]["motivo"] == "despencou" and p["vendas"][-1]["px"] == 0.01
    est, p = est_com_compra()
    assert not andar(est, p, [vela(1, 1, 1.3, 0.8, 1.2)], T0 + 2 * MIN5)
    assert andar(est, p, [], T0 + 25 * 3600 * 1000)                                 # 24 h sem negócio: sai no último preço
    assert p["vendas"][-1]["motivo"] == "24 horas" and p["vendas"][-1]["px"] == 1.2


class Falso:
    """GeckoTerminal de mentira: pools novas, segunda olhada, pools principais e velas."""

    def __init__(self, t):
        self.t, self.chamadas, self.pedidos = t, 0, []

    def get(self, caminho, **params):
        self.chamadas += 1
        self.pedidos.append(caminho)
        t = self.t[0] * 1000
        if caminho.endswith("/new_pools"):
            if params["page"] == 1:
                return {"data": [pool(f"a{int(t)}", nome="NOVA / SOL", px=1e-5, criada=t - 60000, buys=30, sells=10, buyers=22, vol=900),
                                 pool(f"b{int(t)}", px=1e-5, criada=t - 60000, buys=5, sells=1, buyers=4, vol=100),
                                 pool("c", dex="meteora")]}
            return {"data": []}
        if "/pools/multi/" in caminho:
            ids = caminho.rsplit("/", 1)[1].split(",")
            return {"data": [pool(i, nome="VIVA / SOL" if i.startswith("b") else "NOVA / SOL", px=3e-5 if i.startswith("b") else 1e-6, janela="h1",
                                  buys=400, sells=150, buyers=90, vol=40000) for i in ids]}
        if "/tokens/multi/" in caminho:
            return {"data": [{"attributes": {"address": tok}, "relationships": {"top_pools": {"data": [{"id": f"solana_swap{tok}"}]}}}
                             for tok in caminho.rsplit("/", 1)[1].split(",")]}
        if "/ohlcv/" in caminho:
            tc = (t - 10 * 60000) - (t - 10 * 60000) % MIN5          # uma vela fechada de 10 min atrás
            return {"data": {"attributes": {"ohlcv_list": [[tc / 1000, 1e-5, 2.5e-5, 0.9e-5, 2.2e-5, 10]]}}}
        raise AssertionError(caminho)


def test_rodar(tmp_path):
    (tmp_path / "lab" / "dados").mkdir(parents=True)
    relogio = [(T0 + 2 * 60000) / 1000]
    g = Falso(relogio)
    assert rodar_memecoins.main(tmp_path, gecko=g, relogio=lambda: relogio[0]) == 0
    s = json.loads((tmp_path / "saida" / "memecoins.json").read_text())
    v = s["ao_vivo"]
    assert v["compras"] == 1 and [(a["simbolo"], a["tipo"]) for a in v["abertas"]] == [("NOVA", "lancamento")] and v["vistas"] == 2
    assert v["patrimonio"] == pytest.approx(CAPITAL - 10 + 10 / 1.03 * 0.97, abs=0.01)
    # 30 min depois: ainda não roda; 1 h depois: segue a pool nova (formou), a vela dobra o preço, e revê as moedas da rodada
    # anterior: a que sobreviveu e triplicou é comprada na estratégia "depois da 1ª hora"
    relogio[0] += 30 * 60
    assert rodar_memecoins.main(tmp_path, gecko=g, relogio=lambda: relogio[0]) == 0
    assert json.loads((tmp_path / "saida" / "memecoins.json").read_text())["ao_vivo"]["compras"] == 1
    relogio[0] += 40 * 60
    rodar_memecoins.main(tmp_path, gecko=g, relogio=lambda: relogio[0])
    v = json.loads((tmp_path / "saida" / "memecoins.json").read_text())["ao_vivo"]
    primeira = next(x for x in v["abertas"] if x["simbolo"] == "NOVA" and x["tipo"] == "lancamento" and x["entrou"] < (T0 + 3 * 60000))
    assert primeira["pool"].startswith("swaptoka") and primeira["dobrou"] and primeira["max"] == pytest.approx(2.5, abs=0.01)
    assert any("/ohlcv/" in c and "swaptoka" in c for c in g.pedidos)
    hora = [x for x in v["abertas"] if x["tipo"] == "hora"]
    assert [x["simbolo"] for x in hora] == ["BONK2"] and hora[0]["medidas"]["subiu"] == 3.0
    e = {x["id"]: x for x in v["por_estrategia"]}
    assert e["lancamento"]["compras"] == 2 and e["hora"]["compras"] == 1
