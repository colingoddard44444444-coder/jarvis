"""Small OpenAI-compatible chat client (works with OpenAI, Ollama, proxies, etc.)."""
from __future__ import annotations

import json
import os
import re
from typing import Any, Optional

import requests


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, cfg):
        self.provider = cfg.get("llm", "provider", default="openai")
        self.base_url = (cfg.get("llm", "base_url", default="") or "").strip()
        self.model = cfg.get("llm", "model", default="gpt-4o-mini")
        self.api_key = os.environ.get(cfg.get("llm", "api_key_env", default="OPENAI_API_KEY"), "") or ""

    def _endpoint(self) -> str:
        base = self.base_url or "https://api.openai.com/v1"
        return base.rstrip("/") + "/chat/completions"

    def chat(
        self,
        system: str,
        user: str,
        temperature: float = 0.7,
        max_tokens: int = 2500,
        json_mode: bool = False,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode and "openai" in self.provider:
            payload["response_format"] = {"type": "json_object"}

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            resp = requests.post(self._endpoint(), json=payload, headers=headers, timeout=60)
        except requests.RequestException as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc

        if resp.status_code != 200:
            raise LLMError(f"LLM API error {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def chat_json(self, system: str, user: str, **kwargs) -> dict:
        content = self.chat(system, user, json_mode=True, **kwargs)
        return parse_json(content)


def parse_json(content: str) -> dict:
    """Parse JSON from LLM output, tolerating markdown fences and stray text."""
    content = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", content, re.S)
    if fenced:
        content = fenced.group(1).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start != -1 and end > start:
            return json.loads(content[start : end + 1])
        raise LLMError(f"Could not parse JSON from LLM response: {content[:300]}")
