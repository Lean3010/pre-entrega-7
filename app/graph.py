import os
from typing import Annotated, TypedDict, Literal
from operator import add
from dotenv import load_dotenv

from langchain_groq import ChatGroq
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.redis.aio import AsyncRedisSaver

from app.observability import traceable
from app.hitl import check_if_critical

load_dotenv()

# 1. Definición de Estado del Sistema Multi-Agente
class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add]
    task: str
    research_notes: str
    is_critical: bool
    approved: bool | None
    final_output: str

# LLM Gratuito via Groq
def get_llm():
    return ChatGroq(
        model="openai/gpt-oss-120b",
        temperature=0.2,
        api_key=os.getenv("GROQ_API_KEY")
    )

# 2. Nodos del Grafo decorados para Observabilidad
@traceable(name="Supervisor_Triage_Agent", run_type="chain")
async def supervisor_node(state: AgentState) -> dict:
    """Evalúa la tarea entrante y determina si involucra riesgo crítico (HITL)."""
    task = state["task"]
    is_crit = check_if_critical(task)
    return {
        "is_critical": is_crit,
        "messages": [AIMessage(content=f"[Supervisor] Tarea analizada. Crítica={is_crit}")]
    }

@traceable(name="Researcher_Agent", run_type="llm")
async def researcher_node(state: AgentState) -> dict:
    """Agente 1: Investiga y prepara el plan técnico."""
    llm = get_llm()
    prompt = [
        SystemMessage(content="Eres un Agente Investigador Senior. Analiza la solicitud en 3 puntos breves y técnicos."),
        HumanMessage(content=state["task"])
    ]
    response = await llm.ainvoke(prompt)
    return {
        "research_notes": response.content,
        "messages": [response]
    }

@traceable(name="Critical_Action_Node", run_type="tool")
async def critical_action_node(state: AgentState) -> dict:
    """Agente 2 (HITL): Ejecuta u omite la operación crítica tras la pausa humana."""
    if state.get("approved") is False:
        return {
            "final_output": "❌ Operación CANCELADA por el supervisor humano en la revisión HITL.",
            "messages": [AIMessage(content="Ejecución crítica abortada por el usuario.")]
        }

    llm = get_llm()
    prompt = [
        SystemMessage(content="Eres un Agente Ejecutor de Producción. La operación crítica fue APROBADA por un humano. Genera el reporte de ejecución exitoso basado en las notas."),
        HumanMessage(content=f"Tarea: {state['task']}\nNotas previas: {state['research_notes']}")
    ]
    response = await llm.ainvoke(prompt)
    return {
        "final_output": f"✅ [EJECUCIÓN CRÍTICA APROBADA]\n{response.content}",
        "messages": [response]
    }

@traceable(name="Standard_Writer_Agent", run_type="llm")
async def writer_node(state: AgentState) -> dict:
    """Agente 3: Redacta la respuesta final para tareas estándar (sin pausa HITL)."""
    llm = get_llm()
    prompt = [
        SystemMessage(content="Eres un Agente Redactor. Sintetiza una respuesta final clara y directa basada en la investigación."),
        HumanMessage(content=f"Tarea: {state['task']}\nInvestigación: {state['research_notes']}")
    ]
    response = await llm.ainvoke(prompt)
    return {
        "final_output": response.content,
        "messages": [response]
    }

def route_after_research(state: AgentState) -> Literal["critical_action", "writer"]:
    """Arista condicional: desvía al nodo con interrupción si la tarea es crítica."""
    if state.get("is_critical"):
        return "critical_action"
    return "writer"

# 3. Construcción del Grafo con Checkpointer en Redis
def build_graph(checkpointer: AsyncRedisSaver):
    builder = StateGraph(AgentState)
    
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("researcher", researcher_node)
    builder.add_node("critical_action", critical_action_node)
    builder.add_node("writer", writer_node)

    builder.add_edge(START, "supervisor")
    builder.add_edge("supervisor", "researcher")
    builder.add_conditional_edges("researcher", route_after_research)
    builder.add_edge("critical_action", END)
    builder.add_edge("writer", END)

    # HITL: El grafo se congela automáticamente ANTES de ejecutar 'critical_action'
    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["critical_action"]
    )