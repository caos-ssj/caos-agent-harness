"""The same agent as `native.run_agent`, orchestrated as a LangGraph state graph.

    model ──tool calls──▶ tools ──▶ model …      model ──no tool calls──▶ judge ──▶ END

The policy guard, the budgets and the citation and relevance checks are the same functions the native
engine uses, so the two engines can be evaluated on the same tasks and compared like for like.
"""
from __future__ import annotations

import time
from typing import TypedDict

from langgraph.graph import END, StateGraph

from ..policy.guard import Policy
from .native import SYSTEM, Result, exec_tool, judge_final


class State(TypedDict):
    msgs: list
    res: Result
    seen: str
    scores: dict
    final: str | None   # content of the model's final message, once it stops calling tools
    stop: bool          # a budget ran out or the model failed


def build_graph(session, llm, tools: list[dict], policy: Policy, t0: float):
    async def model(state: State) -> dict:
        res = state["res"]
        if res.steps >= policy.max_steps:
            res.status, res.reason = "budget_exhausted", "steps"
            return {"stop": True}
        res.steps += 1
        if time.perf_counter() - t0 > policy.wall_seconds:
            res.status, res.reason = "budget_exhausted", "wall_time"
            return {"stop": True}
        try:
            msg = llm.chat(state["msgs"], tools)
        except Exception as e:  # a model failure ends the run with a reason, it does not crash the harness
            res.status, res.reason = "error", f"llm:{type(e).__name__}"
            return {"stop": True}
        out = {"msgs": state["msgs"] + [msg]}
        if not (msg.get("tool_calls") or []):
            out["final"] = msg.get("content", "")
        return out

    async def run_tools(state: State) -> dict:
        res, msgs, seen = state["res"], list(state["msgs"]), state["seen"]
        for c in msgs[-1].get("tool_calls") or []:
            if len(res.tool_calls) >= policy.max_tool_calls:
                res.status, res.reason = "budget_exhausted", "tool_calls"
                return {"stop": True}
            content, new_seen = await exec_tool(session, policy, c, res, state["scores"])
            seen += new_seen
            msgs.append({"role": "tool", "tool_name": c["function"]["name"], "content": content})
        return {"msgs": msgs, "seen": seen}

    async def judge(state: State) -> dict:
        judge_final(state["res"], state["final"] or "", state["seen"], state["scores"], policy)
        return {}

    def after_model(state: State) -> str:
        if state["stop"]:
            return END
        return "judge" if state["final"] is not None else "tools"

    g = StateGraph(State)
    g.add_node("model", model)
    g.add_node("tools", run_tools)
    g.add_node("judge", judge)
    g.set_entry_point("model")
    g.add_conditional_edges("model", after_model, {"tools": "tools", "judge": "judge", END: END})
    g.add_conditional_edges("tools", lambda s: END if s["stop"] else "model", {"model": "model", END: END})
    g.add_edge("judge", END)
    return g.compile()


async def run_agent(question: str, session, llm, tools: list[dict], policy: Policy | None = None) -> Result:
    policy = policy or Policy()
    t0 = time.perf_counter()
    res = Result(status="error")
    graph = build_graph(session, llm, tools, policy, t0)
    state: State = {"msgs": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}],
                    "res": res, "seen": "", "scores": {}, "final": None, "stop": False}
    await graph.ainvoke(state, {"recursion_limit": 2 * policy.max_steps + 6})
    res.seconds = round(time.perf_counter() - t0, 2)
    return res
