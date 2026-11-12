"""Modular domain handlers for providers, intents, metrics, skills/MCP tools and Share Pack/Drive."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from .. import app, doctor, mcp_tools, metrics, providers, share, skills


def _safe_key_for(pid: str, kenv: str | None, root: Path, default_env: str | None = None) -> tuple[str | None, str]:
    """Calls `providers.key_for` while staying compatible with single-argument test doubles."""
    try:
        if kenv and kenv != default_env:
            return providers.key_for(pid, kenv, root=root)
        return providers.key_for(pid, kenv, root=root) if kenv else providers.key_for(pid)
    except TypeError:
        return providers.key_for(pid)


def providers_payload(project: app.Project, transport, profile: str | None = None) -> dict:
    """Builds the unified Providers, Ollama multi-host, Presets, Intents, Failover and CLI summary."""
    root = project.root
    hosts = providers.ollama_hosts(root)
    ollama_state = providers.probe_ollama(hosts)
    models = ollama_state["models"]
    default_ol = "qwen2.5:7b" if "qwen2.5:7b" in models else (models[0] if models else "")

    items: list[dict] = [
        {
            "id": "ollama",
            "name": "Ollama (Local & Hosts)",
            "type": "local",
            "status": "online" if ollama_state["online"] else "offline",
            "wired": True,
            "quota": f"{len([h for h in ollama_state['hosts'] if h['online']])}/{len(hosts)} hosts",
            "cost_per_m": "local compute",
            "models": models,
            "model_details": ollama_state["details"],
            "default_model": default_ol,
            "base_url": hosts[0]["url"] if hosts else providers.default_ollama_url(),
            "description": "Local or remote LAN/Tailscale Ollama hosts.",
            "is_fallback": True,
        }
    ]

    custom_rows = {c["id"]: c for c in providers.custom_providers(root=root)}
    for pid, spec in providers.API.items():
        override = custom_rows.get(pid) or {}
        kenv = override.get("api_key_env") or spec["env"]
        try:
            key, where = _safe_key_for(pid, kenv, root, default_env=spec["env"])
            p_status = "key_present" if key else "missing_key"
            key_error = None
            masked = providers.mask_key(key)
        except providers.ProviderError as e:
            where, p_status, key_error, masked = "error", "invalid_key", str(e), ""
        entry = {
            "id": pid,
            "name": spec["name"],
            "type": "cloud",
            "status": p_status,
            "wired": True,
            "quota": "env / keyring" if p_status == "key_present" else "key required",
            "cost_per_m": "not measured",
            "models": override.get("models") or [],
            "default_model": override.get("default_model") or spec.get("default_model", ""),
            "base_url": override.get("base_url") or spec.get("base_url", ""),
            "api_key_env": kenv,
            "key_source": where,
            "key_masked": masked,
            "description": spec.get("description", ""),
            "free_models": list(spec.get("free_models") or []),
            "tier_hint": spec.get("tier_hint", ""),
        }
        if key_error:
            entry["key_error"] = key_error
        items.append(entry)

    for cid, cp in custom_rows.items():
        if cid in providers.API:
            continue
        kenv = cp.get("api_key_env")
        key, where, err = None, "none", None
        try:
            key, where = _safe_key_for(cid, kenv, root)
        except providers.ProviderError as e:
            err = str(e)
        local_url = str(cp.get("base_url", "")).startswith("http://127.0.0.1")
        st = "invalid_key" if err else ("ready" if (key or local_url) else "missing_key")
        entry = {
            **cp,
            "type": "custom",
            "wired": True,
            "quota": "custom endpoint",
            "cost_per_m": "not measured",
            "status": st,
            "key_source": where,
            "key_masked": providers.mask_key(key),
        }
        if err:
            entry["key_error"] = err
        items.append(entry)

    failover = providers.load_failover(root)
    try:
        intents = {intent: providers.resolve_intent(intent, root=root, local_models=models, profile=profile) for intent in providers.INTENTS}
    except ValueError as e:
        raise app.ConfigError(str(e)) from e
    used = {tuple(a.command) for a in project.agents.values() if a.command}
    binaries = {a.command[0] for a in project.agents.values() if a.command}   # an agent with the same binary and another model counts too
    clis = [{**c, "added": tuple(providers.CLIS[c["id"]]["command"]) in used or providers.CLIS[c["id"]]["bin"] in binaries} for c in providers.detect_clis()]
    api_agents = [{"name": a.name, "provider": a.provider, "model": a.model} for a in project.agents.values() if a.provider]
    return {
        "providers": items,
        "ollama_hosts": ollama_state["hosts"],
        "intents": intents,
        "active_failover": failover,
        "clis": clis,
        "api_agents": api_agents,
    }


def _probe_target(project: app.Project, pid: str, body: dict) -> tuple[str | None, str | None]:
    """The address and key variable a test request names, after refusing the ones it has no business naming."""
    base_url = str(body.get("base_url") or "").strip() or None
    key_env = str(body.get("key_env") or "").strip() or None
    try:
        providers.check_probe_target(pid, base_url, key_env, root=project.root)
    except ValueError as e:
        raise app.ConfigError(str(e)) from e
    return base_url, key_env


def provider_test(project: app.Project, body: dict, transport) -> dict:
    pid = str(body.get("id") or "").strip()
    if pid == "ollama":
        url = str(body.get("base_url") or "").strip()
        if url:
            try:
                url = providers.safe_base_url(url)
            except ValueError as e:
                raise app.ConfigError(str(e)) from e
        hosts = [{"id": "custom", "label": url, "url": url}] if url else providers.ollama_hosts(project.root)
        probe = providers.probe_ollama(hosts)
        first = probe["hosts"][0] if probe["hosts"] else {"online": False, "latency_ms": 0, "error": "no host"}
        return {
            "ok": probe["online"],
            "models": probe["models"],
            "latency_ms": first.get("latency_ms", 0),
            "source": first.get("url", "localhost"),
            "message": f"connected ({len(probe['models'])} local models)" if probe["online"] else (first.get("error") or "Ollama offline"),
        }
    if pid not in providers.API and not providers.find_custom_provider(pid, root=project.root):
        raise app.ConfigError("unknown provider id: " + pid)
    base_url, key_env = _probe_target(project, pid, body)
    return providers.test(pid, key_env=key_env, transport=transport, base_url=base_url, root=project.root)


def provider_smoke(project: app.Project, body: dict, transport) -> dict:
    pid = str(body.get("provider") or body.get("id") or "ollama").strip()
    mod = str(body.get("model") or "").strip()
    if not mod:
        if pid == "ollama":
            mods = providers.probe_ollama(providers.ollama_hosts(project.root)).get("models") or []
            mod = mods[0] if mods else "qwen2.5:7b"
        elif pid in providers.PRESETS:
            mod = providers.PRESETS[pid]["default_model"]
        else:
            cp = providers.find_custom_provider(pid, root=project.root)
            mod = (cp or {}).get("default_model") or ""
    if not mod:
        raise app.ConfigError("model name is required for smoke test")
    base_url, key_env = _probe_target(project, pid, body) if pid != "ollama" else (None, None)
    res = providers.smoke_test(pid, mod, base_url=base_url, key_env=key_env, root=project.root, transport=transport)
    metrics.record_run(
        project.root,
        pid,
        mod,
        res.get("latency_ms") or 0,
        bool(res.get("ok")),
        prompt_tokens=int((res.get("usage") or {}).get("prompt_tokens") or 0),
        completion_tokens=int((res.get("usage") or {}).get("completion_tokens") or 0),
        kind="smoke",
        json_ok=res.get("json_ok"),
        tools_ok=res.get("tools_ok"),
        error=res.get("error") or "",
    )
    return res


def provider_save_key(project: app.Project, body: dict) -> dict:
    pid = str(body.get("provider") or body.get("id") or "").strip()
    secret = str(body.get("secret") or "")
    env_name = body.get("env_name")
    storage = str(body.get("storage") or "auto")
    if not pid:
        raise app.ConfigError("provider id is required")
    try:
        return providers.save_key(pid, secret, env_name=env_name, storage=storage, root=project.root)
    except ValueError as e:
        raise app.ConfigError(str(e)) from e


def save_provider_entry(project: app.Project, body: dict) -> dict:
    try:
        scope = "project" if body.get("scope") == "project" else "global"
        return providers.save_custom_provider(body, root=project.root, scope=scope)
    except ValueError as e:
        msg = str(e)
        if "keys are not stored" in msg:
            raise app.ConfigError("keys are not stored: export the key in your shell or save it to keyring/.env.local") from e
        raise app.ConfigError(msg) from e


def save_failover_cfg(project: app.Project, body: dict) -> dict:
    return providers.save_failover(body, root=project.root)


def save_ollama_host(project: app.Project, body: dict) -> dict:
    try:
        if body.get("remove") and body.get("id"):
            hosts = providers.remove_ollama_host(str(body["id"]), root=project.root)
        else:
            hosts = providers.save_ollama_host(str(body.get("url") or ""), str(body.get("label") or ""), body.get("id"), root=project.root)
        return {"hosts": hosts, "probe": providers.probe_ollama(hosts)}
    except ValueError as e:
        raise app.ConfigError(str(e)) from e


def save_intent_override(project: app.Project, body: dict) -> dict:
    intent = str(body.get("intent") or "")
    provider = str(body.get("provider") or "")
    model = str(body.get("model") or "")
    try:
        providers.save_intent_map(intent, provider, model)
        return {i: providers.resolve_intent(i, root=project.root) for i in providers.INTENTS}
    except ValueError as e:
        raise app.ConfigError(str(e)) from e


def metrics_payload(project: app.Project, scope: str, reports_dir: Path) -> dict:
    return metrics.snapshot(project, scope=scope, reports_dir=reports_dir)


def metrics_demote(project: app.Project, body: dict) -> dict:
    """Degrade or restore a model. The provider travels with it: a cloud model that shares a name with a local one is a different system."""
    try:
        model = str(body.get("model") or body.get("system") or "").strip()
        provider = str(body.get("provider") or "").strip() or None
        demotions = metrics.set_demotion(project.root, metrics.demotion_key(provider, model), bool(body.get("demoted", True)), str(body.get("reason") or "Degraded from Metrics"))
        return {"ok": True, "key": metrics.demotion_key(provider, model), "demotions": demotions}
    except ValueError as e:
        raise app.ConfigError(str(e)) from e


def metrics_series(project: app.Project, scope: str, bucket: str) -> dict:
    try:
        return metrics.series(project, scope, bucket)
    except ValueError as e:
        raise app.ConfigError(str(e)) from e


def providers_compare(project: app.Project, body: dict, transport) -> dict:
    """Runs one prompt against two engines. A cloud side costs quota, so the caller must have confirmed it, and the server checks."""
    sides = body.get("sides")
    if not isinstance(sides, list) or len(sides) != 2 or not all(isinstance(x, dict) for x in sides):
        raise app.ConfigError("give two engines to compare")
    cloud = [f"{x.get('provider')} · {x.get('model')}" for x in sides if x.get("provider") != "ollama"]
    if cloud and body.get("confirm_cloud") is not True:
        raise app.ConfigError("this comparison uses cloud quota (" + ", ".join(cloud) + "): confirm it to run")
    try:
        results = providers.compare(str(body.get("prompt") or ""), sides, root=project.root, transport=transport)
    except ValueError as e:
        raise app.ConfigError(str(e)) from e
    for r in results:   # logged apart from real work: it never counts toward the success rate
        metrics.record_run(project.root, r["provider"], r["model"], r["latency_ms"], r["ok"], prompt_tokens=r["prompt_tokens"], completion_tokens=r["completion_tokens"], kind="compare", json_ok=r["json_ok"], error=r["error"])
    return {"results": results, "cloud": bool(cloud), "prompt_chars": len(str(body.get("prompt") or ""))}


def clone_skill(project: app.Project, body: dict) -> dict:
    try:
        sk = skills.clone_to_project(project.root, str(body.get("name") or ""))
    except ValueError as e:
        raise app.ConfigError(str(e)) from e
    return {"name": sk.name, "description": sk.description, "local": sk.local, "category": sk.category, "team_shareable": sk.team_shareable, "body": sk.body}


def save_skill(project: app.Project, body: dict) -> dict:
    try:
        sk = skills.save_local_skill(
            project.root,
            str(body.get("name") or ""),
            str(body.get("description") or ""),
            str(body.get("body") or ""),
            str(body.get("category") or "Proyecto"),
        )
        return {"name": sk.name, "description": sk.description, "local": sk.local, "category": sk.category, "team_shareable": sk.team_shareable, "body": sk.body}
    except ValueError as e:
        raise app.ConfigError(str(e)) from e


def tools_payload(project: app.Project) -> dict:
    return {"tools": mcp_tools.discover_tools(project.root)}


def share_doctor(project: app.Project, body: dict) -> dict:
    files = body.get("files") if isinstance(body.get("files"), list) else None
    return share.doctor(project.root, files=files)


def _pack_options(body: dict) -> dict:
    files = body.get("files") if isinstance(body.get("files"), list) else None
    try:
        fmt = share.normalize_format(body.get("format"))
    except ValueError as e:
        raise app.ConfigError(str(e)) from e
    return {
        "include_code": bool(body.get("include_code", True)),
        "include_docs": bool(body.get("include_docs", True)),
        "include_skills": bool(body.get("include_skills", True)),
        "fmt": fmt,
        "selected_files": files,
    }


def share_pack(project: app.Project, body: dict) -> dict:
    return share.build_share_pack(project.root, **_pack_options(body))


def share_preview(project: app.Project, body: dict) -> dict:
    return share.preview_share_pack(project.root, **_pack_options(body))


def preflight(project: app.Project, dry_run: bool = False) -> dict:
    return doctor.preflight(project, dry_run=dry_run)


def share_upload(project: app.Project, body: dict) -> dict:
    rel = str(body.get("path") or "").strip()
    if not rel:
        raise app.ConfigError("pack path is required")
    target = (project.root / rel).resolve() if not Path(rel).is_absolute() else Path(rel).resolve()
    exports_root = (project.root / ".harness" / "exports").resolve()
    if exports_root not in target.parents and project.root.resolve() not in target.parents:
        raise app.ConfigError("file must reside inside the workspace exports folder")
    return share.upload_gdrive(target, parent_id=body.get("parent_id"))


def share_exports_list(project: app.Project) -> dict:
    exp = project.root / ".harness" / "exports"
    items = []
    if exp.is_dir():
        for p in sorted(exp.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)[:12]:
            items.append({"filename": p.name, "relative_path": p.relative_to(project.root).as_posix(), "is_dir": p.is_dir(), "size_bytes": p.stat().st_size if p.is_file() else 0, "mtime": p.stat().st_mtime})
    gd = shutil.which("gdrive") is not None
    return {"exports": items, "gdrive_connected": gd}
