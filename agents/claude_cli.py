"""
Drop-in replacement for anthropic.AsyncAnthropic that routes through Claude Code CLI.

No API key needed — uses active Claude Code subscription.

Usage (identical to anthropic SDK):
    from claude_cli import get_client
    client = get_client()
    resp = await client.messages.create(
        model="claude-opus-4-8",
        max_tokens=800,
        messages=[{"role": "user", "content": "..."}],
    )
    text = resp.content[0].text
"""

import asyncio
import os
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass
class _Content:
    text: str
    type: str = "text"


@dataclass
class _Response:
    content: list


def _extract_prompt(messages: list) -> str:
    parts = []
    for m in messages:
        if m.get("role") == "user":
            c = m.get("content", "")
            if isinstance(c, str):
                parts.append(c)
            elif isinstance(c, list):
                for block in c:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block["text"])
    return "\n\n".join(parts)


def _run_claude(prompt: str) -> str:
    # Strip ANTHROPIC_API_KEY from env so claude CLI uses its own session auth
    # (placeholder key in .env would override claude's subscription auth)
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    if result.returncode != 0:
        err = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"claude CLI error (code {result.returncode}): {err}")
    return result.stdout.strip()


class _FakeStream:
    """Fake streaming context manager — runs claude -p and yields text word by word."""
    def __init__(self, messages, **kwargs):
        self._messages = messages or []
        self._text = ""

    def __enter__(self):
        self._text = _run_claude(_extract_prompt(self._messages))
        return self

    def __exit__(self, *args):
        pass

    @property
    def text_stream(self):
        # Yield in small chunks to simulate streaming output
        chunk_size = 8
        for i in range(0, len(self._text), chunk_size):
            yield self._text[i:i + chunk_size]


class _SyncMessages:
    def create(self, model: str = "", max_tokens: int = 4096, messages: list = None, **kwargs) -> _Response:
        if not messages:
            raise ValueError("messages required")
        text = _run_claude(_extract_prompt(messages))
        return _Response(content=[_Content(text=text)])

    def stream(self, model: str = "", max_tokens: int = 4096, messages: list = None, **kwargs) -> _FakeStream:
        return _FakeStream(messages or [], model=model, max_tokens=max_tokens)


class _AsyncMessages:
    async def create(self, model: str = "", max_tokens: int = 4096, messages: list = None, **kwargs) -> _Response:
        if not messages:
            raise ValueError("messages required")
        loop = asyncio.get_event_loop()
        prompt = _extract_prompt(messages)
        text = await loop.run_in_executor(None, _run_claude, prompt)
        return _Response(content=[_Content(text=text)])


class _ClaudeCodeClient:
    def __init__(self):
        self.messages = _SyncMessages()


class _AsyncClaudeCodeClient:
    def __init__(self):
        self.messages = _AsyncMessages()


def get_client() -> _AsyncClaudeCodeClient:
    """Return async Claude Code CLI client (no API key needed)."""
    return _AsyncClaudeCodeClient()


# Compatibility shims — drop-in for anthropic SDK
class AsyncAnthropic(_AsyncClaudeCodeClient):
    def __init__(self, api_key: str = "", **kwargs):
        super().__init__()


class Anthropic(_ClaudeCodeClient):
    def __init__(self, api_key: str = "", **kwargs):
        super().__init__()
