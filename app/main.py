import os
import uuid
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
import redis.asyncio as aioredis
from langgraph.checkpoint.redis.aio import AsyncRedisSaver

from app.observability import init_observability
from app.graph import build_graph
from app.worker import set_job_state, get_job_state, run_agent_job, resume_agent_job
from app.hitl import ApprovalRequest

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

class TaskCreateRequest(BaseModel):
    task: str = Field(..., min_length=3, examples=["Analizar arquitectura de microservicios en Python"])

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_observability()
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    
    # Inicializamos el checkpointer asíncrono de LangGraph en Redis
    async with AsyncRedisSaver.from_conn_string(REDIS_URL) as checkpointer:
        await checkpointer.asetup()
        app.state.redis = redis_client
        app.state.graph = build_graph(checkpointer)
        app.state.background_tasks = set()
        yield

    await redis_client.aclose()

app = FastAPI(
    title="Pre-entrega 7: API Multi-Agente en Producción",
    version="1.0.0",
    lifespan=lifespan
)

@app.post("/tasks", status_code=status.HTTP_202_ACCEPTED)
async def enqueue_task(payload: TaskCreateRequest):
    """Recibe una tarea, registra estado PENDING en Redis y lanza el worker sin bloquear."""
    job_id = str(uuid.uuid4())
    redis_client = app.state.redis
    graph = app.state.graph

    await set_job_state(
        redis_client,
        job_id,
        status="PENDING",
        task=payload.task,
        result=None,
        error=None
    )

    # Disparo no bloqueante en el Event Loop
    bg_task = asyncio.create_task(run_agent_job(job_id, payload.task, graph, redis_client))
    app.state.background_tasks.add(bg_task)
    bg_task.add_done_callback(app.state.background_tasks.discard)

    return {
        "job_id": job_id,
        "status": "PENDING",
        "Check_status_url": f"/tasks/{job_id}"
    }

@app.get("/tasks/{job_id}")
async def get_task_status(job_id: str):
    """Consulta el estado del trabajo directamente en Redis sin bloquear."""
    job = await get_job_state(app.state.redis, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job ID no encontrado en Redis")
    return job

@app.post("/tasks/{job_id}/approve")
async def approve_critical_task(job_id: str, body: ApprovalRequest):
    """Endpoint HITL: desbloquea un grafo pausado en 'WAITING_APPROVAL'."""
    redis_client = app.state.redis
    job = await get_job_state(redis_client, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job ID no encontrado")

    if job.get("status") != "WAITING_APPROVAL":
        raise HTTPException(
            status_code=400,
            detail=f"El job no está esperando aprobación (estado actual: {job.get('status')})"
        )

    bg_task = asyncio.create_task(
        resume_agent_job(job_id, body.approved, body.reviewer_comment, app.state.graph, redis_client)
    )
    app.state.background_tasks.add(bg_task)
    bg_task.add_done_callback(app.state.background_tasks.discard)

    return {
        "job_id": job_id,
        "status": "RESUMING",
        "approved": body.approved,
        "reviewer_comment": body.reviewer_comment
    }