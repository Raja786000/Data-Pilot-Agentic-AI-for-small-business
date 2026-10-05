"""Optional AI layer. Works with OpenAI and any OpenAI-compatible service (OpenRouter, Groq, Ollama, ...)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from . import store

PRESETS = {
    "openai": {"label": "OpenAI", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "needs_key": True},
    "openrouter": {"label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "model": "openai/gpt-4o-mini", "needs_key": True},
    "groq": {"label": "Groq", "base_url": "https://api.groq.com/openai/v1", "model": "llama-3.3-70b-versatile", "needs_key": True},
    "ollama": {"label": "Ollama (free, on this computer)", "base_url": "http://localhost:11434/v1", "model": "llama3.2", "needs_key": False},
    "custom": {"label": "Other (OpenAI-compatible)", "base_url": "", "model": "", "needs_key": True},
}


def config():
    s = store.settings_full()["ai"]
    prov = s.get("provider") or "openai"
    preset = PRESETS.get(prov, PRESETS["custom"])
    key = s.get("api_key") or (os.getenv("OPENAI_API_KEY", "") if prov == "openai" else "")
    base = (s.get("base_url") or preset["base_url"]).rstrip("/")
    model = s.get("model") or preset["model"]
    ok = bool(base and model and (key or not preset["needs_key"]))
    return {"provider": prov, "key": key, "base_url": base, "model": model, "ready": ok}


def complete(system: str, user: str, timeout: int = 45):
    """Return (text, error). Never raises."""
    cfg = config()
    if not cfg["ready"]:
        return None, "AI is not set up. Add a key in Settings → AI assistant."
    body = json.dumps({"model": cfg["model"], "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}).encode()
    req = urllib.request.Request(cfg["base_url"] + "/chat/completions", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if cfg["key"]:
        req.add_header("Authorization", "Bearer " + cfg["key"])
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        text = (data["choices"][0]["message"]["content"] or "").strip()
        return (text or None), (None if text else "The AI returned an empty answer.")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("error", {})
            detail = detail.get("message") if isinstance(detail, dict) else str(detail)
        except Exception:
            detail = ""
        hints = {401: "The API key was rejected. Check it in Settings.", 403: "This key is not allowed to use that model.",
                 404: "The model name was not found. Check the model name in Settings.", 429: "The AI service is rate-limiting or out of credit."}
        return None, hints.get(e.code, f"The AI service returned an error ({e.code}).") + (f" {detail}" if detail else "")
    except urllib.error.URLError as e:
        return None, f"Could not reach {cfg['base_url']}. Check your internet connection" + (" and that Ollama is running." if cfg["provider"] == "ollama" else ".")
    except Exception as e:  # noqa
        return None, f"AI request failed: {e}"
