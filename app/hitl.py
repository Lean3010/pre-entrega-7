from pydantic import BaseModel, Field

class ApprovalRequest(BaseModel):
    approved: bool = Field(..., description="True para autorizar la tarea crítica, False para abortar")
    reviewer_comment: str = Field(default="Aprobado por supervisor humano", description="Motivo o comentario")

CRITICAL_KEYWORDS = [
    "produccion", "producción", "borrar", "eliminar", "drop", 
    "transferir", "pago", "masivo", "deploy", "critico", "crítico"
]

def check_if_critical(task_text: str) -> bool:
    """Detecta si el prompt solicita una operación crítica de alto costo o riesgo."""
    text_lower = task_text.lower()
    return any(keyword in text_lower for keyword in CRITICAL_KEYWORDS)