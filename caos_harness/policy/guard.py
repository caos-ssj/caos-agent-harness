"""Capa de política entre el modelo y las herramientas MCP: lista blanca, validación de argumentos y límites."""
from __future__ import annotations

import posixpath
from dataclasses import dataclass, field

ALLOWED_TOOLS = {"buscar_notas", "leer_nota", "buscar_pares"}
NOTE_PREFIX = "conocimiento/"


class Blocked(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Policy:
    max_steps: int = 5
    max_tool_calls: int = 6
    wall_seconds: float = 240.0
    max_result_chars: int = 3000
    min_relevance: float = 1.01  # calibrado aparte con agent/calibrate.py; una cita con menos puntos, o sin puntos, no se entrega
    allowed: set = field(default_factory=lambda: set(ALLOWED_TOOLS))

    def check(self, name: str, args: dict) -> dict:
        if name not in self.allowed:
            raise Blocked(f"tool_not_allowed:{name}")
        if not isinstance(args, dict):
            raise Blocked("args_not_object")
        args = dict(args)
        if name == "leer_nota":
            ruta = args.get("ruta")
            if not isinstance(ruta, str) or not ruta:
                raise Blocked("missing_path")
            norm = posixpath.normpath(ruta.replace("\\", "/"))
            if ".." in ruta.split("/") or ruta.startswith(("/", "~")) or not norm.startswith(NOTE_PREFIX):
                raise Blocked(f"path_outside_notes:{ruta[:60]}")
        if name in ("buscar_notas", "buscar_pares"):
            q = args.get("pregunta")
            if not isinstance(q, str) or not q.strip():
                raise Blocked("missing_question")
            if "n" in args:
                try:
                    args["n"] = max(1, min(10, int(args["n"])))
                except (TypeError, ValueError):
                    raise Blocked("bad_n")
        return args
