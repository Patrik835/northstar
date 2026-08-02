from typing import Any

from openai import AsyncOpenAI


class OpenAIInvestmentAssistant:
    disclaimer = "For informational and educational purposes only—not financial advice."

    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def recommendation(self, portfolio_context: dict[str, Any]) -> str:
        raise NotImplementedError

    async def chat(self, portfolio_context: dict[str, Any], message: str) -> str:
        raise NotImplementedError
