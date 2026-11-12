# Pre-entrega 7: API Multi-Agente en Producción y Monitoreo Activo

API REST asíncrona desarrollada con **FastAPI**, **LangGraph**, **Redis** (`AsyncRedisSaver`) y observabilidad activa en **LangSmith**, utilizando el modelo **`openai/gpt-oss-120b`** a través de la API de **Groq**.

---

## 🏗️ Arquitectura y Capacidades Implementadas

1. **Endpoints Asíncronos No Bloqueantes (`app/main.py` y `app/worker.py`):**
   - `POST /tasks`: Recibe la tarea, inicializa el estado `PENDING` en Redis, despacha la ejecución en segundo plano mediante `asyncio.create_task` y devuelve inmediatamente `202 Accepted` con el `job_id`.
   - `GET /tasks/{job_id}`: Consulta de forma asíncrona el estado actual (`PENDING`, `RUNNING`, `WAITING_APPROVAL`, `DONE` o `FAILED`) sin bloquear el Event Loop.
2. **Persistencia y Checkpointing en Redis (`app/graph.py` y `app/worker.py`):**
   - Gestión de estado del trabajo (`job:{id}`) con captura automática de excepciones y transición a `FAILED` ante errores en background.
   - Memoria y estado de ejecución del grafo persistidos con `AsyncRedisSaver` de `langgraph-checkpoint-redis`.
3. **Flujo Human-in-the-Loop - HITL (`app/hitl.py` y `app/graph.py`):**
   - El nodo `supervisor` evalúa si la tarea contiene operaciones críticas (ej. despliegues en producción, borrado de datos).
   - El grafo compilado utiliza `interrupt_before=["critical_action"]` para congelar la ejecución antes del nodo crítico, dejando el trabajo en estado `WAITING_APPROVAL` hasta recibir autorización externa vía `POST /tasks/{job_id}/approve`.
4. **Capa de Observabilidad Activa (`app/observability.py`):**
   - Instrumentación mediante decoradores `@traceable` de **LangSmith** en cada nodo del sistema multi-agente y workers de ejecución, registrando trazas anidadas, consumo de tokens, costo por ejecución y latencia **p95**.

---

## 📂 Estructura del Proyecto

```text
mi-api-agente/
├── app/
│   ├── main.py            # FastAPI: POST /tasks, GET /tasks/{id}, POST /tasks/{id}/approve
│   ├── graph.py           # Orquestador multi-agente + AsyncRedisSaver + interrupt_before
│   ├── worker.py          # Ejecución en segundo plano y máquina de estados en Redis
│   ├── observability.py   # Inicialización de trazas con LangSmith (@traceable)
│   └── hitl.py            # Detección de tareas críticas y esquema de aprobación humana
├── screenshots/           # Evidencia del dashboard de LangSmith (trazas, costos y latencia p95)
├── docker-compose.yml     # Configuración de Redis Stack local (opcional si se usa Redis Cloud)
├── load_test.py           # Script asíncrono para lanzar las 5 peticiones concurrentes + HITL
├── requirements.txt       # Dependencias del proyecto (Python 3.12+)
├── .env.example           # Plantilla de variables de entorno
└── README.md              # Instructivo de instalación y ejecución
```

---

## ⚙️ Requisitos e Instalación Paso a Paso

### 1. Clonar el repositorio y crear el entorno virtual (Python 3.12+)

```powershell
git clone <URL_DE_TU_REPOSITORIO>
cd mi-api-agente

# Crear y activar entorno virtual en Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1


# Instalar dependencias
pip install -r requirements.txt
```

### 2. Configurar las variables de entorno (`.env`)

Copia el archivo de ejemplo y completa tus claves:

```powershell
cp .env.example .env
```

Edita el archivo `.env` con tus credenciales:

```env
# Opción A: Redis Cloud (Recomendado en Windows sin Docker) o Redis Stack local
REDIS_URL=redis://default:TU_PASSWORD@TU_ENDPOINT_REDIS_CLOUD:PUERTO

# Clave gratuita de Groq ([https://console.groq.com](https://console.groq.com))
GROQ_API_KEY=gsk_tu_clave_de_groq_aqui

# Configuración de Observabilidad en LangSmith ([https://smith.langchain.com](https://smith.langchain.com))
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=[https://api.smith.langchain.com](https://api.smith.langchain.com)
LANGCHAIN_API_KEY=lsv2_pt_tu_clave_de_langsmith_aqui
LANGCHAIN_PROJECT=pre-entrega-7-multiagente
```

### 3. Inicializar Redis

- **Opción A — Redis Cloud (Sin Docker):** Asegúrate de colocar la URL de tu instancia gratuita de Redis Cloud en `REDIS_URL` dentro de `.env`.
- **Opción B — Contenedor local con Docker Compose:** Si prefieres correr Redis localmente con los módulos `RedisJSON` y `RediSearch`:
  ```powershell
  docker compose up -d
  ```
  Y en tu `.env` utiliza `REDIS_URL=redis://localhost:6379`.

---

## 🚀 Cómo Ejecutar el Programa y las Pruebas

### Paso 1: Levantar el servidor FastAPI (Terminal 1)

Con el entorno virtual activo, inicia Uvicorn:

```powershell
uvicorn app.main:app --reload --port 8000
```

- La API quedará disponible en: `http://localhost:8000`
- Documentación interactiva (Swagger UI): `http://localhost:8000/docs`

### Paso 2: Lanzar las 5 peticiones concurrentes y el flujo HITL (Terminal 2)

Abre una **segunda terminal**, activa el entorno virtual y ejecuta el script de prueba de carga:

```powershell
.\.venv\Scripts\Activate.ps1
python load_test.py
```

**Qué hace este script automáticamente:**
1. Envía **5 tareas concurrentes** con `asyncio.gather` contra `POST /tasks` y recibe los 5 `job_id` de forma inmediata (`202 Accepted`).
2. Realiza *polling* no bloqueante sobre `GET /tasks/{job_id}`.
3. Las tareas estándar (1, 2, 4 y 5) avanzan por los agentes y finalizan en estado `DONE`.
4. La **Tarea 3** (marcada como crítica) es interceptada por el breakpoint de LangGraph y queda en estado `WAITING_APPROVAL`. El script detecta la pausa, envía la aprobación humana a `POST /tasks/{job_id}/approve` y verifica que reanude hasta `DONE`.

### Paso 3: Probar el manejo de excepciones (`FAILED`)

Para comprobar que un fallo en segundo plano no bloquea al cliente y persiste el estado `FAILED` en Redis, ejecuta en PowerShell o desde `/docs`:

```powershell
python -c "import httpx, time; r = httpx.post('http://localhost:8000/tasks', json={'task': 'forzar_error'}).json(); time.sleep(1); print(httpx.get(f'http://localhost:8000/tasks/{r[\"job_id\"]}').json())"
```

---

## 📊 Evidencia de Observabilidad (`/screenshots`)

En el directorio `/screenshots` se encuentran las capturas tomadas desde el dashboard de **LangSmith** (`pre-entrega-7-multiagente`) tras ejecutar las 5 peticiones concurrentes:
- Registro de trazas activas e historial de ejecuciones concurrentes con cálculo de **costo por ejecución** a partir de los tokens de entrada y salida.
- Desglose de nodos del grafo (`Supervisor_Triage_Agent`, `Researcher_Agent`, `Standard_Writer_Agent`, `Critical_Action_Node`).
- Métricas de rendimiento y **latencia p95** de la corrida.