"""Minimal model client: chat with a JSON schema, and embeddings.

Two backends behind one interface, chosen in config/ai.json:
  ollama  native Ollama API (structured output via `format`, thinking switched off)
  openai  any OpenAI-compatible server, e.g. vLLM (structured output via `response_format`)
Standard library only, so nothing extra to install.
"""
from __future__ import annotations

import json
import urllib.request


class LLM:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.backend = cfg["backend"]
        self.base = cfg["base_url"].rstrip("/")
        self.model = cfg["model"]
        self.calls = 0

    def _post(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.cfg.get("timeout_s", 600)) as r:
            return json.loads(r.read().decode("utf-8"))

    def chat_json(self, system: str, user: str, schema: dict) -> tuple[dict | None, str]:
        """Returns (parsed JSON or None, raw text). Shape is enforced by the server; truth is checked by the caller."""
        self.calls += 1
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if self.backend == "ollama":
            resp = self._post("/api/chat", {"model": self.model, "messages": msgs, "format": schema, "stream": False,
                                            "think": False, "options": {"temperature": self.cfg.get("temperature", 0),
                                                                        "seed": self.cfg.get("seed", 42),
                                                                        "num_ctx": self.cfg.get("num_ctx", 8192)}})
            raw = resp["message"]["content"]
        else:
            resp = self._post("/v1/chat/completions", {"model": self.model, "messages": msgs,
                                                       "temperature": self.cfg.get("temperature", 0), "seed": self.cfg.get("seed", 42),
                                                       "response_format": {"type": "json_schema",
                                                                           "json_schema": {"name": "out", "schema": schema, "strict": True}}})
            raw = resp["choices"][0]["message"]["content"]
        try:
            out = json.loads(raw)
        except json.JSONDecodeError:
            return None, raw
        if not isinstance(out, dict) or any(k not in out for k in schema.get("required", [])):
            return None, raw
        return out, raw

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.backend == "ollama":
            return self._post("/api/embed", {"model": self.cfg["embed_model"], "input": texts})["embeddings"]
        resp = self._post("/v1/embeddings", {"model": self.cfg["embed_model"], "input": texts})
        return [d["embedding"] for d in resp["data"]]

    def describe(self) -> dict:
        """Model identity for the audit record (name, and digest when the server reports it)."""
        info = {"backend": self.backend, "model": self.model, "embed_model": self.cfg.get("embed_model"),
                "temperature": self.cfg.get("temperature"), "seed": self.cfg.get("seed"),
                "prompt_version": self.cfg.get("prompt_version")}
        if self.backend == "ollama":
            try:
                req = urllib.request.Request(self.base + "/api/tags")
                with urllib.request.urlopen(req, timeout=10) as r:
                    tags = json.loads(r.read().decode("utf-8"))["models"]
                info["digest"] = next((m["digest"][:12] for m in tags if m["name"] == self.model), None)
            except Exception:
                info["digest"] = None
        return info
