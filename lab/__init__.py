"""Os laboratórios (testes com dinheiro de mentira)."""
import os


def sem_espera() -> bool:
    """Cada laboratório tem o seu intervalo mínimo entre rodadas (o fluxo do GitHub chama todos de hora em hora e cada
    um pula se ainda é cedo). A máquina 24 h (vivo/gemeos.py) roda os gêmeos no ritmo dela e desliga essa espera."""
    return os.environ.get("LAB_SEM_ESPERA") == "1"
