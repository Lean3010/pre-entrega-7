import os
from dotenv import load_dotenv
from langsmith import traceable

load_dotenv()

def init_observability() -> None:
    """Verifica y activa la capa de instrumentación con LangSmith."""
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGCHAIN_PROJECT", "pre-entrega-7-multiagente")
    
    if not os.getenv("LANGCHAIN_API_KEY"):
        print("⚠️ [WARN] LANGCHAIN_API_KEY no detectada. Las trazas no se enviarán.")
    else:
        project = os.getenv("LANGCHAIN_PROJECT")
        print(f"✅ Observabilidad activa -> Proyecto LangSmith: '{project}'")

__all__ = ["init_observability", "traceable"]