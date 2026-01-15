"""LLM client using LiteLLM for model abstraction."""

from litellm import completion, acompletion
from typing import List, Dict, Any, Optional
from config import settings


class LLMClient:
    """Wrapper around LiteLLM for consistent LLM access."""

    def __init__(self, model: Optional[str] = None):
        self.model = model or settings.llm.model

    def _litellm_kwargs(self) -> Dict[str, Any]:
        extra: Dict[str, Any] = {}
        if settings.llm.base_url:
            extra["api_base"] = settings.llm.base_url
        if settings.anthropic_api_key and self._uses_anthropic():
            extra["api_key"] = settings.anthropic_api_key
        return extra

    def _uses_anthropic(self) -> bool:
        model = (self.model or "").lower()
        return "claude" in model or "anthropic" in model
    
    async def complete(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4000,
        **kwargs
    ) -> str:
        """Async completion request.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature
            max_tokens: Maximum response tokens
            **kwargs: Additional LiteLLM parameters
            
        Returns:
            Response text
        """
        response = await acompletion(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=settings.llm.timeout,
            **self._litellm_kwargs(),
            **kwargs
        )
        return response.choices[0].message.content
    
    def complete_sync(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4000,
        **kwargs
    ) -> str:
        """Synchronous completion request.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature
            max_tokens: Maximum response tokens
            **kwargs: Additional LiteLLM parameters
            
        Returns:
            Response text
        """
        response = completion(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=settings.llm.timeout,
            **self._litellm_kwargs(),
            **kwargs
        )
        return response.choices[0].message.content


# Global instance
llm_client = LLMClient()
