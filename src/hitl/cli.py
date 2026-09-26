"""CLI for the HITL approval agent.

    hitl submit "transition P-1 to Done"   -> runs until the gate, then EXITS
    hitl approve <request_id> --as <who>   -> resumes from the checkpoint
    hitl deny    <request_id> --as <who>
    hitl audit   <request_id>
    hitl users   add <who> --level lead    -> who may approve, and up to what tier
    hitl config                            -> print the resolved configuration

Approvers come from `<home>/identities.json`. No file means no approvers, so a
fresh install approves nothing until someone is added -- the safe direction to
fail in.

Settings come from `<home>/config.toml`, the environment (`HITL_*`) and a
`.env` file; see config.example.toml. `--home`, `--profile` and `--config` are
global, so they go before the subcommand: `hitl --profile prod submit ...`.

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
from hitl.config import ConfigError, load_config
from hitl.graph import build_graph, checkpointer_for
from hitl.health import check_health, defer_signals
from hitl.identity import FileIdentityProvider
from hitl.jira import FakeJira
from hitl.logging import setup_logging
from hitl.notifiers import EmailNotifier, NotifierChain, SlackNotifier, WebhookNotifier
from hitl.policy import Action
from hitl.server import serve

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


def _build_notifiers(cfg) -> NotifierChain | None:
    """Build notifier chain from config.

    Returns None if no notifiers are configured. Notifiers are keyed by
    approval level (JUNIOR, SENIOR, LEAD) from notify_levels config.
    """
    notifiers: dict[str, list] = {}
    levels = [lv.strip().upper() for lv in cfg.notify_levels.split(",")]

    if cfg.slack_webhook_url:
        notifier = SlackNotifier(url=cfg.slack_webhook_url)
        for level in levels:
            notifiers.setdefault(level, []).append(notifier)

    if cfg.smtp_host and cfg.smtp_from:
        notifier = EmailNotifier(smtp_host=cfg.smtp_host, from_addr=cfg.smtp_from)
        for level in levels:
            notifiers.setdefault(level, []).append(notifier)

    if cfg.webhook_url:
        notifier = WebhookNotifier(url=cfg.webhook_url)
        for level in levels:
            notifiers.setdefault(level, []).append(notifier)

    return NotifierChain(notifiers) if notifiers else None


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
    # No argparse defaults on these three: a flag left off must fall through
    # to the environment and the config file, not overwrite them with its own
    # idea of a default.
    p.add_argument("--home", type=Path)
    p.add_argument("--profile")
    p.add_argument("--config", type=Path, help="TOML config file")
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

    c = sub.add_parser("config", help="print the resolved configuration")
    c.add_argument("--json", action="store_true")

    h = sub.add_parser("health", help="check that this install can do its job")
    h.add_argument("--json", action="store_true")
    h.add_argument(
        "--deep",
        action="store_true",
        help="also verify the audit chain and count stuck approvals",
    )

    sv = sub.add_parser("serve", help="serve /health and /metrics until SIGTERM")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8080)

    args = p.parse_args(argv)

    try:
        cfg = load_config(path=args.config, home=args.home, profile=args.profile)
    except ConfigError as exc:
        # Fail at startup with every problem at once, rather than halfway
        # through a request with one of them.
        print(str(exc))
        return 2

    setup_logging("hitl", level=cfg.log_level)
    home = cfg.home
    db = cfg.checkpoint_db
    identities_path = cfg.identities_path

    if args.cmd == "config":
        resolved = cfg.redacted()
        if args.json:
            print(json.dumps(resolved, indent=2, sort_keys=True))
        else:
            for key, value in sorted(resolved.items()):
                print(f"{key} = {value!r}")
        return 0

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

    if args.cmd == "health":
        report = check_health(cfg, deep=args.deep)
        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(f"status: {report.status}")
            for check in report.checks:
                print(f"  {check.status:9} {check.name}: {check.detail}")
        return 0 if report.ok else 1

    if args.cmd == "serve":
        return serve(cfg, host=args.host, port=args.port)

    if args.cmd == "verify":
        problems = verify_chain(cfg.audit_dir)
        if problems:
            print(f"AUDIT TRAIL COMPROMISED ({len(problems)} problem(s))")
            for problem in problems:
                print(f"  {problem}")
            return 1
        print("audit trail intact")
        return 0

    if args.cmd == "audit":
        found = []
        for f in sorted(cfg.audit_dir.glob("*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                if json.loads(line)["request_id"] == args.request_id:
                    found.append(line)
        if not found:
            print(f"no audit records for {args.request_id}")
            return 1
        print("\n".join(found))
        return 0

    jira = _jira(args.seed)
    request_id = args.request_id if args.cmd != "submit" else new_request_id()
    thread = {"configurable": {"thread_id": request_id}}

    if args.cmd == "submit":
        # Parse before opening anything: an unparseable request must not
        # leave a checkpoint file behind.
        try:
            action = parse_action(args.request)
        except ValueError as exc:
            print(str(exc))
            return 2

    # Running the graph and writing its audit records is one indivisible
    # step. A SIGTERM landing between them would leave an executed action
    # with no trail, which is the one outcome this system exists to prevent.
    with defer_signals():
        with checkpointer_for(db) as cp:
            notifiers = _build_notifiers(cfg)
            app = build_graph(jira, cp, FileIdentityProvider(identities_path), notifiers)
            if args.cmd == "submit":
                state = app.invoke(
                    {
                        "request": args.request,
                        "request_id": request_id,
                        "action": asdict(action),
                    },
                    thread,
                )
            else:
                decision = "approve" if args.cmd == "approve" else "deny"
                state = app.invoke(
                    Command(
                        resume={"decision": decision, "human_id": args.human_id}
                    ),
                    thread,
                )

        _emit(state, home)

    if "__interrupt__" in state:
        print("APPROVAL REQUIRED")
        print(f"  request_id {request_id}")
        print(f"  approve with: hitl approve {request_id} --as <your-id>")
        return 0

    if state.get("refusal"):
        print(f"REJECTED: {state['refusal']}")
        print(f"  request_id {request_id} was denied and is closed")
        return 3

    print(f"stage: {state.get('stage')}")
    if state.get("result"):
        print(f"result: {state['result']}")

    if state.get("stage") == "deferred":
        # Distinct from a failure on purpose: nothing was applied, so this one
        # is safe to submit again once Jira is back.
        print("  nothing was applied -- safe to resubmit once Jira is reachable")
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
