from abc import abstractmethod
from typing import Any, Dict, Iterator, List, Optional, Union
from app.runtime.providers.base import BaseProvider, LLMResult


class LLMProvider(BaseProvider):
    """Abstract interface for Large Language Model providers."""

    @abstractmethod
    def generate(
        self,
        system_instruction: str,
        messages: List[Dict[str, Any]],
        available_tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        model: Optional[str] = None
    ) -> LLMResult:
        """Generate conversational response or tool call given message history and active tools."""
        pass

    async def generate_async(
        self,
        system_instruction: str,
        messages: List[Dict[str, Any]],
        available_tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        model: Optional[str] = None
    ) -> LLMResult:
        """Asynchronously generate response with fallback to synchronous generate."""
        return self.generate(
            system_instruction=system_instruction,
            messages=messages,
            available_tools=available_tools,
            temperature=temperature,
            model=model
        )

    def generate_stream(
        self,
        system_instruction: str,
        messages: List[Dict[str, Any]],
        available_tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        model: Optional[str] = None
    ) -> Iterator[Union[str, LLMResult]]:
        """
        Streams a response: yields text deltas (str) as they are produced, then the
        complete LLMResult (full text, tool calls, usage) as the final item.
        Default implementation wraps generate() for providers without native streaming.
        """
        result = self.generate(
            system_instruction=system_instruction,
            messages=messages,
            available_tools=available_tools,
            temperature=temperature,
            model=model
        )
        if result.text:
            yield result.text
        yield result
