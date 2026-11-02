"""Cliente da API pública da Hyperliquid (sem chave, sem conta).

Limite oficial: 1200 de "peso" por minuto por IP. Cada tipo de consulta tem um peso:
  - clearinghouseState: 2
  - userFillsByTime, portfolio, candleSnapshot e as outras: 20
  - userFillsByTime ainda soma +1 a cada 20 fills devolvidos (candleSnapshot: +1 a cada 60 velas)
O Limitador guarda o que foi gasto no último minuto e espera quando o orçamento acaba.
"""
from __future__ import annotations

import math
import time
from collections import deque

import requests

INFO = "https://api.hyperliquid.xyz/info"
LEADERBOARD = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"


class Limitador:
    """Orçamento de peso por janela de 60 s (fica abaixo do limite oficial por segurança)."""

    def __init__(self, por_minuto: int = 1000, relogio=time.monotonic, dormir=time.sleep):
        self.por_minuto = por_minuto
        self.gastos: deque[tuple[float, int]] = deque()
        self.relogio, self.dormir = relogio, dormir
        self.total = 0

    def _limpar(self, agora: float) -> None:
        while self.gastos and agora - self.gastos[0][0] >= 60:
            self.gastos.popleft()

    def usado(self) -> int:
        self._limpar(self.relogio())
        return sum(p for _, p in self.gastos)

    def gastar(self, peso: int) -> None:
        peso = max(0, int(peso))
        while True:
            agora = self.relogio()
            self._limpar(agora)
            if sum(p for _, p in self.gastos) + peso <= self.por_minuto or not self.gastos:
                self.gastos.append((agora, peso))
                self.total += peso
                return
            self.dormir(max(0.05, 60 - (agora - self.gastos[0][0]) + 0.05))


class Hyperliquid:
    def __init__(self, por_minuto: int = 1000, sessao: requests.Session | None = None, tentativas: int = 5):
        self.lim = Limitador(por_minuto)
        self.s = sessao or requests.Session()
        self.tentativas = tentativas

    def _post(self, corpo: dict, peso: int):
        self.lim.gastar(peso)
        espera = 2.0
        for i in range(self.tentativas):
            try:
                r = self.s.post(INFO, json=corpo, timeout=30)
            except requests.RequestException:
                r = None
            if r is not None and r.status_code == 200:
                return r.json()
            if r is not None and r.status_code not in (429, 500, 502, 503, 504):
                raise RuntimeError(f"Hyperliquid respondeu {r.status_code}: {r.text[:200]}")
            time.sleep(espera)
            espera = min(espera * 2, 60)
        raise RuntimeError(f"Hyperliquid não respondeu depois de {self.tentativas} tentativas ({corpo.get('type')})")

    # ---------- consultas ----------
    def leaderboard(self) -> list[dict]:
        """Ranking público (o mesmo da página Leaderboard). Cada linha: ethAddress, accountValue,
        displayName, windowPerformances = [[janela, {pnl, roi, vlm}], ...] (day, week, month, allTime)."""
        r = self.s.get(LEADERBOARD, timeout=60)
        r.raise_for_status()
        return r.json().get("leaderboardRows", [])

    def estado(self, usuario: str) -> dict:
        """Conta perp agora: marginSummary.accountValue, assetPositions (posições abertas)."""
        return self._post({"type": "clearinghouseState", "user": usuario}, 2)

    def portfolio(self, usuario: str):
        """Histórico de saldo e PnL por janela (day, week, month, allTime)."""
        return self._post({"type": "portfolio", "user": usuario}, 20)

    def fills_desde(self, usuario: str, inicio_ms: int, fim_ms: int | None = None, maximo: int = 10000) -> list[dict]:
        """Todos os fills (execuções) a partir de inicio_ms, paginando de 2000 em 2000.
        A Hyperliquid só guarda os 10 mil fills mais recentes de cada conta."""
        todos: dict[int, dict] = {}
        inicio = inicio_ms
        while len(todos) < maximo:
            corpo = {"type": "userFillsByTime", "user": usuario, "startTime": int(inicio), "aggregateByTime": True}
            if fim_ms:
                corpo["endTime"] = int(fim_ms)
            pag = self._post(corpo, 20) or []
            self.lim.gastar(math.ceil(len(pag) / 20))  # peso extra pelos itens devolvidos
            novos = 0
            for f in pag:
                chave = f.get("tid") or hash((f.get("time"), f.get("oid"), f.get("px"), f.get("sz")))
                if chave not in todos:
                    todos[chave] = f
                    novos += 1
            if len(pag) < 2000 or not novos:
                break
            inicio = max(f["time"] for f in pag) + 1
        return sorted(todos.values(), key=lambda f: (f["time"], f.get("tid", 0)))

    def velas(self, moeda: str, intervalo: str, inicio_ms: int, fim_ms: int) -> list[dict]:
        """Velas (para a fase 2: descobrir o que o robô olhou antes de entrar)."""
        pag = self._post({"type": "candleSnapshot", "req": {"coin": moeda, "interval": intervalo, "startTime": int(inicio_ms), "endTime": int(fim_ms)}}, 20) or []
        self.lim.gastar(math.ceil(len(pag) / 60))
        return pag
