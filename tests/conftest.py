import os
import sys
from unittest.mock import MagicMock

os.environ.setdefault("HF_TOKEN", "test-token")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("QDRANT_API_KEY", "test-key")
os.environ.setdefault("QDRANT_COLLECTION_TECHNICAL", "kb_technical")
os.environ.setdefault("QDRANT_COLLECTION_HR", "kb_hr")

# Stub packages that connect to external services on init — must happen
# before src.agents.graph or src.tools.rag_tool are imported.
_fake_llm = MagicMock()
_fake_llm.bind_tools.return_value = MagicMock()
_fake_llm.with_structured_output.return_value = MagicMock()

_hf_module = MagicMock()
_hf_module.ChatHuggingFace.return_value = _fake_llm

sys.modules["langchain_huggingface"] = _hf_module
sys.modules["qdrant_client"] = MagicMock()
sys.modules["langchain_qdrant"] = MagicMock()
sys.modules["huggingface_hub"] = MagicMock()
