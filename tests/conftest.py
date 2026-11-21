import sys
from unittest.mock import MagicMock

# Register mock modules for external neural runtimes to support weightless test runs
sys.modules["llama_cpp"] = MagicMock()
sys.modules["faster_whisper"] = MagicMock()
