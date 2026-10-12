#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Bounded, source-hashed formal checks; never substitutes for VM qualification."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classify(kind, code, output, timed_out=False):
    if timed_out:
        return "NOT_PROVEN_TIMEOUT"
    if re.search(r"unsupported construct|unsupported feature", output, re.I):
        return "NOT_PROVEN_UNSUPPORTED"
    if kind == "cbmc":
        try:
            rows = json.loads(output)
        except ValueError:
            return "NOT_PROVEN_INVALID_OUTPUT"
        properties = [p for row in rows for p in row.get("result", [])]
        if code == 0 and properties and all(p["status"] == "SUCCESS" for p in properties) and any(
                row.get("cProverStatus") == "success" for row in rows):
            return "PROVED_SCOPED"
    elif kind in ("lkmm", "lkmm-ticket"):
        expected = {"ChannelSnapshot": "Never", "ChannelSnapshotWeak": "Sometimes",
                    "ChannelCloseAdmission": "Never"}
        if kind == "lkmm-ticket":
            expected = {"TxCommitWithdrawal": "Never", "TxCommitWithdrawalWeak": "Sometimes"}
        found = dict(re.findall(r"Observation (\w+) (Never|Sometimes|Always)\b", output))
        if code == 0 and found == expected:
            return "PROVED_SCOPED_WITH_WEAK_CONTROL"
    elif kind == "tlc" and code == 0 and "Model checking completed. No error has been found." in output:
        return "MODEL_CHECKED_SCOPED"
    elif kind == "counterexample" and code == 12 and "Invariant NoWrongRefill is violated." in output:
        return "EXPECTED_COUNTEREXAMPLE_RISK_OPEN"
    elif kind == "kani" and code == 0 and "VERIFICATION:- SUCCESSFUL" in output and "0 failures, 1 total" in output:
        return "PROVED_SCOPED"
    return "NOT_PROVEN_FAILED_OR_INCOMPLETE"


def run(output, credit_all, budget, ticket_only=False, credit_rollback_only=False, binding_only=False, session_only=False):
    repo = Path(__file__).resolve().parents[1]
    root = repo.parent
    kernel = root / "linux"
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    smoke = Path("/opt/opensparklink-verification-tools-20261013/system-smoke-tests.json")
    sources = [kernel / "net/sparklink" / name for name in (
        "sle_channel_state.h", "sle_channel_socket.c", "sle_data_credit.rs",
        "sle_native.rs", "sle_sessions.rs", "sle_native_data.rs", "sle_command_queue.rs", "sle_host.rs", "sle_irq_lock.rs", "sle_native_ffi.c", "sle_native_ffi.h")]
    sources += [kernel / "drivers/sparklink/ws73/usb.c", kernel / "include/linux/sparklink_native.h"]
    sources += sorted((repo / "formal").rglob("*.c"))
    sources += sorted((repo / "formal").rglob("*.rs"))
    sources += sorted((repo / "formal").rglob("*.tla"))
    sources += sorted((repo / "formal").rglob("*.cfg"))
    sources += sorted((repo / "formal").rglob("*.litmus"))
    sources += [kernel / "tools/memory-model" / name for name in
                ("linux-kernel.cfg", "linux-kernel.cat", "linux-kernel.bell", "linux-kernel.def")]
    sources += [repo / "formal/README.md", repo / "formal/credit/Cargo.toml", Path(__file__).resolve()]
    record = {"schema": 1, "status": "RUNNING", "hardware_acceptance": False,
              "installation_is_implementation_proof": False,
              "installation_smoke_sha256": sha(smoke),
              "sources": {str(p.relative_to(root)): sha(p) for p in sources},
              "repositories": {}, "checks": []}
    record["tool_paths"] = {name: shutil.which(name) for name in (
        "cbmc", "goto-cc", "goto-instrument", "herd7", "tlc", "cargo-kani",
        "ghidra", "ghidra-headless", "tamarin-prover", "proverif", "maude")}
    record["tool_versions"] = {}
    for name, command in (("cbmc", ["cbmc", "--version"]),
                          ("herd7", ["herd7", "-version"]),
                          ("kani", ["cargo", "kani", "--version"])):
        record["tool_versions"][name] = subprocess.check_output(command, text=True, timeout=15).strip()
    for name, directory in (("linux", kernel), ("sparklink", repo)):
        record["repositories"][name] = {
            "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=directory, text=True).strip(),
            "worktree": subprocess.check_output(["git", "status", "--porcelain"], cwd=directory, text=True)}
    env = dict(os.environ, CARGO_TARGET_DIR=str(root / ".dev/formal-credit-system-target"))
    checks = [
        ("channel-progress", "cbmc", root,
         ["cbmc", str(repo / "formal/channel/progress_cbmc.c"), "--bounds-check", "--pointer-check",
          "--signed-overflow-check", "--unsigned-overflow-check", "--unwind", "20", "--unwinding-assertions", "--json-ui"]),
        ("state-publication", "lkmm", root,
         ["herd7", "-conf", str(kernel / "tools/memory-model/linux-kernel.cfg"), "-I",
          str(kernel / "tools/memory-model")] + [str(repo / "formal/lkmm" / (n + ".litmus")) for n in
          ("ChannelSnapshot", "ChannelSnapshotWeak", "ChannelCloseAdmission")]),
        ("managed-lifetime", "tlc", repo / "formal/lifecycle",
         ["tlc", "-workers", "1", "-metadir", str(output / "tlc-managed"), "-config", "ManagedLifetime.cfg", "ManagedLifetime.tla"]),
        ("nocp-reuse-risk", "counterexample", repo / "formal/lifecycle",
         ["tlc", "-workers", "1", "-metadir", str(output / "tlc-nocp"), "-config", "NOCPReuse.cfg", "NOCPReuse.tla"]),
    ]
    harnesses = ["initialization_all_parameters"]
    if credit_all:
        harnesses += ["reservation_preserves_invariant_and_old_debt",
                      "arbitrary_completion_preserves_invariant_and_exact_accounting",
                      "uncertain_transport_never_refunds_or_refills",
                      "separate_controllers_do_not_share_ledger_mutations",
                      "rejected_atomic_submission_restores_exact_prior_ledger"]
    checks += [("credit-" + h, "kani", repo,
                ["cargo", "kani", "--manifest-path", "formal/credit/Cargo.toml", "--harness", h]) for h in harnesses]
    ticket_check = ("ticket-submit-withdrawal", "lkmm-ticket", root,
                    ["herd7", "-conf", str(kernel / "tools/memory-model/linux-kernel.cfg"),
                     "-I", str(kernel / "tools/memory-model")] +
                    [str(repo / "formal/lkmm" / (n + ".litmus")) for n in
                     ("TxCommitWithdrawal", "TxCommitWithdrawalWeak")])
    checks = [ticket_check] if ticket_only else checks + [ticket_check]
    if credit_rollback_only:
        h = "rejected_atomic_submission_restores_exact_prior_ledger"
        checks = [("credit-" + h, "kani", repo,
                   ["cargo", "kani", "--manifest-path", "formal/credit/Cargo.toml", "--harness", h])]
    if binding_only:
        checks = [("binding-state", "cbmc", root,
                   ["cbmc", str(repo / "formal/channel/binding_cbmc.c"), "--bounds-check", "--pointer-check",
                    "--signed-overflow-check", "--unsigned-overflow-check", "--unwind", "20", "--unwinding-assertions", "--json-ui"])]
    if session_only:
        checks = [("session-lifetime", "tlc", repo / "formal/lifecycle",
                   ["tlc", "-workers", "1", "-metadir", str(output / "tlc-session"),
                    "-config", "ConnectionSession.cfg", "ConnectionSession.tla"])]
    record["session_only_requested"] = session_only
    record["session_scope"] = "abstract contract only: two controllers/two lifetimes, fd aliases0..2 and pending/running work0..1 each; last close does not restart CMTC, joined references before free; not C/Rust/VFS refinement, lost wakeups, Grant/NOCP/hardware proof"
    record["binding_only_requested"] = binding_only
    record["binding_scope"] = "actual binding initialization/representation/retire/busy/queue-space helpers; not C session work/VFS/kref refinement or hardware"
    record["credit_rollback_only_requested"] = credit_rollback_only
    record["ticket_only_requested"] = ticket_only
    record["ticket_scope"] = "Host-locked validation/atomic submit vs Host withdrawal CPU order, with a weak check-drop-submit control; not C/Rust refinement, HCD internals, callback UAF, Grant epoch or NOCP reuse barrier"
    manifest = output / "manifest.json"
    for name, kind, cwd, command in checks:
        log = output / (name + ".log")
        start = time.monotonic()
        timed_out = False
        with log.open("w") as stream:
            process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stream,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = process.wait(timeout=budget)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
                code = process.wait()
        text = log.read_text()
        record["checks"].append({"name": name, "kind": kind, "command": command,
                                 "cwd": str(cwd), "budget_seconds": budget,
                                 "elapsed_seconds": round(time.monotonic() - start, 3),
                                 "exit": code, "status": classify(kind, code, text, timed_out),
                                 "output": log.name, "output_sha256": sha(log),
                                 "tool_banner": text.splitlines()[:2]})
        manifest.write_text(json.dumps(record, indent=2) + "\n")
        print(name, record["checks"][-1]["status"], flush=True)
    record["sources_unchanged"] = all(sha(p) == record["sources"][str(p.relative_to(root))] for p in sources)
    record["status"] = "SCOPED_RESULTS_RECORDED_FULL_VERIFICATION_OPEN"
    if not record["sources_unchanged"]:
        record["status"] = "NOT_PROVEN_SOURCE_CHANGED"
    record["credit_all_requested"] = credit_all
    record["unselected_credit_harnesses_proved"] = False
    manifest.write_text(json.dumps(record, indent=2) + "\n")
    print(str(manifest))
    return 2 if not record["sources_unchanged"] or any(
        c["status"].startswith("NOT_PROVEN") for c in record["checks"]) else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--credit-all", action="store_true")
    parser.add_argument("--session-only", action="store_true", help="bounded abstract Session/Binding/work lifetime TLC only")
    parser.add_argument("--binding-only", action="store_true", help="actual binding pure-state CBMC only")
    parser.add_argument("--credit-rollback-only", action="store_true", help="only the new actual ledger rollback harness")
    parser.add_argument("--ticket-only", action="store_true", help="scope this run to submission/withdrawal LKMM and weak control")
    parser.add_argument("--budget-seconds", type=int, default=600)
    args = parser.parse_args()
    if not 1 <= args.budget_seconds <= 3600:
        parser.error("budget must be 1..3600 seconds per check")
    raise SystemExit(run(args.output, args.credit_all, args.budget_seconds, args.ticket_only, args.credit_rollback_only, args.binding_only, args.session_only))
