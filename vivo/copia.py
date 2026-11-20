"""Copy trading em tempo real (simulação, sem dinheiro e sem chave): o gêmeo ao vivo da cópia fiel do laboratório.

O laboratório (lab/copia.py, de hora em hora no GitHub) refaz a cópia DEPOIS, com os fills que o radar coletou e o
preço das velas, supondo um atraso (60 s ou 10 s). Aqui é ao vivo: a cada poucos segundos a máquina olha a conta de
cada carteira do radar na Hyperliquid e, quando a posição dela numa moeda muda, cada cópia ajusta a sua subconta na
mesma volta.

Versão 2 (20/11/2026, pedido do João: "as mesmas ordens que faz no normal, para poder comparar"): o gêmeo começa do
estado do laboratório (as mesmas cópias, as mesmas subcontas, o mesmo saldo e as mesmas posições abertas) e segue as
mesmas regras: quem entra, alavancagem, teto, parada de proteção, taxa (lab.copia). Dali em diante as ordens são as
mesmas; o que muda é só o que a máquina tem de diferente:

- o atraso é o de verdade: a ordem sai na volta em que a mudança foi vista (alguns segundos), não 60 s ou 10 s depois;
- o preço de execução vem do livro de ofertas daquele instante (o que uma ordem a mercado daquele tamanho pagaria),
  não da vela do minuto com um escorregamento estimado;
- a proporção usa o saldo da carteira naquele instante (valor da posição ÷ saldo da conta), não a foto da hora.

O que a carteira operou entre a última rodada do laboratório e a partida do gêmeo é acertado na primeira olhada (os
fills desse intervalo dizem em quais moedas ela mexeu).

Duas medidas que só dá para tirar ao vivo:
- atraso de detecção: quanto tempo depois da ordem dela a máquina viu a mudança;
- custo do atraso: quanto pior (em centésimos de 1 %) foi o preço da cópia em relação ao preço que ela pegou.

Estado em vivo/dados/copia_estado.json; resultado em vivo/gemeo/saida/copia_fiel.json, no mesmo formato do
saida/copia_fiel.json do laboratório (o Nexus lê os dois com o mesmo código e põe lado a lado).
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from lab import copia as C

VERSAO = 2
# As mesmas cópias do laboratório. Ao vivo nenhuma espera: "atraso_s" vira 0 e o atraso que o laboratório supõe fica
# em "atraso_normal_s" (só informação). Por isso, ao vivo, a cópia de 60 s e a de 10 s são o mesmo robô.
VARIANTES = {nome: {**var, "atraso_s": 0, "atraso_normal_s": var["atraso_s"]} for nome, var in C.VARIANTES.items()}
CICLO_MIN_S = 3.0             # o mais rápido que a máquina olha todas as carteiras
ORCAMENTO = 600               # peso por minuto gasto olhando contas (o limite da Hyperliquid é 1200 por IP, e os
                              # laboratórios gêmeos usam uma parte: vivo/gemeos.py)
FOLGA_PARA_MEDIR = 250        # só confere os fills dela (peso 20+) quando sobra isso do orçamento
MAX_TERCEIROS = 0.8           # igual ao laboratório: carteira quase toda em mercados de terceiros fica de fora
MAX_LOG = 300
MAX_CURVA = 2000
MAX_MUDANCAS = 400
PONTO_CURVA_MS = 60_000       # um ponto da curva por minuto nas últimas horas: o Nexus compara o gêmeo com o normal no
RECENTE_MS = 3 * 3_600_000    # mesmo instante (o da última rodada do normal), e precisa do valor daquele minuto
PONTO_ANTIGO_MS = 10 * 60_000  # depois de 3 h fica um ponto a cada 10 minutos
GRAVAR_MS = 60_000
HORA = 3_600_000
SEMEAR_POR_VOLTA = 3          # carteiras acertadas por volta na partida (cada uma custa uma consulta de fills)
JANELA_SEMENTE_MS = 10 * 60_000


def _gravar(caminho: Path, obj) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(caminho)


def _ler(caminho: Path, padrao):
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return padrao


def afinar(curva: list, agora: int) -> list:
    """Guarda todos os pontos das últimas horas e, dos mais velhos, um a cada 10 minutos."""
    out: list = []
    for p in curva:
        if p[0] > agora - RECENTE_MS or not out or p[0] - out[-1][0] >= PONTO_ANTIGO_MS - 1000:
            out.append(p)
    return out


def _reduzir(curva: list, n: int = 400) -> list:
    if len(curva) <= n:
        return curva
    passo = len(curva) / n
    return [curva[int(i * passo)] for i in range(n)] + [curva[-1]]


class PrecosVivos:
    """O preço de agora de cada moeda. Faz o papel do Precos do laboratório (lá o preço depende do instante)."""

    def __init__(self):
        self.p: dict[str, float] = {}

    def atualizar(self, mids: dict) -> None:
        for moeda, px in (mids or {}).items():
            try:
                self.p[moeda] = float(px)
            except (TypeError, ValueError):
                continue

    def em(self, moeda: str, t: int | None = None) -> float | None:
        return self.p.get(moeda)

    ultimo = em


def preco_no_livro(livro: dict | None, delta: float, meio: float) -> float:
    """Preço médio de executar |delta| moedas a mercado agora: compra come as vendas do livro, da melhor para a pior
    (e a venda, as compras). Sem livro, ou para o que o livro mostrado não cobre, vale o escorregamento do laboratório."""
    pior = meio * (1 + C.ESCORREGA) if delta > 0 else meio * (1 - C.ESCORREGA)
    try:
        niveis = livro["levels"][1 if delta > 0 else 0]
    except (KeyError, IndexError, TypeError):
        return pior
    falta, custo = abs(delta), 0.0
    for n in niveis:
        try:
            px, sz = float(n["px"]), float(n["sz"])
        except (KeyError, TypeError, ValueError):
            continue
        pega = min(falta, sz)
        custo += pega * px
        falta -= pega
        pior = px * (1 + C.ESCORREGA) if delta > 0 else px * (1 - C.ESCORREGA)
        if falta <= 1e-12:
            break
    if falta > 1e-12:
        custo += falta * pior
    return custo / abs(delta)


def ler_conta(estado: dict) -> tuple[float, dict[str, float], dict[str, float]]:
    """Da resposta da Hyperliquid (clearinghouseState): saldo da conta, {moeda: quantidade com sinal} e
    {moeda: valor da posição em US$}. Só os perpétuos que dá para copiar."""
    saldo = float(((estado or {}).get("marginSummary") or {}).get("accountValue") or 0)
    pos, valor = {}, {}
    for ap in (estado or {}).get("assetPositions") or []:
        p = ap.get("position") or {}
        moeda = p.get("coin")
        try:
            q = float(p.get("szi") or 0)
        except (TypeError, ValueError):
            continue
        if moeda and q and C.copiavel_mercado(moeda):
            pos[moeda] = q
            valor[moeda] = abs(float(p.get("positionValue") or 0))
    return saldo, pos, valor


class CopiaAoVivo:
    nome = "copia"

    def __init__(self, raiz: Path, api, relogio, ler_fills=None):
        self.raiz, self.api, self.relogio = Path(raiz), api, relogio
        self.ler_fills = ler_fills
        self.precos = PrecosVivos()
        self.arq_estado = self.raiz / "vivo" / "dados" / "copia_estado.json"
        self.arq_saida = self.raiz / "vivo" / "gemeo" / "saida" / "copia_fiel.json"
        self.arq_radar = self.raiz / "saida" / "relatorio.json"
        self.arq_lab = self.raiz / "lab" / "dados" / "copia_estado.json"
        est = _ler(self.arq_estado, {})
        self.est = est if est.get("versao") == VERSAO else {"versao": VERSAO}
        self.est.setdefault("variantes", {})
        self.est.setdefault("vistas", {})         # carteira → {t, v (saldo), pos {moeda: quantidade}}: a última olhada
        self.est.setdefault("mudancas", [])       # as últimas mudanças de posição vistas
        self.est.setdefault("conferir", [])       # ids de mudanças que ainda falta medir (fills dela)
        self.est.setdefault("seq", 0)
        self.no_radar: dict[str, dict] = {}
        self.radar_lido = None                    # (mtime, tamanho) do relatorio.json já lido
        self.proximo = 0
        self.gravado = 0
        self.ciclo_ms = int(CICLO_MIN_S * 1000)
        self.livros: dict[str, dict | None] = {}  # livro de cada moeda, guardado só durante a volta
        self.falhas: list[int] = []               # instantes das consultas que falharam (última hora)
        self.voltas: list[tuple[int, int]] = []   # (instante, duração em ms) das últimas voltas
        self.acertar: dict[str, dict[str, set]] = {}   # partida: carteira → {cópia: moedas em que ela mexeu no intervalo}
        self.tentou: dict[str, int] = {}

    # ------------------------------------------------------------ a partida: o mesmo ponto do laboratório
    def semear(self, agora: int) -> None:
        """Começa do estado da cópia fiel do laboratório (as mesmas subcontas, saldos e posições). Sem esse estado
        (repositório novo), começa do zero, como o laboratório começaria."""
        lab = _ler(self.arq_lab, {})
        sem = {"t": agora, "ate": None, "de": "zero", "retorno": {}}
        if lab.get("variantes") and lab.get("ate"):
            for nome in VARIANTES:
                v = lab["variantes"].get(nome)
                if not v:
                    continue
                self.est["variantes"][nome] = {"subs": v.get("subs", {}), "curva": v.get("curva", []), "log": v.get("log", []),
                                               "pulos": v.get("pulos", {}), "fora": v.get("fora", {}), "fila": []}
                sem["retorno"][nome] = C.resumo(list(v.get("subs", {}).values()))["retorno"]
            self.est["inicio"] = lab.get("inicio", agora)
            sem.update(ate=lab["ate"], de="laboratório")
            self.est["a_acertar"] = self.carteiras()
        self.est["semente"] = sem

    def acertar_partida(self, w: str) -> None:
        """Em quais moedas a carteira mexeu depois da última ordem que o laboratório já tinha copiado (os fills dela
        desde um pouco antes da última rodada). Na primeira olhada, a cópia vai para a posição de agora nessas moedas."""
        ate = self.est["semente"]["ate"]
        fills = self.api.fills_desde(w, ate - JANELA_SEMENTE_MS)
        out: dict[str, set] = {}
        for nome, v in self.est["variantes"].items():
            sc = v["subs"].get(w)
            if not sc or not sc["vivo"]:
                continue
            moedas = {f["coin"] for f in fills if C.copiavel_mercado(f.get("coin", "@")) and int(f["time"]) > sc["ult"]}
            if moedas:
                out[nome] = moedas
        self.acertar[w] = out

    # ------------------------------------------------------------ quem é copiado
    def _terceiros(self, w: str) -> float:
        if self.ler_fills is None:
            from radar import armazenamento as A
            self.ler_fills = A.ler_fills
        try:
            return C.parte_terceiros(self.ler_fills(w))
        except Exception:  # noqa: BLE001  (sem os fills guardados, não dá para saber: entra)
            return 0.0

    def carregar_radar(self, agora: int) -> None:
        """Relê a lista do radar quando ela muda (o GitHub atualiza de hora em hora e a máquina baixa). Carteira nova
        ganha subconta; carteira que saiu do radar é fechada e congelada. As mesmas regras do laboratório."""
        try:
            st = self.arq_radar.stat()
            marca = (st.st_mtime_ns, st.st_size)
        except FileNotFoundError:
            return
        if marca == self.radar_lido:
            return
        rel = _ler(self.arq_radar, None)
        if not rel or not rel.get("carteiras"):
            return                                 # arquivo no meio de uma troca: tenta na próxima volta
        self.radar_lido = marca
        self.no_radar = {c["carteira"]: c for c in rel["carteiras"]}
        self.est.setdefault("inicio", agora)
        terceiros: dict[str, float] = {}
        for nome, var in VARIANTES.items():
            v = self.est["variantes"].setdefault(nome, {"subs": {}, "curva": [], "log": [], "pulos": {}, "fora": {},
                                                        "fila": []})
            for w, c in self.no_radar.items():
                if w in v["subs"]:
                    continue
                ok, motivo = C.copiavel(c, var)
                if ok:
                    if w not in terceiros:
                        terceiros[w] = self._terceiros(w)
                    if terceiros[w] > MAX_TERCEIROS:
                        ok, motivo = False, (f"{round(100 * terceiros[w])} % das ordens em mercados de terceiros "
                                             "(xyz:…), que têm saldo separado: não dá para copiar na proporção certa")
                if not ok:
                    v["fora"][w] = motivo
                    continue
                v["fora"].pop(w, None)
                v["subs"][w] = C.nova_subconta(w, agora, C.fator_de(c, var))
            for w, sc in v["subs"].items():
                if sc["vivo"] and w not in self.no_radar:
                    C.fechar_tudo(sc, self.precos, agora, v["log"], "saiu do radar")
                    sc.update(vivo=False, parou="saiu do radar", parou_em=agora, patrimonio=round(sc["colateral"], 2))

    def carteiras(self) -> list[str]:
        """As carteiras que alguma cópia ainda segue (as outras não precisam ser olhadas)."""
        vivas = {w for v in self.est["variantes"].values() for w, sc in v["subs"].items() if sc["vivo"]}
        return sorted(vivas)

    # ------------------------------------------------------------ ver a mudança
    def _mudanca(self, w: str, moeda: str, de: float | None, para: float, frac: float | None, t: int, antes_t: int,
                 so: set | None = None) -> dict:
        """Anota a mudança e põe na fila de cada cópia que segue a carteira (ou só das cópias em `so`)."""
        self.est["seq"] += 1
        mud = {"id": self.est["seq"], "t": t, "antes_t": antes_t, "w": w, "moeda": moeda, "de": de, "para": para,
               "frac": None if frac is None else round(frac, 6)}
        self.est["mudancas"].append(mud)
        if de is not None:
            self.est["conferir"].append(mud["id"])
        for nome, var in VARIANTES.items():
            if so is not None and nome not in so:
                continue
            v = self.est["variantes"].get(nome)
            if v and v["subs"].get(w, {}).get("vivo"):
                v["fila"].append({"exec": t + var["atraso_s"] * 1000, "t": t, "w": w, "moeda": moeda,
                                  "frac": mud["frac"], "mud": mud["id"]})
        return mud

    def ver(self, w: str, conta: dict, t: int) -> list[dict]:
        """Compara a conta da carteira com a última olhada. Cada moeda cuja posição mudou vira uma mudança, que entra
        na fila de cada cópia. Volta as mudanças."""
        saldo, pos, valor = ler_conta(conta)
        ant = self.est["vistas"].get(w)
        self.est["vistas"][w] = {"t": t, "v": round(saldo, 2), "pos": pos}

        def fracao(moeda: str) -> float | None:
            para = pos.get(moeda, 0.0)
            if not para:
                return 0.0
            if saldo > 0:
                return (1 if para > 0 else -1) * valor.get(moeda, 0.0) / saldo
            return None                            # conta sem saldo visível: não dá para saber a proporção

        novas = []
        if ant is None:
            # primeira olhada: só anota o que ela já tinha. Na partida, acerta as moedas em que ela mexeu depois da
            # última ordem que o laboratório copiou (uma mudança por moeda, para as cópias que ainda não a tinham visto)
            por_moeda: dict[str, set] = {}
            for nome, moedas in (self.acertar.pop(w, None) or {}).items():
                for moeda in moedas:
                    por_moeda.setdefault(moeda, set()).add(nome)
            for moeda in sorted(por_moeda):
                novas.append(self._mudanca(w, moeda, None, pos.get(moeda, 0.0), fracao(moeda), t,
                                           self.est["semente"]["ate"], por_moeda[moeda]))
        else:
            for moeda in sorted(set(pos) | set(ant["pos"])):
                de, para = ant["pos"].get(moeda, 0.0), pos.get(moeda, 0.0)
                if not C._perto(de, para):
                    novas.append(self._mudanca(w, moeda, de, para, fracao(moeda), t, ant["t"]))
        del self.est["mudancas"][:-MAX_MUDANCAS]
        del self.est["conferir"][:-60]
        return novas

    # ------------------------------------------------------------ executar (no papel)
    def _livro(self, moeda: str) -> dict | None:
        if moeda not in self.livros:
            try:
                self.livros[moeda] = self.api.livro(moeda)
            except Exception:  # noqa: BLE001  (sem livro, a ordem sai no preço do meio com o escorregamento padrão)
                self.livros[moeda] = None
                self.falhas.append(self.relogio())
        return self.livros[moeda]

    def aplicar(self, sc: dict, item: dict, var: dict, log: list, t: int) -> str | None:
        """Leva a subconta para a proporção nova da carteira. A mesma conta do laboratório (lab.copia.aplicar), com o
        preço do livro. Volta None (feito, ou nada a fazer) ou o motivo de ter pulado."""
        moeda, frac = item["moeda"], item["frac"]
        q = sc["pos"].get(moeda, (0.0, 0.0))[0]
        if frac == 0 and q == 0:
            return None                            # ela zerou uma posição que a cópia não tinha
        if frac is None:
            return "sem saldo da carteira"
        meio = self.precos.em(moeda)
        if meio is None:
            return "sem preço"
        pat = C.patrimonio(sc, self.precos, t)
        if pat <= 0:
            return "subconta zerada"
        alvo_valor = frac * sc["fator"] * pat
        teto = var["teto"] * pat - C.exposicao(sc, self.precos, t, sem=moeda)
        if abs(alvo_valor) > max(0.0, teto):
            alvo_valor = (1 if alvo_valor > 0 else -1) * max(0.0, teto)
        alvo = alvo_valor / meio
        delta = alvo - q
        if abs(delta) * meio < C.MINIMO and not (alvo == 0 and q != 0):
            return "ordem pequena"
        preco = preco_no_livro(self._livro(moeda), delta, meio)
        C.negociar(sc, moeda, delta, preco, t, log)
        log[-1]["mud"] = item["mud"]
        log[-1]["espera_ms"] = t - item["t"]
        sc["expo_max"] = max(sc["expo_max"], C.exposicao(sc, self.precos, t) / max(1e-9, C.patrimonio(sc, self.precos, t)))
        return None

    def executar(self, t: int) -> int:
        """Executa o que já venceu na fila de cada cópia. Volta quantos itens saíram das filas."""
        feitos = 0
        for nome, var in VARIANTES.items():
            v = self.est["variantes"].get(nome)
            if not v or not v["fila"]:
                continue
            fica = []
            for item in sorted(v["fila"], key=lambda i: (i["exec"], i["mud"])):
                if item["exec"] > t:
                    fica.append(item)
                    continue
                feitos += 1
                sc = v["subs"].get(item["w"])
                if not sc or not sc["vivo"]:
                    continue
                motivo = self.aplicar(sc, item, var, v["log"], t)
                if motivo:
                    v["pulos"][motivo] = v["pulos"].get(motivo, 0) + 1
                sc["ult"] = max(sc["ult"], item["t"])
                C.conferir(sc, self.precos, t, var, v["log"])
            v["fila"] = fica
            del v["log"][:-MAX_LOG]
        return feitos

    def proteger(self, t: int) -> None:
        """A cada volta, com o preço de agora: liquidação e parada de proteção de cada subconta, e o saldo dela."""
        for nome, var in VARIANTES.items():
            v = self.est["variantes"].get(nome)
            for sc in (v or {}).get("subs", {}).values():
                if sc["vivo"]:
                    C.conferir(sc, self.precos, t, var, v["log"])

    # ------------------------------------------------------------ medir o atraso de verdade
    def medir(self) -> None:
        """Quando sobra orçamento, busca os fills de uma carteira que mudou e anota, em cada mudança dela: quanto
        tempo depois do fill a máquina viu (atraso_ms) e o preço que ela pegou (px_dela)."""
        fila = self.est["conferir"]
        if not fila:
            return
        lim = getattr(self.api, "lim", None)
        if lim is not None and lim.usado() > lim.por_minuto - FOLGA_PARA_MEDIR:
            return
        por_id = {m["id"]: m for m in self.est["mudancas"]}
        primeira = por_id.get(fila[0])
        if primeira is None:
            fila.pop(0)
            return
        if self.relogio() - primeira["t"] < 2 * self.ciclo_ms:
            return                                 # dá um tempo para o fill aparecer na API
        w = primeira["w"]
        lote = [por_id[i] for i in fila if i in por_id and por_id[i]["w"] == w]
        self.est["conferir"] = [i for i in fila if i in por_id and por_id[i]["w"] != w]
        try:
            fills = self.api.fills_desde(w, min(m["antes_t"] for m in lote) - 2000, max(m["t"] for m in lote) + 1000)
        except Exception:  # noqa: BLE001  (medida perdida: não tenta de novo, para não gastar orçamento em falha)
            self.falhas.append(self.relogio())
            return
        for m in lote:
            seus = [f for f in fills if f.get("coin") == m["moeda"] and m["antes_t"] - 2000 <= int(f["time"]) <= m["t"] + 1000]
            if not seus:
                m["sem_fill"] = True               # mudou sem ordem dela (ajuste da bolsa) ou o fill ainda não apareceu
                continue
            qtd = sum(float(f["sz"]) for f in seus)
            m["atraso_ms"] = max(0, m["t"] - max(int(f["time"]) for f in seus))
            if qtd > 0:
                m["px_dela"] = round(sum(float(f["px"]) * float(f["sz"]) for f in seus) / qtd, 8)

    def custo_do_atraso(self, log: list) -> dict | None:
        """Quanto pior foi o preço da cópia em relação ao dela, em centésimos de 1 % (mediana das ordens recentes que
        foram para o mesmo lado da ordem dela). Positivo = a cópia pagou mais caro (ou vendeu mais barato)."""
        por_id = {m["id"]: m for m in self.est["mudancas"]}
        vals = []
        for o in log:
            m = por_id.get(o.get("mud"))
            if not m or not m.get("px_dela") or m.get("de") is None:
                continue
            compra = o["lado"] == "compra"
            if compra != (m["para"] > m["de"]):
                continue
            vals.append((1 if compra else -1) * (o["px"] / m["px_dela"] - 1) * 10_000)
        if not vals:
            return None
        return {"mediana": round(statistics.median(vals), 1), "ordens": len(vals)}

    # ------------------------------------------------------------ a volta
    def passo(self, agora: int) -> None:
        """Chamado o tempo todo pelo motor; faz uma volta quando chega a hora dela."""
        if agora < self.proximo:
            return
        try:
            self.precos.atualizar(self.api.mids())
        except Exception:  # noqa: BLE001  (segue com o preço da volta anterior)
            self.falhas.append(agora)
        if not self.precos.p:
            self.proximo = agora + 1000            # sem nenhum preço ainda, o saldo das subcontas sairia errado: espera
            return
        if "semente" not in self.est:
            self.semear(agora)
        self.carregar_radar(agora)
        ws = self.carteiras()
        self.ciclo_ms = int(max(CICLO_MIN_S, len(ws) * 2 * 60 / ORCAMENTO) * 1000)
        self.proximo = agora + self.ciclo_ms
        self.livros = {}
        a_acertar, acertadas = self.est.get("a_acertar") or [], 0
        for w in ws:
            if w in a_acertar:                     # partida: antes da primeira olhada, o que ela fez no intervalo
                if acertadas >= SEMEAR_POR_VOLTA:
                    continue
                acertadas += 1
                try:
                    self.acertar_partida(w)
                except Exception:  # noqa: BLE001
                    self.falhas.append(self.relogio())
                    self.tentou[w] = self.tentou.get(w, 0) + 1
                    if self.tentou[w] < 3:
                        continue                   # tenta de novo na próxima volta; na terceira falha, segue sem o acerto
                a_acertar.remove(w)
            try:
                conta = self.api.estado(w)
            except Exception:  # noqa: BLE001  (esta carteira fica para a próxima volta)
                self.falhas.append(self.relogio())
                if w in self.acertar:              # o acerto da partida espera a primeira olhada dar certo
                    a_acertar.append(w)
                continue
            self.ver(w, conta, self.relogio())
        t = self.relogio()
        self.executar(t)
        self.proteger(t)
        for nome, v in self.est["variantes"].items():
            ativas = list(v["subs"].values())
            if ativas and (not v["curva"] or t - v["curva"][-1][0] >= PONTO_CURVA_MS):
                v["curva"] = afinar(v["curva"] + [[t, C.resumo(ativas)["retorno"]]], t)[-MAX_CURVA:]
        try:
            self.medir()
        except Exception:  # noqa: BLE001  (medida é extra: nunca derruba a cópia)
            pass
        fim = self.relogio()
        self.voltas.append((fim, fim - agora))
        self.voltas = [x for x in self.voltas if x[0] > fim - HORA]
        self.falhas = [x for x in self.falhas if x > fim - HORA]
        if fim - self.gravado >= GRAVAR_MS:
            self.gravar(fim)

    # ------------------------------------------------------------ o que sai
    def montar_saida(self, agora: int) -> dict:
        """O mesmo formato do saida/copia_fiel.json do laboratório, e mais dois blocos só do gêmeo: "maquina" (as
        medidas ao vivo) e "semente" (de onde e quando ele partiu)."""
        mud = self.est["mudancas"]
        atrasos = [m["atraso_ms"] for m in mud if "atraso_ms" in m]
        duracoes = [d for _, d in self.voltas]
        saida = {
            "gerado": agora, "gerado_txt": datetime.fromtimestamp(agora / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "inicio": self.est.get("inicio", agora), "ate": agora, "versao": VERSAO, "ao_vivo": True,
            "modo": "simulação (sem dinheiro, sem chave)", "taxa": C.TAXA, "semente": self.est.get("semente"),
            "maquina": {
                "carteiras_olhadas": len(self.carteiras()), "volta_s": round(self.ciclo_ms / 1000, 1),
                "volta_demora_ms": round(statistics.median(duracoes)) if duracoes else None,
                "falhas_1h": len(self.falhas), "mudancas_1h": sum(1 for m in mud if m["t"] > agora - HORA),
                "mudancas": self.est["seq"], "a_acertar": len(self.est.get("a_acertar") or []),
                "atraso_deteccao_ms": ({"mediana": round(statistics.median(atrasos)), "pior": max(atrasos),
                                        "medidas": len(atrasos)} if atrasos else None),
            },
            "variantes": {},
        }
        for nome, var in VARIANTES.items():
            v = self.est["variantes"].get(nome)
            if not v:
                continue
            subs = []
            for w, sc in v["subs"].items():
                abertas = []
                for m, (q, a) in sc["pos"].items():
                    p = self.precos.em(m) or a
                    abertas.append({"moeda": m, "lado": "long" if q > 0 else "short", "valor": round(abs(q) * p, 2),
                                    "resultado": round(q * (p - a), 2)})
                c = self.no_radar.get(w, {})
                subs.append({"w": w, "apelido": c.get("apelido", ""), "inicio": sc["inicio"],
                             "retorno": round(sc["patrimonio"] / sc["capital"] - 1, 5), "patrimonio": sc["patrimonio"],
                             "vivo": sc["vivo"], "parou": sc["parou"], "parou_em": sc["parou_em"],
                             "ordens": sc["ordens"], "taxas": round(sc["taxas"], 2), "fator": round(sc["fator"], 3),
                             "expo_max": round(sc["expo_max"], 2), "abertas": abertas,
                             "classe": c.get("classe_nome", ""), "tipo": (c.get("operador") or {}).get("rotulo", ""),
                             "duracao_min": (c.get("geral") or {}).get("duracao_mediana_min")})
            subs.sort(key=lambda s: -s["retorno"])
            saida["variantes"][nome] = {
                "nome": C.VARIANTES[nome]["nome"], "regras": {k: var[k] for k in var if k != "nome"},
                **C.resumo(list(v["subs"].values())),
                "curva": (_reduzir([p for p in v["curva"] if p[0] <= agora - RECENTE_MS], 300)
                          + [p for p in v["curva"] if p[0] > agora - RECENTE_MS]), "subcontas": subs,
                "ordens_recentes": v["log"][-150:], "pulos": v["pulos"], "na_fila": len(v["fila"]),
                "custo_do_atraso_bps": self.custo_do_atraso(v["log"]),
                "fora": [{"w": w, "motivo": m} for w, m in v["fora"].items()],
            }
        return saida

    def gravar(self, agora: int) -> None:
        self.gravado = agora
        _gravar(self.arq_estado, self.est)
        _gravar(self.arq_saida, self.montar_saida(agora))

    def fechar(self) -> None:
        self.gravar(self.relogio())

    def resumo(self, agora: int) -> dict:
        """O que vai no sinal de vida da máquina (saida/maquina.json)."""
        mud = self.est["mudancas"]
        atrasos = [m["atraso_ms"] for m in mud if "atraso_ms" in m]
        return {"carteiras": len(self.carteiras()), "volta_s": round(self.ciclo_ms / 1000, 1),
                "mudancas_1h": sum(1 for m in mud if m["t"] > agora - HORA), "falhas_1h": len(self.falhas),
                "atraso_deteccao_ms": round(statistics.median(atrasos)) if atrasos else None,
                "partiu": (self.est.get("semente") or {}).get("t"),
                "retorno": {nome: C.resumo(list(v["subs"].values()))["retorno"]
                            for nome, v in self.est["variantes"].items() if v["subs"]}}
