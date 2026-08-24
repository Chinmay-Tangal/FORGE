from typing import Callable, Dict, Any, List
from pydantic import BaseModel
import inspect

class Tool(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]
    func: Callable

class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, Tool] = {}
        
    def register(self, name: str, description: str, parameters: Dict[str, Any]):
        def decorator(func: Callable):
            self.tools[name] = Tool(
                name=name,
                description=description,
                parameters=parameters,
                func=func
            )
            return func
        return decorator
        
    def get_tool(self, name: str) -> Tool:
        if name not in self.tools:
            raise ValueError(f"Tool {name} not found.")
        return self.tools[name]
        
    def execute(self, name: str, kwargs: Dict[str, Any]) -> Any:
        tool = self.get_tool(name)
        return tool.func(**kwargs)
        
    def to_openai_schema(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters
                }
            } for tool in self.tools.values()
        ]
