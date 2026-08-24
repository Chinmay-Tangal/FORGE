"""
forge/llm/router.py — RouterLLM: local-first with optional frontier escalation.

By default all requests go to the local model. Pass ``require_frontier=True``
(or set it via the Agent) to escalate a turn to the frontier model — useful
when the local model is stuck or a task explicitly requires a larger model.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Generator, List, Optional

from forge.llm.backend import LLMBackend

logger = logging.getLogger(__name__)


class RouterLLM:
    """
    Routes generation requests between a local and an optional frontier LLM.

    Parameters
    ----------
    local_llm:
        Always-available local model (llama-server / vLLM).
    frontier_llm:
        Optional hosted frontier model. When ``None``, frontier requests
        fall back silently to the local model.
    """

    def __init__(
        self,
        local_llm: LLMBackend,
        frontier_llm: Optional[LLMBackend] = None,
    ) -> None:
        self.local_llm = local_llm
        self.frontier_llm = frontier_llm

    # Internal
    def _pick(self, require_frontier: bool) -> LLMBackend:
        if require_frontier and self.frontier_llm is not None:
            logger.debug("Routing to frontier model.")
            return self.frontier_llm
        return self.local_llm

    # Public API (mirrors LLMBackend)
    def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        require_frontier: bool = False,
    ) -> Dict[str, Any]:
        return self._pick(require_frontier).generate(messages, tools)

    def stream_generate(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        require_frontier: bool = False,
    ) -> Generator[str, None, None]:
        yield from self._pick(require_frontier).stream_generate(messages, tools)

    def count_tokens(self, text: str) -> int:
        return self.local_llm.count_tokens(text)

    def check_health(self) -> bool:
        return self.local_llm.check_health()
