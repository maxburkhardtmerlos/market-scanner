"""Parámetros de la estrategia. Cambia aquí los umbrales; no hace falta tocar nada más."""

DRAWDOWN_ALERT = 0.25      # caída mínima desde el máximo de 52 semanas para ALERTA
DRAWDOWN_WATCH = 0.15      # caída mínima para entrar en VIGILAR
QUALITY_MIN = 65           # puntuación de calidad mínima (0-100)
VALUATION_MIN = 50         # puntuación de valoración mínima (0-100) para ALERTA
EPS_REV_MIN = -0.05        # revisión máxima a la baja del EPS estimado en 90 días
EARNINGS_WARN_DAYS = 10    # aviso si faltan menos días para resultados
EARNINGS_WINDOW_DAYS = 14  # ventana del calendario de resultados
PE_ABS_CHEAP = 20          # referencia absoluta de P/E (solo informativa)

FUND_REFRESH_DAYS = 5      # los fundamentales se refrescan cada 5-9 días (escalonado)
ATH_REFRESH_DAYS = 30      # el máximo histórico completo se recalcula cada 30 días
FUND_TIME_BUDGET_S = 45 * 60   # tiempo máximo por ejecución descargando fundamentales
SLEEP_BETWEEN_CALLS_S = 0.4

INDICES = {
    "^GSPC": "S&P 500",
    "^NDX": "Nasdaq 100",
    "^GDAXI": "DAX",
    "^MDAXI": "MDAX",
    "^VIX": "VIX",
}
