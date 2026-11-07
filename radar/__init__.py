

def proxima_segunda(ms: int) -> int:
    """Próxima segunda-feira às 11:00 de Brasília (14:00 UTC) depois de `ms` (a triagem semanal das carteiras novas)."""
    from datetime import datetime, timedelta, timezone
    d = datetime.fromtimestamp(ms / 1000, timezone.utc)
    alvo = d.replace(hour=14, minute=0, second=0, microsecond=0) + timedelta(days=(0 - d.weekday()) % 7)
    if alvo <= d:
        alvo += timedelta(days=7)
    return int(alvo.timestamp() * 1000)
