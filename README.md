# Dashboard local de ciclismo

Aplicación en Streamlit para consultar entrenamientos de Garmin Connect e
intervals.icu, con almacenamiento local SQLite.

## Funciones

- **Resumen:** volumen semanal, reparto por deporte e interior/exterior.
- **Forma:** CTL, ATL, TSB y tendencia descriptiva del CTL a una semana.
- **Ciclismo:** curva de potencia, carga y volumen.
- **Zonas:** tiempo por zonas de frecuencia cardiaca y potencia.
- **Actividades:** sesiones, perfiles disponibles, comparación con planificación
  y resumen de actividad en TXT/JSON.
- **Salud:** sueño, calidad, frecuencia cardiaca en reposo, HRV y peso.
- **Planificación:** sesiones previstas enlazables con actividades realizadas.

## Requisitos y puesta en marcha

Requiere Python 3.12 y las dependencias de `requirements.txt`.

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Rellena `.env` con las credenciales que quieras usar. Después, inicia la app:

```powershell
python main.py login
python main.py sync --full
python main.py sync-health --days 90
python main.py sync-intervals --days 365
python -m streamlit run app.py
```

También puedes abrir `iniciar_dashboard.bat` en Windows o ejecutar
`bash iniciar_dashboard.sh` desde Git Bash. La app se abre en
`http://localhost:8501`.

## Datos y privacidad

La base SQLite, los tokens de Garmin, las credenciales, el plan personal y las
exportaciones se mantienen fuera de Git. `.gitignore` excluye `.env`, `data/`,
`artifacts/` y `planning_bloque_1.json`. No publiques credenciales ni datos
personales al subir el código a GitHub. El repositorio no tendrá un remoto
configurado hasta que elijas o crees uno.

Para configurar un repositorio GitHub después de crearlo:

```bash
git remote add origin <URL_DEL_REPOSITORIO>
git push -u origin master
```

## Datos de demostración

Puedes crear una base sintética sin conectar cuentas:

```bash
python scripts/seed_demo.py --force
```

Después inicia Streamlit con `GARMIN_DB_PATH=data/demo.db` y
`GARMIN_DEMO=1` configurados en el entorno.
