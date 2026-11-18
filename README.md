# Escáner de mercado

Dashboard diario que busca **empresas de calidad que han caído sin que su negocio empeore**
(S&P 500, DAX, MDAX y los tickers extra que añadas). Gratis: datos de Yahoo Finance,
ejecución en GitHub Actions y web en GitHub Pages.

## Cómo funciona

1. `scanner/run.py` descarga precios (diario) y fundamentales (semanal, escalonado) con `yfinance`.
2. `scanner/scoring.py` calcula **calidad** y **valoración** (0-100) y clasifica cada acción:
   - **Alerta**: calidad ≥ 65, valoración ≥ 50, caída ≥ 25 % desde el máximo de 52 semanas
     y estimaciones de EPS estables (no han bajado más de un 5 % en 90 días).
   - **Estimaciones a la baja**: misma caída, pero los analistas recortan beneficios (posible trampa de valor).
   - **Vigilar**: calidad con caída ≥ 15 %, o caída ≥ 25 % sin estar barata.
3. El resultado se guarda en `docs/data/latest.json` y `docs/index.html` lo muestra.
4. `.github/workflows/daily.yml` lo ejecuta de martes a sábado a las 05:17 UTC y publica la web.

## Ajustes

- Umbrales de la estrategia: `scanner/config.py`.
- Añadir acciones: una línea en `universe/extra.csv` (`ticker;nombre;US` o `DE`, con el ticker de Yahoo).
- `universe/mdax.csv` es una lista aproximada; los tickers que Yahoo no reconozca se omiten y aparecen al pie del dashboard.

## Uso en local

```bash
pip install -r requirements.txt
python -m scanner.run --limit 30   # prueba rápida con datos reales
python -m scanner.run              # escaneo completo (la primera vez tarda 20-40 min)
python -m scanner.run --demo       # datos inventados, sin red
cd docs && python -m http.server   # abre http://localhost:8000
```

## Limitaciones

- Yahoo Finance es una fuente gratuita no oficial: puede limitar peticiones o cambiar sin aviso.
  El escáner reintenta, usa caché y no publica si faltan más de la mitad de los precios.
- No hay media histórica de P/E por empresa (no está disponible gratis); la valoración se compara con el sector.
- Es un filtro para generar ideas, no una recomendación de compra.
