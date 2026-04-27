"""Shared LLM factory + Langfuse callback provider."""

import os
from dotenv import load_dotenv

load_dotenv()


def _build_llm():
    from langchain_huggingface import HuggingFaceEndpoint, ChatHuggingFace
    endpoint = HuggingFaceEndpoint(
        repo_id=os.getenv("HF_MODEL_ID", "Qwen/Qwen2.5-72B-Instruct"),
        task="text-generation",
        huggingfacehub_api_token=os.getenv("HF_TOKEN"),
        temperature=0.01,
        max_new_tokens=1024,
    )
    return ChatHuggingFace(llm=endpoint)


def get_langfuse_handler():
    try:
        from langfuse.callback import CallbackHandler
        return CallbackHandler(
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            host=os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"),
        )
    except Exception:
        return None


llm = _build_llm()
