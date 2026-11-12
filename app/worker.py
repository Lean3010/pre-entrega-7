import json
import traceback
from datetime import datetime, timezone
import redis.asyncio as aioredis
from langchain_core.messages import HumanMessage
from app.observability import traceable

JOB_PREFIX = "job:"

async def set_job_state(redis_client: aioredis.Redis, job_id: str, **updates) -> dict:
    """Actualiza de forma atómica el estado del trabajo en Redis."""
    key = f"{JOB_PREFIX}{job_id}"
    raw = await redis_client.get(key)
    data = json.loads(raw) if raw else {"job_id": job_id}
    data.update(updates)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    await redis_client.set(key, json.dumps(data), ex=86400) # TTL 24h
    return data

async def get_job_state(redis_client: aioredis.Redis, job_id: str) -> dict | None:
    raw = await redis_client.get(f"{JOB_PREFIX}{job_id}")
    return json.loads(raw) if raw else None

@traceable(name="Worker_Execute_Job", run_type="chain")
async def run_agent_job(job_id: str, task: str, graph, redis_client: aioredis.Redis) -> None:
    """Ejecuta el grafo en background y actualiza Redis ante pausas HITL o errores."""
    config = {"configurable": {"thread_id": job_id}}
    try:
        await set_job_state(redis_client, job_id, status="RUNNING")

        # Simulamos fallo controlado si el prompt pide probar manejo de errores
        if "forzar_error" in task.lower():
            raise RuntimeError("Fallo simulado para verificar transición a estado FAILED en Redis.")

        initial_state = {
            "messages": [HumanMessage(content=task)],
            "task": task,
            "research_notes": "",
            "is_critical": False,
            "approved": None,
            "final_output": ""
        }

        await graph.ainvoke(initial_state, config=config)

        # Inspeccionamos el checkpoint para saber si quedó pausado en el nodo HITL
        snapshot = await graph.aget_state(config)
        if snapshot.next and "critical_action" in snapshot.next:
            await set_job_state(
                redis_client,
                job_id,
                status="WAITING_APPROVAL",
                pending_node="critical_action",
                research_preview=snapshot.values.get("research_notes", ""),
                message="Tarea crítica pausada. Requiere POST /tasks/{id}/approve para continuar."
            )
        else:
            await set_job_state(
                redis_client,
                job_id,
                status="DONE",
                result=snapshot.values.get("final_output", "")
            )

    except Exception as exc:
        await set_job_state(
            redis_client,
            job_id,
            status="FAILED",
            error=str(exc),
            traceback=traceback.format_exc()
        )

@traceable(name="Worker_Resume_After_Approval", run_type="chain")
async def resume_agent_job(
    job_id: str, approved: bool, comment: str, graph, redis_client: aioredis.Redis
) -> None:
    """Reanuda el grafo desde el checkpoint de Redis tras recibir el input humano."""
    config = {"configurable": {"thread_id": job_id}}
    try:
        await set_job_state(
            redis_client, job_id, status="RUNNING", reviewer_comment=comment
        )

        # Inyectamos la decisión humana en el estado persistido en Redis
        await graph.aupdate_state(config, {"approved": approved})

        # Reanudamos pasando None como input para continuar desde el breakpoint
        await graph.ainvoke(None, config=config)

        snapshot = await graph.aget_state(config)
        await set_job_state(
            redis_client,
            job_id,
            status="DONE",
            result=snapshot.values.get("final_output", "")
        )
    except Exception as exc:
        await set_job_state(
            redis_client,
            job_id,
            status="FAILED",
            error=str(exc),
            traceback=traceback.format_exc()
        )