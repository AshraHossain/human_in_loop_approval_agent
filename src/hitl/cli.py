"""CLI for the HITL approval agent.

    hitl submit "transition P-1 to Done"   -> runs until the gate, then EXITS
    hitl approve <request_id> --as <who>   -> resumes from the checkpoint
    hitl deny    <request_id> --as <who>
    hitl audit   <request_id>
    hitl users   add <who> --level lead    -> who may approve, and up to what tier

Approvers come from `<home>/identities.json`. No file means no approvers, so a
fresh install approves nothing until someone is added -- the safe direction to
fail in.

`--seed` exists so the FakeJira backing this CLI has issues to act on until
`RovoJira` is bound (Task 7).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict
from pathlib import Path

from langgraph.types import Command

from hitl.audit import append_audit, new_request_id, verify_chain
from hitl.graph import build_graph, checkpointer_for
from hitl.identity import FileIdentityProvider
from hitl.jira import FakeJira
from hitl.policy import Action

LEVELS = ("junior", "senior", "lead")

_TRANSITION = re.compile(r"^transition\s+(\S+)\s+to\s+(.+)$", re.IGNORECASE)
_COMMENT = re.compile(r"^comment\s+(\S+)\s+(.+)$", re.IGNORECASE)
_CREATE = re.compile(r"^create\s+(.+)$", re.IGNORECASE)


def parse_action(text: str) -> Action:
    text = text.strip()
    if m := _TRANSITION.match(text):
        return Action(
            kind="transition", issue_key=m.group(1), target_status=m.group(2).strip()
        )
    if m := _COMMENT.match(text):
        return Action(kind="add_comment", issue_key=m.group(1), body=m.group(2).strip())
    if m := _CREATE.match(text):
        return Action(kind="create_issue", body=m.group(1).strip())
    raise ValueError(f"cannot parse action from: {text!r}")


def _jira(seed: list[str] | None) -> FakeJira:
    existing: dict[str, str] = {}
    for item in seed or []:
        key, _, status = item.partition("=")
        existing[key] = status or "To Do"
    return FakeJira(existing=existing)


def _emit(state: dict, home: Path) -> None:
    """Append only records not already on disk.

    On resume, state["audits"] carries the whole accumulated trail (the field
    is `operator.add`), including records written by the submit process. A
    duplicated audit record is a corrupt trail, so dedupe on the identity of
    the record itself.
    """
    seen = set()
    for f in sorted((home / "audit").glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            seen.add((r["request_id"], r["timestamp"], r["stage"]))

    for record in state.get("audits", []):
        if (record["request_id"], record["timestamp"], record["stage"]) in seen:
            continue
        append_audit(record, home / "audit")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="hitl")
    p.add_argument("--home", default=".hitl", type=Path)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("submit")
    s.add_argument("request")
    s.add_argument("--seed", action="append")

    for name in ("approve", "deny"):
        d = sub.add_parser(name)
        d.add_argument("request_id")
        d.add_argument("--as", dest="human_id", required=True)
        d.add_argument("--seed", action="append")

    a = sub.add_parser("audit")
    a.add_argument("request_id")

    sub.add_parser("verify")

    u = sub.add_parser("users")
    usub = u.add_subparsers(dest="users_cmd", required=True)
    ua = usub.add_parser("add")
    ua.add_argument("user_id")
    ua.add_argument("--level", required=True, choices=LEVELS)
    ur = usub.add_parser("rm")
    ur.add_argument("user_id")
    usub.add_parser("list")

    args = p.parse_args(argv)
    home: Path = args.home
    db = home / "checkpoints.sqlite"
    identities_path = home / "identities.json"

    if args.cmd == "users":
        users = (
            json.loads(identities_path.read_text(encoding="utf-8"))
            if identities_path.exists()
            else {}
        )
        if args.users_cmd == "list":
            for user_id, level in sorted(users.items()):
                print(f"{user_id}: {level}")
            return 0
        if args.users_cmd == "add":
            users[args.user_id] = args.level
        elif args.user_id not in users:
            print(f"no such user: {args.user_id}")
            return 1
        else:
            del users[args.user_id]
        identities_path.parent.mkdir(parents=True, exist_ok=True)
        identities_path.write_text(json.dumps(users, indent=2) + "\n", encoding="utf-8")
        print(f"{args.users_cmd}: {args.user_id}")
        return 0

    if args.cmd == "verify":
        problems = verify_chain(home / "audit")
        if problems:
            print(f"AUDIT TRAIL COMPROMISED ({len(problems)} problem(s))")
            for problem in problems:
                print(f"  {problem}")
            return 1
        print("audit trail intact")
        return 0

    if args.cmd == "audit":
        found = []
        for f in sorted((home / "audit").glob("*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                if json.loads(line)["request_id"] == args.request_id:
                    found.append(line)
        if not found:
            print(f"no audit records for {args.request_id}")
            return 1
        print("\n".join(found))
        return 0

    jira = _jira(args.seed)
    cfg_id = args.request_id if args.cmd != "submit" else new_request_id()
    cfg = {"configurable": {"thread_id": cfg_id}}

    with checkpointer_for(db) as cp:
        app = build_graph(jira, cp, FileIdentityProvider(identities_path))
        if args.cmd == "submit":
            try:
                action = parse_action(args.request)
            except ValueError as exc:
                print(str(exc))
                return 2
            state = app.invoke(
                {"request": args.request, "request_id": cfg_id, "action": asdict(action)}, cfg
            )
        else:
            decision = "approve" if args.cmd == "approve" else "deny"
            state = app.invoke(
                Command(resume={"decision": decision, "human_id": args.human_id}), cfg
            )

    _emit(state, home)

    if "__interrupt__" in state:
        print("APPROVAL REQUIRED")
        print(f"  request_id {cfg_id}")
        print(f"  approve with: hitl approve {cfg_id} --as <your-id>")
        return 0

    if state.get("refusal"):
        print(f"REJECTED: {state['refusal']}")
        print(f"  request_id {cfg_id} was denied and is closed")
        return 3

    print(f"stage: {state.get('stage')}")
    if state.get("result"):
        print(f"result: {state['result']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
