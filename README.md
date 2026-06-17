# Facebook Comment Monitor

Aplicación de **escritorio** (Flet) para scrapear comentarios de publicaciones de
Facebook, guardarlos localmente y en Google Sheets, y extraer datos de los tickets
adjuntos mediante OCR (Vertex AI / Gemini).

## Estructura del proyecto

```
facebook-monitor/
│
├── app.py                    # Lanzador de la aplicación de escritorio
├── .env                      # Variables de entorno y configuración
├── credentials.json          # Credenciales de la cuenta de servicio de Google
├── README.md                 # Documentación del proyecto
├── requirements.txt          # Dependencias
│
├── src/                      # Código fuente
│   ├── __init__.py
│   ├── init.py               # Orquesta el scraping (función main)
│   │
│   ├── desktop/              # Interfaz de escritorio (Flet)
│   │   ├── __init__.py
│   │   └── app.py            # GUI: inputs, tabla, visor de imagen y OCR
│   │
│   ├── api/                  # Integraciones externas
│   │   ├── __init__.py
│   │   ├── facebook.py       # Wrapper de la Facebook Graph API
│   │   └── google_ai.py      # OCR de tickets con Vertex AI (Gemini)
│   │
│   ├── storage/              # Almacenamiento de datos
│   │   ├── __init__.py
│   │   ├── file_storage.py   # Manejo de archivos JSON y CSV
│   │   └── sheets.py         # Integración con Google Sheets
│   │
│   └── monitor/              # Lógica principal de monitoreo
│       ├── __init__.py
│       └── facebook_monitor.py
│
└── facebook_monitor_logs/    # CSV/JSON generados por el scraping
```

## Instalación

1. Clona este repositorio.
2. Crea un entorno virtual (Python 3.12) e instala dependencias:
   ```powershell
   py -3.12 -m venv venv312
   .\venv312\Scripts\python.exe -m pip install -r requirements.txt
   ```
3. Crea un archivo `.env` con tu configuración (ver más abajo).
4. Coloca las credenciales de la cuenta de servicio de Google como `credentials.json`.
5. Para el OCR, autentica Google Cloud en la máquina (Application Default
   Credentials), por ejemplo con `gcloud auth application-default login` o
   definiendo `GOOGLE_APPLICATION_CREDENTIALS`.

## Uso

Ejecuta la aplicación de escritorio:

```powershell
.\venv312\Scripts\python.exe app.py
```

En la ventana:

1. Ingresa el **Post ID**, el **nombre de la hoja** de Google Sheets y el
   **nombre de la pestaña**.
2. Pulsa **Iniciar scraping**. El proceso corre en segundo plano y, al terminar,
   los comentarios con adjunto se cargan en la tabla.
3. Selecciona un comentario para ver la imagen adjunta y pulsa **Extraer OCR del
   adjunto** para obtener los datos estructurados del ticket.

## Empaquetar como ejecutable (.exe)

```powershell
flet build windows
```

Recuerda distribuir `credentials.json` y `.env` junto al ejecutable.

## Configuración

Variables de entorno requeridas:

- `PAGE_ID`: ID de la página de Facebook
- `LONG_LIVE_TOKEN`: token de acceso de larga duración de la Graph API
- `GRAPH_API_TOKEN`: token de acceso de la Graph API

Configuración opcional:

- `API_VERSION`: versión de la Graph API (por defecto: `v22.0`)
- `INTERVAL`: intervalo de chequeo en segundos (por defecto: 60)
- `BATCH_SIZE`: máximo de comentarios a subir por lote (por defecto: 7)
- `UPLOAD_INTERVAL`: tiempo máximo entre subidas en segundos (por defecto: 300)
- `LOG_DIR`: directorio para logs y datos (por defecto: `facebook_monitor_logs`)
- `GOOGLE_SHEETS_CREDS_FILE`: ruta al archivo de credenciales (por defecto: `credentials.json`)
- `ADMIN_EMAIL`: correo con el que compartir la hoja creada (opcional)
- `GCP_PROJECT`: proyecto de Google Cloud para el OCR (por defecto: `innovacion-futuro`)
- `GCP_LOCATION`: región de Vertex AI (por defecto: `us-central1`)

## Características

- Interfaz de escritorio, sin necesidad de servidor web
- Scrapea comentarios de publicaciones de Facebook por páginas (streaming)
- Detecta cambios en el contenido de la publicación
- Guarda los datos localmente en formatos JSON y CSV
- Sincroniza los comentarios a Google Sheets
- Extrae datos de tickets adjuntos mediante OCR (Vertex AI / Gemini)
- Reintentos con backoff exponencial ante errores de la API
- Soporte de paginación para hilos de comentarios grandes
