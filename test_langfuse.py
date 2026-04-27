"""
Quick CLI test — kirim satu pertanyaan ke graph dan lihat trace di Langfuse.

Jalankan:
    python test_langfuse.py
    python test_langfuse.py "Berapa hari cuti tahunan?"
    python test_langfuse.py "What is the capital of France?"
"""

import sys
from dotenv import load_dotenv
load_dotenv()

from langchain_core.messages import HumanMessage
from src.agents.graph import graph, get_langfuse_handler

question = sys.argv[1] if len(sys.argv) > 1 else "How does API Gateway authentication work?"

print(f"\nPertanyaan : {question}")
print("Memproses  ...")

handler = get_langfuse_handler()
config = {"callbacks": [handler]} if handler else {}

result = graph.invoke(
    {
        "messages": [HumanMessage(content=question)],
        "current_agent": "",
        "routing_decision": "",
    },
    config=config,
)

print(f"Agent      : {result['current_agent']}")
print(f"\nJawaban:\n{result['messages'][-1].content}")

if handler:
    handler.langfuse.flush()
    print("\nTrace dikirim ke Langfuse — buka https://cloud.langfuse.com untuk melihatnya.")
