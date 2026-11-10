"""Cola de revisión persistente (SQLite): las escaladas no se pierden y vuelven al conjunto de referencia."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """CREATE TABLE IF NOT EXISTS review_queue (
  id TEXT PRIMARY KEY, text TEXT, reason TEXT, candidate_label TEXT,
  created_at REAL, resolved_label TEXT, reviewer TEXT, resolved_at REAL)"""


class ReviewQueue:
    def __init__(self, path: str | Path = ":memory:"):
        self.db = sqlite3.connect(str(path))
        self.db.execute(SCHEMA)

    def add(self, outcome, text: str) -> bool:
        """Idempotente: reenviar el mismo id no duplica (INSERT OR IGNORE)."""
        cur = self.db.execute("INSERT OR IGNORE INTO review_queue(id,text,reason,candidate_label,created_at) VALUES (?,?,?,?,?)",
                              (outcome.id, text, outcome.reason, outcome.label, time.time()))
        self.db.commit()
        return cur.rowcount == 1

    def pending(self) -> list[dict]:
        cur = self.db.execute("SELECT id,text,reason,candidate_label,created_at FROM review_queue WHERE resolved_label IS NULL ORDER BY created_at")
        return [dict(zip(("id", "text", "reason", "candidate_label", "created_at"), r)) for r in cur]

    def resolve(self, rid: str, label: str, reviewer: str) -> None:
        if label not in {"billing", "bug", "access", "other"}:
            raise ValueError("etiqueta inválida")
        n = self.db.execute("UPDATE review_queue SET resolved_label=?, reviewer=?, resolved_at=? WHERE id=? AND resolved_label IS NULL",
                            (label, reviewer, time.time(), rid)).rowcount
        self.db.commit()
        if n == 0:
            raise KeyError(f"{rid}: no existe o ya estaba resuelto")

    def stats(self) -> dict:
        tot, res = self.db.execute("SELECT COUNT(*), SUM(resolved_label IS NOT NULL) FROM review_queue").fetchone()
        by = dict(self.db.execute("SELECT reason, COUNT(*) FROM review_queue GROUP BY reason").fetchall())
        agree = self.db.execute("SELECT COUNT(*) FROM review_queue WHERE resolved_label IS NOT NULL AND resolved_label=candidate_label").fetchone()[0]
        return {"total": tot, "resolved": res or 0, "pending": tot - (res or 0), "by_reason": by, "reviewer_agrees_with_candidate": agree}

    def export_golden(self, path: str | Path) -> int:
        """Los casos resueltos por una persona pasan a ser datos de referencia nuevos (bucle de mejora)."""
        rows = self.db.execute("SELECT id,text,resolved_label FROM review_queue WHERE resolved_label IS NOT NULL").fetchall()
        with open(path, "a", encoding="utf-8") as f:
            for rid, text, lab in rows:
                f.write(json.dumps({"id": f"rq-{rid}", "text": text, "label": lab, "expect": "classify", "kind": "from-review", "split": "dev"}, ensure_ascii=False) + "\n")
        return len(rows)
