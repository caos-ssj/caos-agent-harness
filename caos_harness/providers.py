"""Accounts, provider presets, multi-host Ollama, intent resolution, live smoke tests and real failover.

Secrets stay out of repository files (`harness.toml`, `providers.json`, `board.db`, traces):
  1. Read from process environment (`<VAR>`), then gitignored `.env.local` (project or global config home, chmod 0600),
     then optional system keyring under service `caos-agent-harness`.
  2. Writes go only to system keyring or gitignored `.env.local`, never to tracked config JSON/TOML.
  3. Values are masked before returning metadata and redacted from any exception or provider error text.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

SERVICE = "caos-agent-harness"
DEFAULT_OLLAMA = os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434"


def default_ollama_url() -> str:
    """Resolves the active Ollama base URL, honoring runtime OLLAMA_HOST overrides."""
    return (os.environ.get("OLLAMA_HOST") or DEFAULT_OLLAMA).rstrip("/")

PRESETS: dict[str, dict] = {
    "anthropic": {
        "name": "Anthropic",
        "env": "ANTHROPIC_API_KEY",
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "url": "https://api.anthropic.com/v1/messages",
        "models": "https://api.anthropic.com/v1/models",
        "default_model": "claude-sonnet-4-20250514",
        "description": "Direct Anthropic Messages API with tool calling.",
    },
    "openai": {
        "name": "OpenAI",
        "env": "OPENAI_API_KEY",
        "kind": "openai",
        "base_url": "https://api.openai.com/v1",
        "url": "https://api.openai.com/v1/chat/completions",
        "models": "https://api.openai.com/v1/models",
        "default_model": "gpt-4.1-mini",
        "description": "OpenAI Chat Completions and tool calling.",
    },
    "openrouter": {
        "name": "OpenRouter",
        "env": "OPENROUTER_API_KEY",
        "kind": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "models": "https://openrouter.ai/api/v1/models",
        "default_model": "openrouter/free",
        "description": "Multi-model OpenAI-compatible gateway.",
        "free_models": ["openrouter/free", "cohere/north-mini-code:free", "google/gemma-4-31b-it:free", "google/gemma-4-26b-a4b-it:free", "nvidia/nemotron-3-ultra-550b-a55b:free", "nvidia/nemotron-3.5-lightning:free", "baidu/ernie-5.5-flash-preview:free"],
        "tier_hint": "Free :free tier: 20 RPM / 50 RPD (1,000 RPD after lifetime top-up); configurable no-training filter",
    },
    "gemini": {
        "name": "Google Gemini Gateway",
        "env": "GEMINI_API_KEY",
        "kind": "openai",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "models": "https://generativelanguage.googleapis.com/v1beta/openai/models",
        "default_model": "gemini-3.8-flash",
        "description": "Gemini OpenAI-compatible endpoint.",
        "free_models": ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3-flash-preview"],
        "tier_hint": "Free tier available; provider notes free content improves products (avoid client/private data)",
    },
    "deepseek": {
        "name": "DeepSeek",
        "env": "DEEPSEEK_API_KEY",
        "kind": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "url": "https://api.deepseek.com/v1/chat/completions",
        "models": "https://api.deepseek.com/v1/models",
        "default_model": "deepseek-chat",
        "description": "DeepSeek reasoning and coding API.",
    },
    "groq": {
        "name": "Groq",
        "env": "GROQ_API_KEY",
        "kind": "openai",
        "base_url": "https://api.groq.com/openai/v1",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "models": "https://api.groq.com/openai/v1/models",
        "default_model": "openai/gpt-oss-120b",
        "description": "Low-latency OpenAI-compatible inference.",
        "free_models": ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"],
        "tier_hint": "30 RPM / 1K RPD / 8K TPM base ceiling; best for compact prompts",
    },
    "nvidia": {
        "name": "NVIDIA NIM",
        "env": "NVIDIA_API_KEY",
        "kind": "openai",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "models": "https://integrate.api.nvidia.com/v1/models",
        "default_model": "deepseek-ai/deepseek-v4-flash",
        "free_models": ["deepseek-ai/deepseek-v4-flash", "deepseek-ai/deepseek-v4-pro", "qwen/qwen2.5-coder-32b-instruct", "moonshotai/kimi-k2-instruct", "mistralai/mistral-nemotron"],
        "tier_hint": "OpenAI-compatible gateway via NVIDIA_API_KEY",
        "description": "NVIDIA NIM OpenAI-compatible inference (DeepSeek, Qwen, Kimi, Mistral).",
    },
}

# Preserve API symbol used by existing tests and `app.load()`.
API = {k: {**v} for k, v in PRESETS.items()}

CLIS = {
    "claude": {"label": "Claude Code", "account": "your Claude subscription", "bin": "claude", "command": ["claude", "-p"], "timeout": 600,
               "models": ["sonnet", "opus", "haiku"]},
    "codex": {"label": "OpenAI Codex", "account": "your ChatGPT subscription", "bin": "codex", "command": ["codex", "exec", "-"], "timeout": 600,
              "models": ["gpt-5.3-codex", "o4-mini", "gpt-4.1"]},
    "opencode": {"label": "OpenCode CLI", "account": "your OpenCode CLI / free Zen models", "bin": "opencode", "command": ["opencode", "run", "-m", "opencode/glm-5.3-flash-free"], "timeout": 600,
                 "free_models": ["opencode/glm-5.3-flash-free", "opencode/deepseek-v4.1-flash-free", "opencode/minimax-m3.1-flash-free", "opencode/beam-free"]},
    # `agy` takes the prompt as the value of `-p`, not on stdin: "{prompt}" is replaced by the task, one argv element, never through a shell.
    "agy": {"label": "Antigravity CLI", "account": "your Antigravity account", "bin": "agy",
            "command": ["agy", "--mode", "accept-edits", "--output-format", "text", "-p", "{prompt}"], "timeout": 600,
            "models": ["gemini-4-argon-high", "gemini-4-argon-medium", "gemini-3.8-flash-high", "gemini-3.8-flash-medium",
                       "claude-sonnet-5-5-high", "claude-opus-5-5-high", "gpt-oss-120b-medium"]},
}
# CLIs that can plan and synthesise a multi-agent job (they read a prompt and answer in text), and the flag each takes a model with.
ORCHESTRATOR_CLIS = ("claude", "agy", "codex", "opencode")
MODEL_FLAG = {"claude": "--model", "agy": "--model", "opencode": "-m", "codex": "-m"}
NAME = re.compile(r"[a-z0-9][a-z0-9_\-]{0,31}")
MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/\-]{0,95}")
ENV_VAR = re.compile(r"[A-Z][A-Z0-9_]{2,63}")
INTENTS = ("rapido", "codigo", "razonar", "local")

Transport = Callable[[str, dict, dict | None, float], tuple]


class ProviderError(Exception):
    """A message that is safe to show: it never contains the key."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):   # never forward credentials across redirects
        return None


SECRET = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\bsk-[A-Za-z0-9_\-]{20,}"
    r"|\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}"
    r"|\bAIza[0-9A-Za-z\-_]{30,}"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\bgh[pousr]_[A-Za-z0-9]{30,}"
    r"|\bgithub_pat_[A-Za-z0-9_]{30,}"
    r"|\bglpat-[A-Za-z0-9_\-]{20,}"
    r"|\bxox[bpas]-[A-Za-z0-9\-]{10,}"
    r"|\bxapp-[A-Za-z0-9\-]{10,}"
    r"|\bhf_[A-Za-z0-9]{30,}"
    r"|\bnpm_[A-Za-z0-9]{30,}"
    r"|\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"      # a JWT
    r"|\bBearer\s+[A-Za-z0-9_\-\.=]{24,}"
    r"|://[^\s/:@]+:[^\s/@]{3,}@"                                                    # credentials inside a URL
)

# A name that says it holds a secret: any word of it is one of these (`api_key`, `OPENAI_API_KEY`, `userToken`, `db-password`).
_SECRET_WORDS = {"key", "secret", "token", "password", "passwd", "pwd", "credential", "apikey", "privatekey", "passphrase"}
# ...unless it says what the value is instead: the name of a variable, a file, a URL, a count.
_NOT_THE_VALUE = {"env", "file", "path", "url", "uri", "name", "count", "limit", "type", "kind", "source", "hint", "label", "id", "ref", "var", "field", "placeholder", "header"}
_ASSIGN = re.compile(
    r"""(?P<name>["']?[A-Za-z][A-Za-z0-9_.\-]*["']?)\s*(?::|=)\s*"""
    r"""(?P<value>"[^"\n]*"|'[^'\n]*'|[^\s,;#"'}\]\)]+)"""
)
_PLACEHOLDER = ("your", "example", "changeme", "change_me", "placeholder", "dummy", "xxxx", "redacted", "removed", "todo", "fake", "<", ">", "${", "$(", "{{", "%(", "...", "*****")


def _name_words(name: str) -> list[str]:
    name = name.strip("\"'")
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return [w for w in re.split(r"[_.\-]+", spaced.lower()) if w]


def secret_name(name: str) -> bool:
    words = _name_words(name)
    return bool(words) and words[-1] not in _NOT_THE_VALUE and any(w in _SECRET_WORDS for w in words)


def secret_value(raw: str) -> bool:
    """Would this value be a credential if it sat beside a secret-sounding name? Placeholders, variable names, URLs and code are not."""
    quoted = len(raw) >= 2 and raw[0] in "\"'" and raw[-1] == raw[0]
    v = raw[1:-1] if quoted else raw
    low = v.lower()
    if len(v) < 8 or any(p in low for p in _PLACEHOLDER):
        return False
    if re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", v):                       # the NAME of an environment variable
        return False
    if re.match(r"https?://", low) or v.startswith(("/", "./", "~", "$")):
        return False
    if v.count(" ") >= 3:                                            # a sentence, not a credential
        return False
    if re.fullmatch(r"[a-z_\-.]+", v) and ("_" in v or "-" in v or "." in v or len(v) < 20):   # an identifier
        return False
    if not quoted:
        if re.search(r"[()\[\]{}$]", v) or not re.search(r"\d", v) or len(v) < 12:
            return False
    return True


def secret_assignments(line: str) -> list[tuple[str, int, int]]:
    """`(name, start, end)` of every `name = value` / `"name": "value"` on the line whose name says secret and whose value could be one."""
    out = []
    for m in _ASSIGN.finditer(line or ""):
        if secret_name(m.group("name")) and secret_value(m.group("value")):
            out.append((m.group("name").strip("\"'"), m.start("value"), m.end("value")))
    return out


def config_home() -> Path:
    base = os.environ.get("CAOS_HARNESS_HOME")
    return Path(base) if base else Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "caos-harness"


def looks_like_secret(text: str) -> bool:
    """A known key shape anywhere in the text, or a secret-sounding name given a value that could be one."""
    text = text or ""
    return bool(SECRET.search(text)) or bool(secret_assignments(text))


def mask_key(secret: str | None) -> str:
    if not secret or len(secret) < 8:
        return ""
    return f"{secret[:3]}••••{secret[-4:]}"


def redact(text: str, key: str | None) -> str:
    """Whatever comes back, the key never travels further than the call."""
    return text.replace(key, "[key removed]") if key and len(key) >= 8 else text


def http(url: str, headers: dict, body: dict | None, timeout: float) -> tuple:
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode() if body is not None else None,
            headers={**headers, "Content-Type": "application/json", "User-Agent": "caos-harness"},
        )
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except ValueError:
            return e.code, {}
    except Exception:
        raise ProviderError("could not reach the provider (no answer, or the call was refused)") from None


def _read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and v:
                out[k] = v
    except OSError:
        pass
    return out


def _write_env_file(path: Path, updates: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_env_file(path)
    existing.update(updates)
    lines = ["# Local CAOS Harness API keys (gitignored; mode 0600)"] + [f"{k}={v}" for k, v in sorted(existing.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _ensure_gitignore(root: Path) -> None:
    gi = root / ".gitignore"
    entries = [".env.local", ".harness/"]
    if not gi.is_file():
        return
    txt = gi.read_text(encoding="utf-8", errors="ignore")
    add = [e for e in entries if e not in txt]
    if add:
        sep = "" if txt.endswith("\n") or not txt else "\n"
        gi.write_text(txt + sep + "\n".join(add) + "\n", encoding="utf-8")


def _default_env(provider: str, key_env: str | None = None, custom_cfg: dict | None = None) -> str | None:
    if key_env:
        return key_env
    if provider in API:
        return API[provider]["env"]
    if custom_cfg and isinstance(custom_cfg.get("api_key_env"), str):
        return custom_cfg["api_key_env"]
    slug = re.sub(r"[^A-Z0-9]+", "_", provider.upper()).strip("_")
    return f"{slug}_API_KEY" if slug else None


def key_for(provider: str, key_env: str | None = None, root: Path | None = None) -> tuple[str | None, str]:
    """Returns `(key, source)` from process env, gitignored `.env.local`, or optional keyring."""
    custom_cfg = None
    if provider not in API:
        custom_cfg = find_custom_provider(provider, root=root)
    env = _default_env(provider, key_env, custom_cfg)
    if not env:
        return None, "none"
    if os.environ.get(env):
        if not re.fullmatch(r"[\x21-\x7e]{8,512}", os.environ[env]):
            raise ProviderError(f"{env} has spaces, line breaks or other characters a key cannot have")
        return os.environ[env], f"environment variable {env}"
    env_files: list[tuple[Path, str]] = []
    if root:
        env_files += [(root / ".harness" / ".env.local", f".harness/.env.local ({env})"), (root / ".env.local", f".env.local ({env})")]
    env_files.append((config_home() / ".env.local", f"global .env.local ({env})"))
    for fp, src in env_files:
        val = _read_env_file(fp).get(env)
        if val:
            if not re.fullmatch(r"[\x21-\x7e]{8,512}", val):
                raise ProviderError(f"{env} in {fp.name} has invalid characters")
            return val, src
    try:
        import keyring   # optional extra
        for lookup in (provider, env):
            k = keyring.get_password(SERVICE, lookup)
            if k:
                return k, "system keyring"
    except Exception:
        pass
    return None, "none"


def save_key(provider: str, secret: str, env_name: str | None = None, storage: str = "auto", root: Path | None = None) -> dict:
    """Stores a key securely in system keyring or gitignored 0600 `.env.local`. Never writes to JSON/TOML or echoes value."""
    val = (secret or "").strip()
    if not re.fullmatch(r"[\x21-\x7e]{8,512}", val):
        raise ValueError("API key must be 8-512 printable non-space characters")
    env = env_name or _default_env(provider, None, find_custom_provider(provider, root=root))
    if not env or not ENV_VAR.fullmatch(env):
        raise ValueError("env_name must look like OPENROUTER_API_KEY")
    if storage in ("auto", "keyring"):
        try:
            import keyring   # type: ignore[import-not-found]
            keyring.set_password(SERVICE, provider, val)
            if env != provider:
                keyring.set_password(SERVICE, env, val)
            return {"ok": True, "saved": True, "storage": "system keyring", "env": env, "masked": mask_key(val)}
        except Exception:
            if storage == "keyring":
                raise ValueError("system keyring backend is not available; use 'env_local' storage instead")
    if storage in ("project_env", "env_local") and root:
        _ensure_gitignore(root)
        target = root / ".harness" / ".env.local"
        _write_env_file(target, {env: val})
        return {"ok": True, "saved": True, "storage": f".harness/.env.local ({env})", "env": env, "masked": mask_key(val)}
    target = config_home() / ".env.local"
    _write_env_file(target, {env: val})
    return {"ok": True, "saved": True, "storage": f"global .env.local ({env})", "env": env, "masked": mask_key(val)}


def _safe_base_url(base_url: str) -> str:
    b = (base_url or "").strip().rstrip("/")
    if not b.startswith(("http://", "https://")):
        raise ValueError("base_url must start with http:// or https://")
    parts = urllib.parse.urlsplit(b)
    if not parts.hostname or parts.username or parts.password:
        raise ValueError("base_url needs a host and no credentials inside it")
    return b


safe_base_url = _safe_base_url


def declared_key_envs(root: Path | None = None) -> set[str]:
    """The environment variables a request may name as the source of a key: the presets', the saved gateways', and the default each id would get."""
    names = {spec["env"] for spec in API.values() if spec.get("env")}
    for c in custom_providers(root=root):
        if c.get("api_key_env"):
            names.add(c["api_key_env"])
        names.add(_default_env(str(c.get("id") or ""), None, c) or "")
    return {n for n in names if n and ENV_VAR.fullmatch(n)}


def check_probe_target(provider: str, base_url: str | None, key_env: str | None, root: Path | None = None) -> None:
    """A test or smoke request carries a key to an address. Refuse a variable nobody declared, and refuse sending a
    provider's own key to an address that is not its own."""
    if key_env:
        if not ENV_VAR.fullmatch(key_env) or key_env not in declared_key_envs(root):
            raise ValueError("key_env must be a variable a provider declares: " + ", ".join(sorted(declared_key_envs(root))))
    if not base_url or provider == "ollama":
        return
    b = _safe_base_url(base_url)
    known = (API.get(provider) or {}).get("base_url") or (find_custom_provider(provider, root=root) or {}).get("base_url")
    if known:
        same = urllib.parse.urlsplit(_safe_base_url(known)).netloc == urllib.parse.urlsplit(b).netloc
        if not same:
            raise ValueError(f"base_url is not {provider}'s address; save the gateway first, or leave base_url empty")
    elif key_env or key_for(provider, None, root=root)[0]:
        raise ValueError("this id has a key and no saved address; save the gateway before testing a different address")


def endpoint_for(provider: str, base_url: str | None = None, root: Path | None = None) -> tuple[str, str, str, str]:
    """Returns `(kind, chat_url, models_url, label)` for built-in presets or custom gateways."""
    if base_url:
        b = _safe_base_url(base_url)
        kind = API[provider]["kind"] if provider in API else "openai"
        if kind == "anthropic":
            return "anthropic", f"{b}/messages", f"{b}/models", API.get(provider, {}).get("name", provider)
        return "openai", f"{b}/chat/completions", f"{b}/models", API.get(provider, {}).get("name", provider)
    if provider in API:
        p = API[provider]
        return p["kind"], p["url"], p["models"], p["name"]
    c = find_custom_provider(provider, root=root)
    if not c or not c.get("base_url"):
        raise ProviderError(f"unknown provider: {provider}")
    b = _safe_base_url(c["base_url"])
    kind = c.get("kind") or ("anthropic" if "anthropic" in b else "openai")
    chat_url = f"{b}/messages" if kind == "anthropic" else f"{b}/chat/completions"
    return kind, chat_url, f"{b}/models", c.get("name") or provider


def _headers(kind: str, key: str | None) -> dict:
    if not key:
        return {}
    if kind == "anthropic":
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    return {"Authorization": f"Bearer {key}"}


def _fail(label: str, status: int) -> ProviderError:
    hint = {401: "the key was refused", 403: "the key has no access to that", 404: "no such model", 429: "rate limit or quota reached"}.get(
        status, f"the provider answered {status}"
    )
    return ProviderError(f"{label}: {hint}")


def ask(
    provider: str,
    model: str,
    prompt: str,
    key: str,
    timeout: float = 120,
    transport: Transport = http,
    base_url: str | None = None,
    root: Path | None = None,
) -> str:
    kind, chat_url, _, label = endpoint_for(provider, base_url=base_url, root=root)
    if kind == "anthropic":
        status, data = transport(
            chat_url,
            _headers("anthropic", key),
            {"model": model, "max_tokens": 4096, "messages": [{"role": "user", "content": prompt}]},
            timeout,
        )
        if status != 200:
            raise _fail(label, status)
        return redact("".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"), key)
    status, data = transport(
        chat_url,
        _headers("openai", key),
        {"model": model, "messages": [{"role": "user", "content": prompt}]},
        timeout,
    )
    if status != 200:
        raise _fail(label, status)
    return redact((data.get("choices") or [{}])[0].get("message", {}).get("content", "") or "", key)


def models(
    provider: str,
    key: str | None = None,
    timeout: float = 10,
    transport: Transport = http,
    base_url: str | None = None,
    root: Path | None = None,
) -> list[str]:
    kind, _, models_url, label = endpoint_for(provider, base_url=base_url, root=root)
    status, data = transport(models_url, _headers(kind, key), None, timeout)
    if status != 200:
        raise _fail(label, status)
    names = [m.get("id") for m in data.get("data", []) if isinstance(m, dict) and isinstance(m.get("id"), str)]
    if provider == "openai":
        names = [n for n in names if re.match(r"(gpt|o\d|chatgpt)", n) and "embed" not in n and "audio" not in n and "image" not in n]
    safe = sorted(n for n in names if not looks_like_secret(n) and redact(n, key) == n)
    curated = set((PRESETS.get(provider) or {}).get("free_models") or [])
    free_first = [n for n in safe if n.endswith(":free") or n == "openrouter/free" or n in curated]
    rest = [n for n in safe if n not in set(free_first)]
    return (free_first + rest)[:120]   # the free ones first, so a 460-model catalogue never cuts them off


def test(
    provider: str,
    key_env: str | None = None,
    transport: Transport = http,
    base_url: str | None = None,
    root: Path | None = None,
) -> dict:
    """Tests connectivity and auth cleanly, returning ping latency and models."""
    t0 = time.perf_counter()
    try:
        key, where = key_for(provider, key_env, root=root) if (key_env or root) else key_for(provider)
    except ProviderError as e:
        return {"ok": False, "message": str(e), "latency_ms": 0}
    env_hint = key_env or (API[provider]["env"] if provider in API else _default_env(provider, root=root))
    if not key and not (base_url and base_url.startswith("http://127.0.0.1")):
        return {
            "ok": False,
            "latency_ms": 0,
            "message": f"no key: set {env_hint} in the environment where caos-harness serve starts, or store it in keyring/.env.local",
        }
    try:
        found = models(provider, key, transport=transport, base_url=base_url, root=root)
    except ProviderError as e:
        return {"ok": False, "message": str(e), "source": where, "latency_ms": round((time.perf_counter() - t0) * 1000)}
    ms = round((time.perf_counter() - t0) * 1000)
    return {"ok": True, "message": f"connected ({where}): {len(found)} models available ({ms} ms)", "models": found, "source": where, "latency_ms": ms}


def detect_clis(added: set[str] | None = None) -> list[dict]:
    """Which known CLIs are installed here. Never exposes executable paths."""
    out = []
    for cid, c in CLIS.items():
        out.append({
            "id": cid,
            "label": c["label"],
            "account": c["account"],
            "installed": shutil.which(c["bin"]) is not None,
            "command": " ".join(c["command"]),
            "added": bool(added and cid in added),
            "free_models": list(c.get("free_models") or []),
            "models": list(c.get("models") or c.get("free_models") or []),
            "orchestrator_capable": cid in ORCHESTRATOR_CLIS,
            "effort": dict(zip(("supported", "reason"), effort_support(c["command"]))),
        })
    return out


def cli_command(cid: str, model: str | None = None) -> list[str]:
    """The command an agent runs for a known CLI. `claude`, `agy`, `opencode` and `codex` take a model, any one that is a plain model name."""
    base = list(CLIS[cid]["command"])
    if not model:
        return base
    if cid not in MODEL_FLAG:
        return base
    if not MODEL.fullmatch(model):
        raise ValueError("model must be a model name")
    flag = MODEL_FLAG[cid]
    if cid == "opencode":
        return ["opencode", "run", "-m", model]
    if cid == "codex":          # codex exec [-m MODEL] -   (the dash stays last: the task arrives on stdin)
        return ["codex", "exec", flag, model, "-"]
    if cid == "claude":
        return ["claude", flag, model, "-p"]
    i = base.index("-p")        # agy: the flag goes before -p, whose value is the prompt
    return base[:i] + [flag, model] + base[i:]


def model_of(command=(), provider: str | None = None, model: str | None = None, system: str | None = None) -> str | None:
    """The effective model of an agent: explicit `model` or `system`, or extracted from `--model`/`-m`/`ollama run <model>` in `command`."""
    if model:
        return model
    if system:
        return system
    cmd = list(command or ())
    for i, part in enumerate(cmd):
        if part in ("--model", "-m") and i + 1 < len(cmd) and not cmd[i + 1].startswith("-"):
            return cmd[i + 1]
        if part.startswith("--model=") or part.startswith("-m="):
            val = part.split("=", 1)[1].strip()
            if val:
                return val
    if len(cmd) >= 3 and Path(cmd[0]).name == "ollama" and cmd[1] == "run":
        return cmd[2]
    return None


# Effort: how hard the agent is asked to think. Only what the installed tool documents is translated; anywhere else the setting is
# refused with the reason, never silently dropped. Checked against `claude --help` (--effort <level>) and `codex exec --help`
# (-c key=value, with the config key `model_reasoning_effort`). `opencode run` takes it only as a per-model variant
# (`provider/model#variant`) and `agy` as part of the model name, so neither gets a generic flag from here.
EFFORTS = ("low", "medium", "high")
EFFORT_UNSUPPORTED = {
    "opencode": "OpenCode takes effort as a model variant (provider/model#variant) that depends on the model: choose it in the model name",
    "agy": "Antigravity fixes the effort in the model name (…-high, …-medium): choose it there",
    "ollama": "Ollama models have no effort setting",
}


def effort_support(command, provider: str | None = None) -> tuple[bool, str]:
    """Whether an agent's command takes an effort level, and how (or why not), in words for the operator."""
    if provider:
        return False, "API agents send no effort setting from here yet"
    cmd = list(command or ())
    if not cmd:
        return False, "no command"
    b = Path(cmd[0]).name
    if b == "claude":
        if any(x == "--effort" or x.startswith("--effort=") for x in cmd):
            return False, "this command already sets --effort itself"
        return True, "sent as claude --effort <level>"
    if b == "codex":
        if "exec" not in cmd:
            return False, "only `codex exec` takes the setting"
        if any("model_reasoning_effort" in x for x in cmd):
            return False, "this command already sets model_reasoning_effort itself"
        return True, "sent as codex exec -c model_reasoning_effort=<level>"
    return False, EFFORT_UNSUPPORTED.get(b, f"{b} has no documented effort setting")


def with_effort(command, effort: str | None) -> list[str]:
    """The command with the effort level added where the tool takes one; unchanged with no effort or a tool that takes none."""
    cmd = list(command)
    if not effort or effort not in EFFORTS or not effort_support(cmd)[0]:
        return cmd
    if Path(cmd[0]).name == "claude":
        return [cmd[0], "--effort", effort] + cmd[1:]
    i = cmd.index("exec")       # codex: an option of `exec`, before the dash that stands for stdin
    return cmd[:i + 1] + ["-c", f"model_reasoning_effort={effort}"] + cmd[i + 1:]


# ── Persistent Global + Legacy Custom Providers, Ollama Hosts, Intents & Failover ──────

def _load_json_dict(path: Path, default):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def _save_json_atomic(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _strip_secrets(row: dict) -> tuple[dict, bool]:
    """Removes plaintext secret fields (`api_key`, `key`, `secret`, `token`) from saved metadata dicts."""
    clean = dict(row)
    dirty = False
    for k in ("api_key", "key", "secret", "token"):
        if k in clean:
            clean.pop(k, None)
            dirty = True
    return clean, dirty


def custom_providers(root: Path | None = None) -> list[dict]:
    """Reads configured custom / preset OpenAI-compat entries across global home + project legacy file, stripping secrets."""
    rows: list[dict] = []
    seen: set[str] = set()
    sources = []
    if root:
        sources.append(root / ".harness" / "custom_providers.json")
    sources.append(config_home() / "custom_providers.json")
    for fp in sources:
        raw = _load_json_dict(fp, [])
        cleaned_file: list[dict] = []
        had_secret = False
        for item in raw:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            clean, dirty = _strip_secrets(item)
            if dirty:
                had_secret = True
            cleaned_file.append(clean)
            if clean["id"] not in seen:
                seen.add(clean["id"])
                rows.append(clean)
        if had_secret:
            try:
                _save_json_atomic(fp, cleaned_file)
            except OSError:
                pass
    return rows


def find_custom_provider(provider_id: str, root: Path | None = None) -> dict | None:
    for item in custom_providers(root=root):
        if item.get("id") == provider_id:
            return item
    return None


def save_custom_provider(body: dict, root: Path | None = None, scope: str = "global") -> dict:
    """Validates and saves a custom provider or preset override cleanly (never storing plaintext API keys in JSON)."""
    if any(body.get(k) for k in ("api_key", "key", "secret", "token")):
        raise ValueError("keys are not stored in custom_providers.json; pass api_key_env or use keyring/.env.local")
    name = str(body.get("name") or body.get("id") or "").strip()[:80]
    if not name:
        raise ValueError("provider name is required")
    pid = re.sub(r"[^a-z0-9_\-]+", "-", str(body.get("id") or name).lower()).strip("-")[:40]
    if not pid:
        raise ValueError("valid provider id or name is required")
    kenv = body.get("api_key_env")
    if kenv is not None and str(kenv).strip():
        kenv = str(kenv).strip()
        if not ENV_VAR.fullmatch(kenv):
            raise ValueError("api_key_env must be an environment variable name, like OPENROUTER_API_KEY")
    else:
        kenv = PRESETS[pid]["env"] if pid in PRESETS else None
    base_url = _safe_base_url(str(body.get("base_url") or PRESETS.get(str(body.get("id") or ""), {}).get("base_url") or ""))
    models_list = [str(m).strip()[:100] for m in (body.get("models") or []) if isinstance(m, str) and m.strip()][:60]
    clean = {
        "id": pid,
        "name": name,
        "type": "custom" if pid not in PRESETS else "cloud",
        "kind": body.get("kind") or PRESETS.get(pid, {}).get("kind", "openai"),
        "base_url": base_url,
        "api_key_env": kenv,
        "models": models_list,
        "default_model": str(body.get("default_model") or (models_list[0] if models_list else PRESETS.get(pid, {}).get("default_model", ""))).strip()[:100],
        "enabled": bool(body.get("enabled", True)),
        "description": str(body.get("description") or f"Endpoint {base_url}")[:160],
    }
    target = (root / ".harness" / "custom_providers.json") if (scope == "project" and root) else (config_home() / "custom_providers.json")
    cur = []
    for r in _load_json_dict(target, []):
        if isinstance(r, dict) and r.get("id") and r.get("id") != pid:
            c, _ = _strip_secrets(r)
            cur.append(c)
    cur.append(clean)
    _save_json_atomic(target, cur)
    return clean


def ollama_hosts(root: Path | None = None) -> list[dict]:
    """Returns configured Ollama host entries (`local` + remote LAN/Tailscale hosts)."""
    hosts = _load_json_dict(config_home() / "ollama_hosts.json", [])
    if root:
        proj = _load_json_dict(root / ".harness" / "ollama_hosts.json", [])
        seen = {h.get("url") for h in hosts if isinstance(h, dict)}
        for h in proj:
            if isinstance(h, dict) and h.get("url") and h["url"] not in seen:
                hosts.append(h)
    valid = [
        {"id": str(h.get("id") or f"ollama-{i}"), "label": str(h.get("label") or h["url"])[:60], "url": _safe_base_url(h["url"])}
        for i, h in enumerate(hosts)
        if isinstance(h, dict) and isinstance(h.get("url"), str) and h["url"].startswith(("http://", "https://"))
    ]
    base_url = default_ollama_url()
    if not any(h["url"].rstrip("/") == base_url for h in valid):
        valid.insert(0, {"id": "local", "label": "Local Ollama", "url": base_url})
    return valid


def save_ollama_host(url: str, label: str = "", host_id: str | None = None, root: Path | None = None) -> list[dict]:
    clean_url = _safe_base_url(url)
    hid = re.sub(r"[^a-z0-9_\-]+", "-", (host_id or label or "remote").lower()).strip("-") or "remote"
    hosts = [h for h in ollama_hosts(root) if h["url"] != clean_url and h["id"] != hid]
    hosts.append({"id": hid, "label": (label or clean_url)[:60], "url": clean_url})
    _save_json_atomic(config_home() / "ollama_hosts.json", hosts)
    return ollama_hosts(root)


def remove_ollama_host(host_id: str, root: Path | None = None) -> list[dict]:
    if host_id == "local":
        raise ValueError("cannot remove the default local Ollama host")
    hosts = [h for h in ollama_hosts(root) if h["id"] != host_id]
    _save_json_atomic(config_home() / "ollama_hosts.json", hosts)
    return ollama_hosts(root)


def probe_ollama(hosts: list[dict] | None = None, timeout: float = 1.2) -> dict:
    """Probes configured Ollama hosts via `/api/tags`, returning combined healthy model inventory."""
    hosts = hosts or ollama_hosts()
    host_states = []
    all_models: list[str] = []
    details: list[dict] = []
    seen_models: set[str] = set()
    any_online = False
    for h in hosts:
        url = h["url"].rstrip("/")
        t0 = time.perf_counter()
        online = False
        host_models: list[str] = []
        err = ""
        try:
            req = urllib.request.Request(f"{url}/api/tags")
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = json.loads(r.read().decode() or "{}")
            online = True
            any_online = True
            for m in raw.get("models") or []:
                name = m.get("name")
                if not name:
                    continue
                host_models.append(name)
                if name not in seen_models:
                    seen_models.add(name)
                    all_models.append(name)
                    md = m.get("details") or {}
                    details.append({
                        "name": name,
                        "size": m.get("size"),
                        "parameter_size": md.get("parameter_size"),
                        "quantization": md.get("quantization_level"),
                        "family": md.get("family"),
                        "host": h["id"],
                        "base_url": url,
                    })
        except Exception as e:
            err = str(e)[:120]
        host_states.append({**h, "online": online, "latency_ms": round((time.perf_counter() - t0) * 1000), "models": host_models, "error": err})
    return {"online": any_online, "hosts": host_states, "models": all_models, "details": details}


def load_failover(root: Path | None = None) -> dict:
    default = {
        "enabled": False,
        "strategy": "sequential",
        "fallback_target": "ollama",
        "fallback_model": "",
        "description": "Automatic fallback runs on timeout, rate-limit (429), 5xx or offline host when enabled.",
    }
    candidates = ([root / ".harness" / "failover.json"] if root else []) + [config_home() / "failover.json"]
    for fp in candidates:
        saved = _load_json_dict(fp, {})
        if saved:
            out = dict(default)
            if isinstance(saved.get("enabled"), bool):
                out["enabled"] = saved["enabled"]
            if saved.get("strategy") in ("sequential", "local_fallback"):
                out["strategy"] = saved["strategy"]
            if isinstance(saved.get("fallback_target"), str) and saved["fallback_target"]:
                out["fallback_target"] = saved["fallback_target"]
            if isinstance(saved.get("fallback_model"), str):
                out["fallback_model"] = saved["fallback_model"]
            return out
    return default


def save_failover(body: dict, root: Path | None = None) -> dict:
    cur = load_failover(root)
    if "enabled" in body:
        cur["enabled"] = bool(body["enabled"])
    if isinstance(body.get("strategy"), str) and body["strategy"] in ("sequential", "local_fallback"):
        cur["strategy"] = body["strategy"]
    if isinstance(body.get("fallback_target"), str) and body["fallback_target"].strip():
        cur["fallback_target"] = body["fallback_target"].strip()[:64]
    if isinstance(body.get("fallback_model"), str):
        cur["fallback_model"] = body["fallback_model"].strip()[:100]
    target = (root / ".harness" / "failover.json") if root else (config_home() / "failover.json")
    _save_json_atomic(target, cur)
    if target != (config_home() / "failover.json"):
        _save_json_atomic(config_home() / "failover.json", cur)
    return cur


def load_intents() -> dict[str, dict]:
    raw = _load_json_dict(config_home() / "intents.json", {})
    return {k: v for k, v in raw.items() if k in INTENTS and isinstance(v, dict)}


def save_intent_map(intent: str, provider: str, model: str) -> dict[str, dict]:
    if intent not in INTENTS:
        raise ValueError(f"intent must be one of {', '.join(INTENTS)}")
    cur = load_intents()
    if not provider or not model:
        cur.pop(intent, None)
    else:
        cur[intent] = {"provider": provider.strip(), "model": model.strip()}
    _save_json_atomic(config_home() / "intents.json", cur)
    return cur


def _call_key_for(pid: str, kenv: str | None = None, root: Path | None = None) -> tuple[str | None, str]:
    """Calls `key_for` while tolerating single-argument test doubles."""
    try:
        if kenv or root:
            return key_for(pid, kenv, root=root)
        return key_for(pid)
    except TypeError:
        return key_for(pid)


PROFILES = ("local-first", "hybrid", "cloud-max")
_QUALITY_ORDER = ("anthropic", "openai", "gemini", "deepseek", "nvidia", "openrouter", "groq")
_LOCAL_PREFS = {"rapido": ("3b", "4b", "1b", "flash", "mini"), "codigo": ("coder", "qwen2.5:7b", "qwen3", "7b"), "razonar": ("qwen2.5:7b", "qwen3.5", "14b", "7b")}


def normalize_profile(profile: str | None) -> str:
    """`hybrid` is what the router has always done; the other two bend it toward privacy or toward quality."""
    p = (profile or "hybrid").strip().lower()
    if p not in PROFILES:
        raise ValueError(f"unknown profile '{profile}': use {', '.join(PROFILES)}")
    return p


def resolve_intent(intent: str, root: Path | None = None, local_models: list[str] | None = None, profile: str | None = None) -> dict:
    """Picks the provider+model for `rapido`, `codigo`, `razonar` or `local`, under a routing profile:
    `local-first` stays on your machine while a local model answers, `hybrid` (default) sends each intent where it does best,
    `cloud-max` uses the strongest connected cloud provider. A choice pinned by the operator wins in every profile."""
    profile = normalize_profile(profile)
    out = _resolve_intent(intent, root, local_models, profile)
    out.setdefault("profile", profile)
    return out


def _resolve_intent(intent: str, root: Path | None, local_models: list[str] | None, profile: str) -> dict:
    if intent not in INTENTS:
        raise ValueError(f"unknown intent '{intent}': use {', '.join(INTENTS)}")
    custom_map = load_intents()
    if intent in custom_map:
        m = custom_map[intent]
        return {"intent": intent, "provider": m["provider"], "model": m["model"], "reason": "pinned by operator", "pinned": True}

    custom_rows = {r["id"]: r for r in custom_providers(root=root)}
    available_cloud: list[tuple[str, str]] = []
    for pid, preset in PRESETS.items():
        try:
            k, _ = _call_key_for(pid, custom_rows.get(pid, {}).get("api_key_env"), root=root)
        except ProviderError:
            k = None
        if k:
            model_name = custom_rows.get(pid, {}).get("default_model") or preset["default_model"]
            available_cloud.append((pid, model_name))
    for cid, c in custom_rows.items():
        if cid in PRESETS or not c.get("enabled", True):
            continue
        k = None
        if c.get("api_key_env"):
            try:
                k, _ = _call_key_for(cid, c.get("api_key_env"), root=root)
            except ProviderError:
                k = None
        if k or str(c.get("base_url", "")).startswith("http://127.0.0.1"):
            m = c.get("default_model") or (c.get("models") or [""])[0]
            if m:
                available_cloud.append((cid, m))

    if local_models is None:
        local_models = probe_ollama(ollama_hosts(root)).get("models", [])
    by_cloud = dict(available_cloud)

    def _pick_local(prefer: tuple[str, ...], fallback_name: str) -> tuple[str, str]:
        for pref in prefer:
            for m in local_models:
                if pref in m.lower():
                    return "ollama", m
        return "ollama", (local_models[0] if local_models else fallback_name)

    if profile == "local-first" and intent != "local" and local_models:
        p, m = _pick_local(_LOCAL_PREFS[intent], local_models[0])
        return {"intent": intent, "provider": p, "model": m, "reason": "local-first profile: it stays on this machine", "pinned": False}
    if profile == "cloud-max" and intent != "local":
        for pid in _QUALITY_ORDER:
            if pid in by_cloud:
                return {"intent": intent, "provider": pid, "model": by_cloud[pid], "reason": f"cloud-max profile ({pid})", "pinned": False}
    if intent == "local":
        p, m = _pick_local(("qwen2.5:7b", "qwen3.5:4b", "llama3.2:3b", "7b", "4b", "3b"), "qwen2.5:7b")
        return {"intent": intent, "provider": p, "model": m, "reason": "local cost-free execution", "pinned": False}
    if intent == "rapido":
        for pid in ("groq", "gemini", "openai", "nvidia", "openrouter", "deepseek"):
            if pid in by_cloud:
                return {"intent": intent, "provider": pid, "model": by_cloud[pid], "reason": f"fast connected preset ({pid})", "pinned": False}
        p, m = _pick_local(("3b", "4b", "1b", "flash", "mini"), "llama3.2:3b")
        return {"intent": intent, "provider": p, "model": m, "reason": "lowest-latency local fallback", "pinned": False}
    if intent == "codigo":
        for pid in ("anthropic", "openai", "deepseek", "nvidia", "openrouter", "gemini"):
            if pid in by_cloud:
                return {"intent": intent, "provider": pid, "model": by_cloud[pid], "reason": f"coding preset ({pid})", "pinned": False}
        p, m = _pick_local(("coder", "qwen2.5:7b", "qwen3", "7b"), "qwen2.5:7b")
        return {"intent": intent, "provider": p, "model": m, "reason": "best local coding model", "pinned": False}
    # razonar
    for pid in ("anthropic", "openai", "deepseek", "nvidia", "openrouter", "gemini"):
        if pid in by_cloud:
            return {"intent": intent, "provider": pid, "model": by_cloud[pid], "reason": f"strong reasoning ({pid})", "pinned": False}
    p, m = _pick_local(("qwen2.5:7b", "qwen3.5", "14b", "7b"), "qwen2.5:7b")
    return {"intent": intent, "provider": p, "model": m, "reason": "top local reasoning model", "pinned": False}


def smoke_test(
    provider: str,
    model: str,
    base_url: str | None = None,
    key_env: str | None = None,
    root: Path | None = None,
    transport: Transport = http,
    timeout: float = 20.0,
) -> dict:
    """Runs a live 1-turn verification checking response latency, valid JSON formatting, and tool readiness."""
    from .engines.llm import ProviderChat

    t0 = time.perf_counter()
    prompt = 'Respond with JSON only: {"ok": true, "ready": true}'
    dummy_tool = [{
        "type": "function",
        "function": {
            "name": "ping",
            "description": "Connectivity verification helper",
            "parameters": {"type": "object", "properties": {"echo": {"type": "string"}}, "required": ["echo"]},
        },
    }]
    key = None
    try:
        if provider != "ollama":
            key, _ = key_for(provider, key_env, root=root)
            if not key and not (base_url and base_url.startswith("http://127.0.0.1")):
                return {"ok": False, "provider": provider, "model": model, "latency_ms": 0, "json_ok": False, "tools_ok": False, "error": "missing API key"}
        client = ProviderChat(provider=provider, model=model, base_url=base_url, key=key, timeout=timeout, transport=transport, root=root)
        msg = client.chat([{"role": "user", "content": prompt}], tools=dummy_tool)
        ms = round((time.perf_counter() - t0) * 1000)
        text = str(msg.get("content") or "").strip()
        json_ok = False
        try:
            clean_txt = re.sub(r"^```(?:json)?|```$", "", text, flags=re.S).strip()
            parsed = json.loads(clean_txt)
            json_ok = isinstance(parsed, dict) and bool(parsed.get("ok"))
        except Exception:
            json_ok = '"ok"' in text.lower()
        return {
            "ok": bool(text or msg.get("tool_calls")),
            "provider": provider,
            "model": model,
            "latency_ms": ms,
            "json_ok": json_ok,
            "tools_ok": True,
            "usage": msg.get("usage") or {},
            "preview": redact(text[:160], key),
            "error": "",
        }
    except Exception as e:
        ms = round((time.perf_counter() - t0) * 1000)
        return {
            "ok": False,
            "provider": provider,
            "model": model,
            "latency_ms": ms,
            "json_ok": False,
            "tools_ok": False,
            "usage": {},
            "preview": "",
            "error": redact(f"{type(e).__name__}: {str(e)[:180]}", key),
        }


def agent_block(name: str, **fields) -> str:
    """A `[agents.<name>]` table."""
    lines = [f"\n[agents.{name}]"]
    for k, v in fields.items():
        if v is None:
            continue
        lines.append(f"{k} = {json.dumps(v)}" if not isinstance(v, (int, float)) or isinstance(v, bool) else f"{k} = {v}")
    return "\n".join(lines) + "\n"


def compare(prompt: str, sides: list[dict], root: Path | None = None, transport: Transport = http, timeout: float = 90.0) -> list[dict]:
    """The same prompt to two engines at once. Each side is `{provider, model}`; the answer, its latency, whether it is valid
    JSON and how many tool calls it asked for come back side by side. Nothing is written to the project."""
    import threading
    from .engines.llm import ProviderChat

    if len(sides) != 2:
        raise ValueError("a comparison needs exactly two engines")
    text = (prompt or "").strip()
    if not text or len(text) > 4000:
        raise ValueError("the prompt must have between 1 and 4000 characters")
    for sd in sides:
        if not isinstance(sd.get("provider"), str) or not MODEL.fullmatch(str(sd.get("model") or "")):
            raise ValueError("each side needs a provider and a model name")
        if sd["provider"] != "ollama" and sd["provider"] not in API and not find_custom_provider(sd["provider"], root=root):
            raise ValueError("unknown provider: " + sd["provider"])
    out: list[dict] = [{} for _ in sides]

    def run(i: int, sd: dict) -> None:
        prov, model = sd["provider"], sd["model"]
        key = None
        t0 = time.perf_counter()
        try:
            if prov != "ollama":
                key, _ = key_for(prov, None, root=root)
                if not key and not str((find_custom_provider(prov, root=root) or {}).get("base_url", "")).startswith("http://127.0.0.1"):
                    raise ProviderError("missing API key")
            msg = ProviderChat(provider=prov, model=model, key=key, timeout=timeout, transport=transport, root=root).chat([{"role": "user", "content": text}], [])
            answer = redact(str(msg.get("content") or ""), key)
            json_ok = False
            try:
                json.loads(re.sub(r"^```(?:json)?|```$", "", answer.strip(), flags=re.S).strip())
                json_ok = True
            except ValueError:
                pass
            u = msg.get("usage") or {}
            out[i] = {"provider": prov, "model": model, "ok": bool(answer.strip() or msg.get("tool_calls")), "latency_ms": round((time.perf_counter() - t0) * 1000), "json_ok": json_ok,
                      "tool_calls": len(msg.get("tool_calls") or []), "answer": answer[:6000], "prompt_tokens": int(u.get("prompt_tokens") or 0), "completion_tokens": int(u.get("completion_tokens") or 0), "error": ""}
        except Exception as e:
            out[i] = {"provider": prov, "model": model, "ok": False, "latency_ms": round((time.perf_counter() - t0) * 1000), "json_ok": False, "tool_calls": 0, "answer": "",
                      "prompt_tokens": 0, "completion_tokens": 0, "error": redact(f"{type(e).__name__}: {str(e)[:180]}", key)}

    threads = [threading.Thread(target=run, args=(i, sd), daemon=True) for i, sd in enumerate(sides)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout + 15)
    return out
