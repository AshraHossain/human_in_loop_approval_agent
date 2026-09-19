"""AgentExecutor flavour of the HITL approval agent.

Relative imports mean this must run as a module from the parent directory,
not as a bare script:

    uv run -m agent_executor_version.main --self-check
    uv run -m agent_executor_version.main "maybe ship the release"

`AgentExecutor` left `langchain.agents` in langchain 1.0; it lives in
`langchain-classic` now. Kept deliberately -- this variant exists to contrast
AgentExecutor against the LangGraph version, and langchain 1.x `create_agent`
is LangGraph underneath, which would erase that contrast.
"""

from __future__ import annotations

import json
import os
import sys

from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import Tool
from langchain_openai import ChatOpenAI

from .audit import make_audit
from .hitl_tool import hitl_check

SYSTEM_PROMPT = """You are a Human-in-the-Loop Approval Agent.

Always call hitl_check first, passing the user's request verbatim.
If it returns HUMAN_APPROVAL_REQUIRED, STOP: report the audit record and the
clarifying questions, and take no further action until a human answers.
If it returns OK, proceed and state what you would do.
"""


def _hitl_check_tool(input_text: str) -> str:
    """Tool wrapper: the executor needs a string back, hitl_check returns a dict."""
    return json.dumps(hitl_check(input_text), default=str)


def build_agent(model: str = "gpt-4o") -> AgentExecutor:
    """Build the executor.

    Lazy on purpose -- constructing ChatOpenAI at import time raises without
    OPENAI_API_KEY, which made this module unimportable for tests.
    """
    llm = ChatOpenAI(model=model, temperature=0)
    tools = [
        Tool(
            name="hitl_check",
            func=_hitl_check_tool,
            description=(
                "Detect uncertainty in a request and decide whether human "
                "approval is required. Input: the raw request text. Returns "
                "JSON with 'status', an 'audit' record, and any 'questions'."
            ),
        )
    ]
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("human", "{input}"),
            ("placeholder", "{agent_scratchpad}"),
        ]
    )
    return AgentExecutor(
        agent=create_tool_calling_agent(llm, tools, prompt),
        tools=tools,
        verbose=True,
    )


def run(request: str) -> dict:
    """Run one request through the agent, returning its result plus an audit record."""
    result = build_agent().invoke({"input": request})
    gate = json.loads(_hitl_check_tool(request))
    return {
        "result": result,
        "audit": make_audit(
            stage="awaiting_human" if gate["status"] == "HUMAN_APPROVAL_REQUIRED" else "completed",
            input_summary=request,
            confidence="low" if gate["status"] == "HUMAN_APPROVAL_REQUIRED" else "high",
            risk_assessment=gate["audit"]["risk_assessment"],
            human_required=gate["status"] == "HUMAN_APPROVAL_REQUIRED",
            actions_taken=["hitl_check"],
        ),
    }


def _self_check() -> None:
    """Offline proof: gate logic and executor wiring. Makes no API call."""
    gated = json.loads(_hitl_check_tool("maybe ship it"))
    assert gated["status"] == "HUMAN_APPROVAL_REQUIRED", gated
    assert gated["questions"], "gated requests must carry clarifying questions"

    clear = json.loads(_hitl_check_tool("ship release 1.2"))
    assert clear["status"] == "OK", clear

    os.environ.setdefault("OPENAI_API_KEY", "sk-self-check-not-a-real-key")
    assert isinstance(build_agent(), AgentExecutor)
    print("self-check OK")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "--self-check":
        _self_check()
    else:
        print(json.dumps(run(" ".join(args)), indent=2, default=str))
