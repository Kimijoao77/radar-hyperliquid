"""Monta as operações (entrou → saiu) a partir dos fills.

Um fill é uma execução de ordem. Uma operação começa quando a posição sai de zero e termina
quando volta a zero (ou vira para o outro lado). Cada fill traz a posição antes dele (sp), então
dá para remontar tudo mesmo com várias entradas e saídas parciais.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Operacao:
    moeda: str
    lado: str                 # "long" ou "short"
    t0: int
    t1: int | None = None
    parcial: bool = False     # começou antes dos dados que temos (não entra nas estatísticas)
    qtd_entrada: float = 0.0
    nocional_entrada: float = 0.0
    qtd_saida: float = 0.0
    nocional_saida: float = 0.0
    pos_max: float = 0.0
    pnl: float = 0.0          # PnL realizado bruto (closedPnl)
    taxas: float = 0.0
    fills: int = 0
    maker: int = 0
    ordens_entrada: set = field(default_factory=set)
    medio_prejuizo: int = 0   # entradas feitas com a operação no prejuízo (preço médio)
    saidas_taker_perda: int = 0
    saidas_perda: int = 0
    liquidada: bool = False

    @property
    def fechada(self) -> bool:
        return self.t1 is not None

    @property
    def preco_entrada(self) -> float:
        return self.nocional_entrada / self.qtd_entrada if self.qtd_entrada else 0.0

    @property
    def preco_saida(self) -> float:
        return self.nocional_saida / self.qtd_saida if self.qtd_saida else 0.0

    @property
    def resultado(self) -> float:
        """PnL líquido (já descontadas as taxas)."""
        return self.pnl - self.taxas

    @property
    def nocional_max(self) -> float:
        return self.pos_max * (self.preco_entrada or self.preco_saida)

    @property
    def retorno(self) -> float:
        """Resultado sobre o tamanho máximo da posição (sem alavancagem). 0,01 = 1 %."""
        n = self.nocional_max
        return self.resultado / n if n else 0.0

    @property
    def duracao_min(self) -> float:
        return ((self.t1 or self.t0) - self.t0) / 60000

    def resumo(self) -> dict:
        return {"moeda": self.moeda, "lado": self.lado, "t0": self.t0, "t1": self.t1, "parcial": self.parcial,
                "entrada": round(self.preco_entrada, 6), "saida": round(self.preco_saida, 6),
                "nocional": round(self.nocional_max, 2), "resultado": round(self.resultado, 2),
                "retorno": round(self.retorno, 5), "duracao_min": round(self.duracao_min, 1),
                "fills": self.fills, "ordens_entrada": len(self.ordens_entrada), "liquidada": self.liquidada}


def _sinal(x: float, eps: float) -> int:
    return 0 if abs(x) <= eps else (1 if x > 0 else -1)


def montar(fills: list[dict]) -> list[Operacao]:
    """fills compactados (armazenamento.compactar), em qualquer ordem. Devolve as operações em ordem de início."""
    abertas: dict[str, Operacao] = {}
    ops: list[Operacao] = []
    for f in sorted(fills, key=lambda f: (f["t"], f.get("id") or 0)):
        moeda, sp, z = f["c"], f["sp"], f["z"]
        if z <= 0:
            continue
        d = z if f["s"] == "B" else -z
        depois = sp + d
        eps = 1e-9 * max(1.0, abs(sp), abs(depois))
        s0, s1 = _sinal(sp, eps), _sinal(depois, eps)
        op = abertas.get(moeda)

        # dados começam no meio de uma posição: operação parcial
        if op is None and s0 != 0:
            op = Operacao(moeda, "long" if s0 > 0 else "short", f["t"], parcial=True, pos_max=abs(sp))
            abertas[moeda] = op
            ops.append(op)
        # operação na memória não bate com a posição informada (fills faltando): fecha como parcial
        if op is not None and s0 == 0:
            op.t1 = op.t1 or f["t"]; op.parcial = True
            abertas.pop(moeda, None); op = None

        def abrir(qtd: float, lado_sinal: int) -> Operacao:
            o = Operacao(moeda, "long" if lado_sinal > 0 else "short", f["t"])
            abertas[moeda] = o
            ops.append(o)
            return o

        if s0 == 0:  # abre do zero
            op = abrir(abs(d), s1)
            _entrada(op, f, abs(d), 1.0, 0.0)
        elif s1 == s0 and abs(depois) > abs(sp) + eps:  # aumenta a posição
            _entrada(op, f, abs(d), 1.0, sp)
        elif s1 == s0 or s1 == 0:  # reduz ou zera
            _saida(op, f, abs(d), 1.0)
            if s1 == 0:
                op.t1 = f["t"]
                abertas.pop(moeda, None)
        else:  # virou de lado: fecha tudo e abre o resto do outro lado
            fecha = abs(sp)
            frac = fecha / z
            _saida(op, f, fecha, frac)
            op.t1 = f["t"]
            abertas.pop(moeda, None)
            novo = abrir(abs(depois), s1)
            _entrada(novo, f, abs(depois), 1 - frac, 0.0, pnl=False)
        if op is not None and op.t1 is None:
            op.pos_max = max(op.pos_max, abs(depois))
    return ops


def _entrada(op: Operacao, f: dict, qtd: float, frac: float, pos_antes: float, pnl: bool = True) -> None:
    preco = f["p"]
    if op.qtd_entrada and pos_antes:
        medio = op.preco_entrada
        if (op.lado == "long" and preco < medio * 0.999) or (op.lado == "short" and preco > medio * 1.001):
            op.medio_prejuizo += 1
    op.qtd_entrada += qtd
    op.nocional_entrada += qtd * preco
    op.taxas += f["f"] * frac
    if pnl:
        op.pnl += f["pnl"] * frac
    op.fills += 1
    op.maker += 0 if f["x"] else 1
    op.ordens_entrada.add(f.get("o"))
    op.pos_max = max(op.pos_max, abs(pos_antes) + qtd)


def _saida(op: Operacao, f: dict, qtd: float, frac: float) -> None:
    op.qtd_saida += qtd
    op.nocional_saida += qtd * f["p"]
    op.taxas += f["f"] * frac
    op.pnl += f["pnl"] * frac
    op.fills += 1
    op.maker += 0 if f["x"] else 1
    if f.get("liq"):
        op.liquidada = True
    if f["pnl"] < 0:
        op.saidas_perda += 1
        op.saidas_taker_perda += 1 if f["x"] else 0
