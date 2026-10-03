"""
ai/brain.py — AI Brain: async Gemini (and fallback provider) interface.

Responsibilities:
  - Maintain conversation context (rolling window)
  - Build multimodal messages (text + image)
  - Stream responses to the EventBus
  - Support swappable providers (Gemini, OpenAI-compatible, Ollama)
"""

from __future__ import annotations

import asyncio
import base64
import threading
from pathlib import Path
from typing import Any

from loguru import logger

from core.config_manager import ConfigManager
from core.event_bus import EventBus, AI_RESPONSE_CHUNK, AI_RESPONSE_DONE, AI_THINKING, WINDOW_FOCUS_CHANGED


class ConversationContext:
    """Rolling window of chat messages for multi-turn context."""

    def __init__(self, max_turns: int = 10):
        self._max_turns = max_turns
        self._messages: list[dict] = []

    def add(self, role: str, content: str | list) -> None:
        self._messages.append({"role": role, "content": content})
        # Keep within window (each turn = 2 messages: user + assistant)
        if len(self._messages) > self._max_turns * 2:
            self._messages = self._messages[-(self._max_turns * 2):]

    def get_history(self) -> list[dict]:
        return list(self._messages)

    def clear(self) -> None:
        self._messages.clear()


class Brain:
    """
    The AI brain of Mr. ADN.
    All public methods are sync wrappers that spawn async tasks
    so they can be called from Qt threads without blocking.
    """

    def __init__(self, cfg: ConfigManager, event_bus: EventBus):
        self._cfg = cfg
        self._bus = event_bus
        self._provider = cfg.get("ai.provider", "gemini")
        self._model = cfg.get("ai.model", "gemini-3.5-flash-lite")
        self._system_prompt = cfg.get("ai.system_prompt", "You are a helpful assistant.")
        self._streaming = cfg.get("ai.streaming", True)
        self._store = cfg.get("ai.store_interactions", False)
        self._context_size = cfg.get("ai.context_window_size", 10)
        self._context = ConversationContext(max_turns=self._context_size)

        # Telemetry context injected externally
        self.active_window: str = ""
        self.visible_windows: list[str] = []

        self._bus.subscribe(WINDOW_FOCUS_CHANGED, self._on_window_changed)

        # Async event loop in its own thread
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="BrainAsyncLoop"
        )
        self._loop_thread.start()

        self._client = self._build_client()
        logger.info(f"Brain initialized | provider={self._provider} | model={self._model}")

    # ── Client factory ────────────────────────────────────────────────────

    def _build_client(self) -> Any:
        """Instantiate the appropriate AI client."""
        if self._provider == "gemini":
            try:
                from google import genai
                client = genai.Client()
                logger.debug("Gemini client created.")
                return client
            except Exception as exc:
                logger.error(f"Failed to create Gemini client: {exc}")
                raise
        elif self._provider in ("openai", "ollama"):
            try:
                from openai import AsyncOpenAI
                provider_cfg = self._cfg.get(f"ai.providers.{self._provider}", {})
                base_url = provider_cfg.get("base_url")
                api_key_env = provider_cfg.get("api_key_env")
                import os
                api_key = os.getenv(api_key_env, "ollama") if api_key_env else "ollama"
                client = AsyncOpenAI(base_url=base_url, api_key=api_key)
                logger.debug(f"OpenAI-compatible client created for {self._provider}.")
                return client
            except Exception as exc:
                logger.error(f"Failed to create {self._provider} client: {exc}")
                raise
        else:
            raise ValueError(f"Unknown AI provider: {self._provider}")

    # ── Public API (sync wrappers) ────────────────────────────────────────

    def ask(
        self,
        user_text: str,
        image_bytes: bytes | None = None,
        image_mime: str = "image/png",
        input_mode: str = "text",
    ) -> None:
        """
        Non-blocking: submit a query to the AI.
        Emits AI_RESPONSE_CHUNK events per token, then AI_RESPONSE_DONE.
        """
        self._bus.publish(AI_THINKING)
        asyncio.run_coroutine_threadsafe(
            self._ask_async(user_text, image_bytes, image_mime, input_mode),
            self._loop,
        )

    def clear_context(self) -> None:
        """Reset conversation history."""
        self._context.clear()
        logger.info("Conversation context cleared.")

    def _on_window_changed(self, window: Any, **kwargs) -> None:
        """Handle window focus change (local tracking only)."""
        if not window:
            return
        
        window_str = str(window)
        if "Mr. ADN" in window_str or "Task Switching" in window_str:
            return

        self.active_window = window_str

    # ── Async core ────────────────────────────────────────────────────────

    async def _ask_async(
        self,
        user_text: str,
        image_bytes: bytes | None,
        image_mime: str,
        input_mode: str,
    ) -> None:
        try:
            if self._provider == "gemini":
                await self._gemini_stream(user_text, image_bytes, image_mime)
            else:
                await self._openai_stream(user_text, image_bytes, image_mime)
        except Exception as exc:
            logger.exception(f"Brain._ask_async error: {exc}")
            self._bus.publish(AI_RESPONSE_DONE, text=f"[Error: {exc}]", error=True)

    async def _gemini_stream(
        self,
        user_text: str,
        image_bytes: bytes | None,
        image_mime: str,
    ) -> None:
        """Streaming via google-genai Interactions API."""
        from google import genai

        # Build multimodal input
        input_parts: list[Any] = []

        # Inject telemetry context into the first user message
        context_prefix = self._build_context_prefix()
        full_text = f"{context_prefix}\n\n{user_text}".strip() if context_prefix else user_text
        input_parts.append(full_text)

        if image_bytes:
            from google.genai import types as gtypes
            input_parts.append(
                gtypes.Part.from_bytes(data=image_bytes, mime_type=image_mime)
            )

        # Add to rolling context
        self._context.add("user", full_text)

        # Build history (exclude last user message already in input)
        history = self._context.get_history()[:-1]
        previous_id: str | None = None

        # NOTE: Interactions API is stateful server-side.
        # We pass previous_interaction_id for multi-turn if available.
        # For simplicity we rebuild context via system prompt each turn.

        full_response = ""

        for event in self._client.interactions.create(
            model=self._model,
            system_instruction=self._system_prompt,
            input=input_parts if len(input_parts) > 1 else input_parts[0],
            stream=True,
            store=self._store,
        ):
            if event.event_type == "step.delta":
                if event.delta.type == "text":
                    chunk = event.delta.text
                    full_response += chunk
                    self._bus.publish(AI_RESPONSE_CHUNK, chunk=chunk)
            elif event.event_type == "interaction.completed":
                pass  # Could log token usage here

        self._context.add("assistant", full_response)
        self._bus.publish(AI_RESPONSE_DONE, text=full_response, error=False)

    async def _openai_stream(
        self,
        user_text: str,
        image_bytes: bytes | None,
        image_mime: str,
    ) -> None:
        """Streaming via OpenAI-compatible API (also works for Ollama)."""
        messages = [{"role": "system", "content": self._system_prompt}]

        context_prefix = self._build_context_prefix()
        full_text = f"{context_prefix}\n\n{user_text}".strip() if context_prefix else user_text

        # Build user message with optional image
        if image_bytes:
            b64 = base64.b64encode(image_bytes).decode()
            user_content = [
                {"type": "text", "text": full_text},
                {"type": "image_url", "image_url": {"url": f"data:{image_mime};base64,{b64}"}},
            ]
        else:
            user_content = full_text

        # Prepend rolling context
        for msg in self._context.get_history():
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": user_content})

        self._context.add("user", full_text)

        provider_cfg = self._cfg.get(f"ai.providers.{self._provider}", {})
        model = provider_cfg.get("model", self._model)

        full_response = ""
        async for chunk in await self._client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            max_tokens=self._cfg.get("ai.max_tokens", 1024),
            temperature=self._cfg.get("ai.temperature", 0.7),
        ):
            delta = chunk.choices[0].delta
            if delta.content:
                full_response += delta.content
                self._bus.publish(AI_RESPONSE_CHUNK, chunk=delta.content)

        self._context.add("assistant", full_response)
        self._bus.publish(AI_RESPONSE_DONE, text=full_response, error=False)

    # ── Context helpers ───────────────────────────────────────────────────

    def _build_context_prefix(self) -> str:
        """Inject telemetry context as a prefix to the user message."""
        parts = []
        if self.active_window:
            parts.append(f"[Ventana activa: {self.active_window}]")
        if self.visible_windows:
            visible = ", ".join(self.visible_windows[:8])
            parts.append(f"[Apps abiertas: {visible}]")
        return " | ".join(parts)
