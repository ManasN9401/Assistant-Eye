"""
AI Engine — abstraction over OpenAI, Anthropic, and Ollama.
Phase 1: text-only. Voice will be added in Phase 2.
"""
from __future__ import annotations
import json
from typing import Generator


class AIEngine:
    def __init__(self, settings):
        self.settings = settings
        self._client = None

    def _get_client(self):
        provider = self.settings.ai_provider
        if provider == "openai":
            import openai
            return openai.OpenAI(api_key=self.settings.get("api_key"))
        elif provider == "anthropic":
            import anthropic
            return anthropic.Anthropic(api_key=self.settings.get("anthropic_api_key"))
        elif provider == "ollama":
            import openai
            return openai.OpenAI(
                base_url="http://localhost:11434/v1",
                api_key="ollama",
            )
        raise ValueError(f"Unknown provider: {provider}")

    def chat(self, message: str, system_prompt: str = "") -> str:
        """Send a message and return the full response as a string."""
        provider = self.settings.ai_provider
        model = self.settings.ai_model
        client = self._get_client()

        if not system_prompt:
            name = self.settings.assistant_name
            system_prompt = (
                f"You are {name}, a helpful assistant integrated into the user's browser. "
                "You help users navigate websites, find information, and perform actions. "
                "Be concise and direct. If asked to perform a website action, respond with "
                "a JSON block: {\"action\": \"<function_name>\", \"params\": {...}}."
            )

        if provider == "anthropic":
            response = client.messages.create(
                model=model,
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": message}],
            )
            return response.content[0].text

        # OpenAI-compatible (openai + ollama)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
            max_tokens=1024,
        )
        return response.choices[0].message.content

    def chat_stream(self, message: str, system_prompt: str = "") -> Generator[str, None, None]:
        """Stream a response token by token."""
        provider = self.settings.ai_provider
        model = self.settings.ai_model
        client = self._get_client()

        if not system_prompt:
            name = self.settings.assistant_name
            system_prompt = (
                f"You are {name}, a helpful assistant. Be concise and direct."
            )

        if provider == "anthropic":
            with client.messages.stream(
                model=model,
                max_tokens=1024,
                system=system_prompt,
                messages=[{"role": "user", "content": message}],
            ) as stream:
                for text in stream.text_stream:
                    yield text
            return

        stream = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message},
            ],
            max_tokens=1024,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
