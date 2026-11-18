Estás en la carpeta de un proyecto ya terminado llamado `market-scanner` (lee README.md primero).
Es un escáner bursátil en Python (yfinance) que genera `docs/data/latest.json`, con un dashboard
estático en `docs/index.html` y un workflow de GitHub Actions en `.github/workflows/daily.yml`.
El código está escrito pero la descarga de Yahoo NUNCA se ha probado con red real. Tu trabajo es
probarlo, publicarlo y dejarlo funcionando solo. Pídeme confirmación únicamente cuando haga falta
iniciar sesión o aprobar un comando; el resto hazlo tú.

1. PRUEBA LOCAL. Crea un entorno virtual, instala `requirements.txt` y ejecuta
   `python -m scanner.run --limit 30`. Si algo falla en `scanner/data.py` (nombres de campos de
   yfinance, formato de `yf.download`, `eps_trend`, `calendar`, límites de peticiones), arréglalo.
   No cambies la lógica de `scanner/scoring.py` ni los umbrales de `scanner/config.py`.
   Comprueba en `docs/data/latest.json` que `demo` es false y que las acciones traen `sector`,
   `fwd_pe`, `quality`, `dd_52w`, `dd_ath` y, en las candidatas, `eps_rev_90d` y `earnings_date`
   con valores plausibles (contrasta 3 acciones conocidas con Yahoo Finance).
   Después borra `cache/*.json` y `docs/data/history.json` para que el repositorio empiece limpio,
   y regenera el dashboard de muestra con `python -m scanner.run --demo`.

2. GITHUB. Comprueba `gh auth status` (si no hay sesión, guíame con `gh auth login`). Inicializa git
   en esta carpeta, crea un repositorio PÚBLICO llamado `market-scanner` en mi cuenta con
   `gh repo create` y sube todo a la rama `main`.

3. PAGES. Activa GitHub Pages con origen "GitHub Actions":
   `gh api -X POST repos/{owner}/market-scanner/pages -f build_type=workflow`
   (si ya existe, usa PUT).

4. PRIMER ESCANEO. Lanza el workflow con `gh workflow run "Escaneo diario"` y sigue la ejecución con
   `gh run watch`. La primera vez tarda 20-40 minutos porque descarga los fundamentales de ~600
   acciones. Si falla, lee los logs con `gh run view --log-failed`, corrige, sube y relanza hasta
   que termine en verde. Si Yahoo bloquea o limita las IPs de GitHub, sube las pausas y reduce
   el tamaño de los lotes en `scanner/config.py` y `scanner/data.py` antes de plantear otra fuente.

5. VERIFICA. Abre la URL de Pages, confirma que ya no sale el aviso de "datos de demostración" y
   revisa al pie la cobertura (acciones con precio y con fundamentales, tickers sin datos).
   Elimina de `universe/mdax.csv` los tickers que Yahoo no reconozca.

6. RESUMEN FINAL. Dame: la URL del dashboard, la URL del repositorio, cuántas alertas han salido
   y cuáles, qué has tenido que corregir, y cualquier limitación que hayas visto.
