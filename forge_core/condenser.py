from typing import List, Dict, Any
from forge_core.llm import LLMBackend
from forge_core.events import Event

class LLMSummarizingCondenser:
    """Condenses evicted conversation events into a recursive summary."""
    def __init__(self, llm: LLMBackend):
        self.llm = llm
        
    def condense(self, events: List[Event], previous_summary: str = "") -> str:
        # Prompt the local model to summarize
        prompt = "Summarize the following conversation events concisely."
        if previous_summary:
            prompt += f"\nPrevious summary context: {previous_summary}"
            
        events_text = "\n".join([f"{e.source}: {e.model_dump()}" for e in events])
        messages = [
            {"role": "system", "content": "You are a helpful summarization assistant."},
            {"role": "user", "content": f"{prompt}\n\nEvents:\n{events_text}"}
        ]
        
        response = self.llm.generate(messages)
        return response['choices'][0]['message']['content']
