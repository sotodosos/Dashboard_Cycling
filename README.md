# Dashboard local de ciclismo

Aplicación en Streamlit para consultar entrenamientos de Garmin Connect e
intervals.icu. Los datos se almacenan localmente en una base SQLite.

## Secciones

- **Recuperación → Forma**: vista inicial con CTL, ATL y TSB, carga, tendencia
  de la forma y métricas recientes de recuperación.
- **Recuperación → Salud**: sueño, calidad del sueño, frecuencia cardiaca en
  reposo, HRV, peso y Body Battery cuando Garmin proporciona esos datos.
- **Entrenamiento → Ciclismo**: curva de potencia, volumen, carga, comparación
  de ciclismo en rodillo y exterior, y distribución agregada por zonas de FC y
  potencia.
- **Entrenamiento → Actividades**: listado filtrable, ficha y perfiles de cada
  sesión, zonas de la actividad y comparación con la planificación cuando hay
  datos disponibles.
- **Planificación**: objetivos y seguimiento semanal del plan.

## Requisitos y puesta en marcha

Requiere Python 3.12 y las dependencias de `requirements.txt`.

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Rellena `.env` con las credenciales que vayas a usar. Garmin se configura con
`GARMIN_EMAIL` y `GARMIN_PASSWORD`; intervals.icu es opcional y se configura
con `INTERVALS_API_KEY` y, si procede, `INTERVALS_ATHLETE_ID`.

Para sincronizar y abrir el dashboard:

```powershell
python main.py login
python main.py sync --full
python main.py sync-health --days 90
python main.py sync-intervals --days 365
python -m streamlit run app.py
```

También puedes iniciar Streamlit con `iniciar_dashboard.bat` en Windows o
ejecutar `bash iniciar_dashboard.sh` desde Git Bash. La dirección local es
`http://localhost:8501`.

## Datos y privacidad

El proyecto está pensado para ejecutarse localmente. `.gitignore` excluye
`.env`, tokens, la carpeta `data/` (incluidas las bases SQLite), las
exportaciones de `artifacts/` y el plan personal `planning_bloque_1.json`.
`.env.example` sí forma parte del repositorio y solo contiene valores de
ejemplo. No añadas credenciales, tokens ni datos personales al repositorio.

## Datos de demostración

Puedes crear una base sintética sin conectar cuentas:

```powershell
python scripts/seed_demo.py --force
$env:GARMIN_DB_PATH = "data/demo.db"
$env:GARMIN_DEMO = "1"
python -m streamlit run app.py
```

En Git Bash, configura las variables para el comando así:

```bash
GARMIN_DB_PATH=data/demo.db GARMIN_DEMO=1 python -m streamlit run app.py
```
