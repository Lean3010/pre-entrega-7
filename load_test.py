import asyncio
import httpx

API_URL = "http://localhost:8000"

TASKS = [
    "Explicar ventajas de FastAPI asíncrono frente a WSGI tradicional.",
    "Diseñar esquema de caché distribuido con Redis para sesiones de usuario.",
    "CRITICO: Borrar registros antiguos y desplegar migración en produccion.",
    "Comparar patrones de orquestación multi-agente Supervisor vs Swarm.",
    "Optimizar consumo de tokens en pipelines con Llama 3.3."
]

async def submit_and_track(client: httpx.AsyncClient, idx: int, task_text: str):
    resp = await client.post(f"{API_URL}/tasks", json={"task": task_text})
    job_id = resp.json()["job_id"]
    print(f"[Tarea {idx}] Encolada -> job_id={job_id}")

    while True:
        await asyncio.sleep(1.5)
        status_resp = await client.get(f"{API_URL}/tasks/{job_id}")
        data = status_resp.json()
        st = data["status"]
        print(f"[Tarea {idx}] Estado actual: {st}")

        if st == "WAITING_APPROVAL":
            print(f"⚠️ [Tarea {idx}] Pausada por HITL. Enviando aprobación humana...")
            await client.post(
                f"{API_URL}/tasks/{job_id}/approve",
                json={"approved": True, "reviewer_comment": "Autorizado en prueba de carga"}
            )
        elif st in ("DONE", "FAILED"):
            print(f"✅ [Tarea {idx}] Finalizada con estado: {st}")
            return data

async def main():
    async with httpx.AsyncClient(timeout=30.0) as client:
        print("🚀 Lanzando 5 peticiones concurrentes contra la API...")
        await asyncio.gather(*(submit_and_track(client, i + 1, t) for i, t in enumerate(TASKS)))
        print("🎯 Corrida finalizada. Revisá LangSmith para tomar las capturas.")

if __name__ == "__main__":
    asyncio.run(main())