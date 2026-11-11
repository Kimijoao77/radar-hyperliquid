"""Peças dos testes que nascem das ideias dos vídeos (11/11/2026). Tudo é simulação com dados públicos: nada aqui
compra, vende, entra em conta de ninguém ou usa chave. Um teste é um arquivo lab/ideias/<id>.py com

    NOME = "Nome curto"            # aparece no app
    COMO = "uma linha"             # o que o robô faz
    CAPITAL = 1000.0               # dinheiro de mentira (US$; ou R$ com MOEDA = "R$")
    INTERVALO_H = 1                # de quantas em quantas horas ele roda (1 = toda hora)
    def rodar(ctx): ...            # uma rodada: lê os dados, decide, compra/vende na carteira de mentira

mais uma linha em lab/ideias/indice.json. O lab/rodar_ideias.py chama rodar() de hora em hora, guarda o estado em
lab/dados/ideias/<id>.json e o resultado de todos em saida/ideias.json (o Nexus e o site mostram no Placar).
Guia completo: lab/ideias/COMO.md.
"""
from __future__ import annotations

import time

import requests

INFO = "https://api.hyperliquid.xyz/info"
TAXA_HL = 0.00045            # taxa de quem toma liquidez na Hyperliquid (0,045 %)
NAVEGADOR = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
S = requests.Session()


def _post_hl(corpo: dict, tentativas: int = 4):
    espera = 2.0
    for _ in range(tentativas):
        try:
            r = S.post(INFO, json=corpo, timeout=30)
            if r.status_code == 200:
                return r.json()
        except requests.RequestException:
            pass
        time.sleep(espera)
        espera *= 2
    raise RuntimeError(f"Hyperliquid não respondeu ({corpo.get('type')})")


def _get(url: str, tentativas: int = 3, timeout: int = 60, ua: str = "placar-ideias/1.0"):
    espera = 3.0
    for _ in range(tentativas):
        try:
            r = S.get(url, timeout=timeout, headers={"User-Agent": ua})
            if r.status_code == 200:
                return r.json()
        except (requests.RequestException, ValueError):
            pass
        time.sleep(espera)
        espera *= 2
    raise RuntimeError(f"não consegui ler {url.split('?')[0]}")


class Carteira:
    """A carteira de mentira. Compra (long) e venda a descoberto (short, sem alavancagem: a margem é o valor) ficam
    em `posicoes`; `creditar` soma rendimento (juros, taxa de pool, funding) ou desconta custo."""

    def __init__(self, estado: dict, capital: float, agora_ms: int):
        self.e = estado.setdefault("carteira", {"caixa": float(capital), "posicoes": {}, "taxas": 0.0, "creditos": 0.0})
        self.ops = estado.setdefault("ops", [])
        self.agora = agora_ms

    @property
    def caixa(self) -> float:
        return self.e["caixa"]

    @property
    def posicoes(self) -> dict:
        return self.e["posicoes"]

    def _op(self, tipo: str, ativo: str, valor: float, preco: float | None, obs: str = "") -> dict:
        op = {"t": self.agora, "tipo": tipo, "ativo": ativo, "valor": round(valor, 4), "preco": preco, "obs": obs}
        self.ops.append(op)
        del self.ops[:-300]
        return op

    def comprar(self, ativo: str, usd: float, preco: float, taxa: float = TAXA_HL, obs: str = "") -> dict | None:
        usd = min(float(usd), self.caixa)
        if usd <= 0.01 or not preco or preco <= 0:
            return None
        custo = usd * taxa
        qtd = (usd - custo) / preco
        p = self.posicoes.get(ativo)
        if p and p.get("lado") == "venda":
            raise ValueError(f"{ativo} está vendido: feche a venda antes de comprar")
        if p:
            p["preco_medio"] = (p["preco_medio"] * p["qtd"] + preco * qtd) / (p["qtd"] + qtd)
            p["qtd"] += qtd
        else:
            self.posicoes[ativo] = {"lado": "compra", "qtd": qtd, "preco_medio": preco, "desde": self.agora}
        self.e["caixa"] -= usd
        self.e["taxas"] += custo
        return self._op("compra", ativo, usd, preco, obs)

    def vender(self, ativo: str, preco: float, qtd: float | None = None, taxa: float = TAXA_HL, obs: str = "") -> dict | None:
        """Vende (toda ou parte) uma posição comprada."""
        p = self.posicoes.get(ativo)
        if not p or p.get("lado") != "compra" or not preco:
            return None
        q = min(p["qtd"], qtd if qtd is not None else p["qtd"])
        bruto = q * preco
        custo = bruto * taxa
        self.e["caixa"] += bruto - custo
        self.e["taxas"] += custo
        resultado = (preco - p["preco_medio"]) * q - custo
        p["qtd"] -= q
        if p["qtd"] <= 1e-12:
            del self.posicoes[ativo]
        return self._op("venda", ativo, bruto, preco, obs or f"resultado {resultado:+.2f}")

    def abrir_venda(self, ativo: str, usd: float, preco: float, taxa: float = TAXA_HL, obs: str = "") -> dict | None:
        """Venda a descoberto (short) sem alavancagem: separa `usd` do caixa como margem."""
        usd = min(float(usd), self.caixa)
        if usd <= 0.01 or not preco or preco <= 0 or ativo in self.posicoes:
            return None
        custo = usd * taxa
        self.posicoes[ativo] = {"lado": "venda", "qtd": (usd - custo) / preco, "preco_medio": preco, "margem": usd - custo, "desde": self.agora}
        self.e["caixa"] -= usd
        self.e["taxas"] += custo
        return self._op("venda_descoberto", ativo, usd, preco, obs)

    def fechar_venda(self, ativo: str, preco: float, taxa: float = TAXA_HL, obs: str = "") -> dict | None:
        p = self.posicoes.get(ativo)
        if not p or p.get("lado") != "venda" or not preco:
            return None
        pnl = (p["preco_medio"] - preco) * p["qtd"]
        custo = p["qtd"] * preco * taxa
        self.e["caixa"] += max(0.0, p["margem"] + pnl - custo)
        self.e["taxas"] += custo
        del self.posicoes[ativo]
        return self._op("recompra", ativo, p["qtd"] * preco, preco, obs or f"resultado {pnl - custo:+.2f}")

    def creditar(self, valor: float, motivo: str, ativo: str = "") -> dict:
        """Rendimento (positivo) ou custo (negativo) que entra direto no caixa: juros, taxa de pool, funding, gás."""
        self.e["caixa"] += float(valor)
        self.e["creditos"] += float(valor)
        return self._op("credito" if valor >= 0 else "custo", ativo, float(valor), None, motivo)

    def valor(self, precos: dict) -> float:
        """Quanto a carteira vale com os preços de agora. Sem preço de um ativo, usa o preço médio dele."""
        v = self.caixa
        for a, p in self.posicoes.items():
            px = precos.get(a) or p["preco_medio"]
            if p.get("lado") == "venda":
                v += max(0.0, p["margem"] + (p["preco_medio"] - px) * p["qtd"])
            else:
                v += p["qtd"] * px
        return v


class DadosHL:
    """Dados públicos da Hyperliquid (perpétuos): preços, velas e funding."""

    def __init__(self):
        self._mids = None
        self._ctx = None

    def precos(self) -> dict[str, float]:
        if self._mids is None:
            self._mids = {k: float(v) for k, v in (_post_hl({"type": "allMids"}) or {}).items()}
        return self._mids

    def velas(self, moeda: str, intervalo: str = "1h", n: int = 200) -> list[dict]:
        """As últimas n velas: [{t (ms), o, h, l, c, v}], da mais velha para a mais nova."""
        passo = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}[intervalo] * 1000
        fim = int(time.time() * 1000)
        pag = _post_hl({"type": "candleSnapshot", "req": {"coin": moeda, "interval": intervalo, "startTime": fim - passo * (n + 1), "endTime": fim}}) or []
        return [{"t": int(x["t"]), "o": float(x["o"]), "h": float(x["h"]), "l": float(x["l"]), "c": float(x["c"]), "v": float(x["v"])} for x in pag][-n:]

    def contextos(self) -> dict[str, dict]:
        """Para cada moeda: funding (por hora), juros em aberto, volume do dia, preço da marca."""
        if self._ctx is None:
            meta, ctxs = _post_hl({"type": "metaAndAssetCtxs"})
            self._ctx = {u["name"]: {"funding_h": float(c.get("funding") or 0), "aberto": float(c.get("openInterest") or 0),
                                     "volume_dia": float(c.get("dayNtlVlm") or 0), "preco": float(c.get("markPx") or 0)}
                         for u, c in zip(meta["universe"], ctxs)}
        return self._ctx

    def funding_historico(self, moeda: str, desde_ms: int) -> list[dict]:
        return [{"t": int(f["time"]), "taxa": float(f["fundingRate"])} for f in _post_hl({"type": "fundingHistory", "coin": moeda, "startTime": int(desde_ms)}) or []]


class DadosLlama:
    """Rendimentos de pools, empréstimos e cofres de DeFi (DefiLlama, público e sem chave)."""

    def __init__(self):
        self._pools = None

    def pools(self) -> list[dict]:
        """Todas as pools: pool (id), chain, project, symbol, tvlUsd, apy, apyBase, apyReward, stablecoin, ilRisk."""
        if self._pools is None:
            self._pools = _get("https://yields.llama.fi/pools", timeout=120).get("data", [])
        return self._pools

    def historico(self, pool_id: str) -> list[dict]:
        """APY e TVL dia a dia de uma pool: [{timestamp, tvlUsd, apy, apyBase, apyReward}]."""
        return _get(f"https://yields.llama.fi/chart/{pool_id}").get("data", [])


class DadosBR:
    """Bolsa e juros (para ideias de canais de investimento do Brasil): taxas do Banco Central (CDI, Selic, IPCA) e
    velas diárias do Yahoo Finance de ações, FIIs e ETFs da B3 (com ".SA": PETR4.SA, HGLG11.SA, BOVA11.SA), índices
    (^BVSP), ações de fora (AAPL) e câmbio (BRL=X = reais por dólar). Públicos e sem chave."""

    SERIES = {"cdi": 12, "selic": 11, "ipca": 433}     # CDI e Selic em % ao dia útil; IPCA em % no mês

    def __init__(self):
        self._velas: dict = {}
        self._divs: dict = {}

    def juros(self, serie: str = "cdi", ultimos: int = 30) -> list[dict]:
        """[{data: "AAAA-MM-DD", valor}] da série do Banco Central ("cdi", "selic", "ipca" ou o número da série)."""
        cod = self.SERIES.get(serie, serie)
        out = []
        for x in _get(f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{cod}/dados/ultimos/{int(ultimos)}?formato=json") or []:
            d, m, a = x["data"].split("/")
            out.append({"data": f"{a}-{m}-{d}", "valor": float(x["valor"])})
        return out

    def velas(self, ticker: str, periodo: str = "1y", intervalo: str = "1d") -> list[dict]:
        """[{t (ms), o, h, l, c, ajustado}] da mais velha para a mais nova (ajustado = com proventos reinvestidos).
        periodo: 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, max; intervalo: 1d, 1wk, 1mo (ou 1h nos últimos 730 dias)."""
        chave = (ticker, periodo, intervalo)
        if chave not in self._velas:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={periodo}&interval={intervalo}&events=div"
            r = _get(url, ua=NAVEGADOR)["chart"]["result"][0]
            q = r["indicators"]["quote"][0]
            adj = ((r["indicators"].get("adjclose") or [{}])[0].get("adjclose")) or q["close"]
            self._velas[chave] = [{"t": int(t) * 1000, "o": q["open"][i], "h": q["high"][i], "l": q["low"][i], "c": q["close"][i],
                                   "ajustado": adj[i] if adj[i] is not None else q["close"][i]}
                                  for i, t in enumerate(r.get("timestamp") or []) if q["close"][i] is not None]
            divs = ((r.get("events") or {}).get("dividends") or {}).values()
            self._divs[ticker] = sorted(({"t": int(d["date"]) * 1000, "valor": float(d["amount"])} for d in divs), key=lambda d: d["t"])
        return self._velas[chave]

    def proventos(self, ticker: str, periodo: str = "2y") -> list[dict]:
        """Dividendos e rendimentos pagos por cota/ação: [{t (ms, data com), valor}]."""
        self.velas(ticker, periodo)
        return self._divs.get(ticker, [])

    def preco(self, ticker: str) -> float:
        return float(self.velas(ticker, "5d")[-1]["c"])


class Contexto:
    """O que cada rodada recebe: carteira, memória livre do teste, dados e um jeito de deixar uma nota para o app."""

    def __init__(self, tid: str, estado: dict, capital: float, agora_ms: int, hl: DadosHL, llama: DadosLlama,
                 br: DadosBR | None = None):
        self.id = tid
        self.agora = agora_ms
        self.estado = estado
        self.memoria = estado.setdefault("memoria", {})       # livre: o teste guarda aqui o que quiser lembrar
        self.carteira = Carteira(estado, capital, agora_ms)
        self.hl = hl
        self.llama = llama
        self.br = br or DadosBR()
        self.precos_extras: dict[str, float] = {}            # preço de ativos que não estão na Hyperliquid
        self.texto_nota = None

    def nota(self, texto: str) -> None:
        """Uma frase para o app (ex.: "comprado em SOL desde 10/11; próxima revisão às 20h")."""
        self.texto_nota = str(texto)[:240]

    def precos(self) -> dict[str, float]:
        """Preços de agora para avaliar a carteira. Se o teste só usa ativos de fora da Hyperliquid (precos_extras),
        nem consulta a Hyperliquid."""
        posicoes = set(self.carteira.posicoes)
        if posicoes and posicoes <= set(self.precos_extras):
            return dict(self.precos_extras)
        return {**self.hl.precos(), **self.precos_extras}

    def buscar(self, url: str, navegador: bool = False):
        """Qualquer API pública em JSON, sem chave (ex.: CoinGecko). Para sites que recusam robôs, use navegador=True."""
        return _get(url, ua=NAVEGADOR if navegador else "placar-ideias/1.0")
