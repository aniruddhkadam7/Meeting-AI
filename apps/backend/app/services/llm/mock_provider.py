from __future__ import annotations

import json
from typing import AsyncIterator, List

from .base import LLMMessage, LLMProvider


class MockLLMProvider(LLMProvider):
    """Deterministic, no network call, no API key. Returns a JSON string
    matching whatever schema the last user message's prompt describes closely
    enough for the analysis pipeline's own Pydantic validation to accept it —
    concretely, it inspects the prompt for a couple of known markers
    (PromptBuilder always includes "question_id" for per-question prompts, or
    "overall_score" for the aggregate prompt) so both stages of the two-stage
    pipeline get a structurally valid mock response instead of one hard-coded
    shape that only fits one stage.

    Every score is 0 and every list is empty — this must never be mistaken
    for a real analysis, hence the explicit note field.
    """

    async def generate(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.2,
        max_tokens: int = 1500,
    ) -> str:
        prompt_text = "\n".join(m.content for m in messages)
        if '"question_id"' in prompt_text or "question_id" in prompt_text:
            payload = {
                "assessment": "Mock analysis — no LLM provider is configured. Set LLM_PROVIDER=openai and OPENAI_API_KEY to enable real analysis.",
                "score": 0,
                "strengths": [],
                "issues": [],
                "improved_answer": "",
            }
        else:
            payload = {
                "overall_score": 0,
                "technical_score": 0,
                "communication_score": 0,
                "practical_experience_score": 0,
                "confidence_score": 0,
                "summary": "Mock analysis — no LLM provider is configured.",
                "strengths": [],
                "weaknesses": [],
                "recommendations": [],
            }
        return json.dumps(payload)

    async def stream(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.2,
        max_tokens: int = 1500,
    ) -> AsyncIterator[str]:
        text = await self.generate(messages, temperature, max_tokens)
        # Yield in a couple of chunks so streaming consumers exercise their
        # incremental-accumulation path even against the mock provider.
        midpoint = len(text) // 2
        if midpoint:
            yield text[:midpoint]
            yield text[midpoint:]
        else:
            yield text
