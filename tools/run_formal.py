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
    elif kind in ("lkmm", "lkmm-ticket", "lkmm-rx"):
        expected = {"ChannelSnapshot": "Never", "ChannelSnapshotWeak": "Sometimes",
                    "ChannelCloseAdmission": "Never"}
        if kind == "lkmm-ticket":
            expected = {"TxCommitWithdrawal": "Never", "TxCommitWithdrawalWeak": "Sometimes"}
        if kind == "lkmm-rx":
            expected = {"RxDequeueWithdrawal": "Never", "RxDequeueWithdrawalWeak": "Sometimes"}
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


def run(output, credit_all, budget, ticket_only=False, credit_rollback_only=False, binding_only=False, session_only=False, grant_only=False, rx_only=False, fd_grant_only=False, backend_only=False):
    repo = Path(__file__).resolve().parents[1]
    root = repo.parent
    kernel = root / "linux"
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    smoke = Path("/opt/opensparklink-verification-tools-20261013/system-smoke-tests.json")
    sources = [kernel / "net/sparklink" / name for name in (
        "sle_channel_state.h", "sle_channel_grant.h", "sle_channel_socket.c", "sle_data_credit.rs",
        "sle_native.rs", "sle_sessions.rs", "sle_grant.rs", "sle_native_data.rs", "sle_command_queue.rs", "sle_host.rs", "sle_irq_lock.rs", "sle_native_ffi.c", "sle_native_ffi.h")]
    sources += [kernel / "net/core/datagram.c", kernel / "drivers/sparklink/ws73/usb.c", kernel / "include/linux/sparklink_native.h"]
    sources += [kernel / "include/linux/sparklink_backend.h", kernel / "tools/testing/selftests/sparklink/sparklink_backend_test.c"]
    sources += sorted((repo / "formal").rglob("*.c"))
    sources += sorted((repo / "formal").rglob("*.rs"))
    sources += sorted((repo / "formal").rglob("*.tla"))
    sources += sorted((repo / "formal").rglob("*.cfg"))
    sources += sorted((repo / "formal").rglob("*.litmus"))
    sources += [kernel / "tools/memory-model" / name for name in
                ("linux-kernel.cfg", "linux-kernel.cat", "linux-kernel.bell", "linux-kernel.def")]
    sources += [repo / "formal/README.md", repo / "formal/credit/Cargo.toml", repo / "formal/grant/Cargo.toml", Path(__file__).resolve()]
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
    if grant_only:
        checks = [("grant-" + h, "kani", repo,
                   ["cargo", "kani", "--manifest-path", "formal/grant/Cargo.toml", "--harness", h])
                  for h in ("lease_authority_constructor_and_transition_induction", "revoked_epoch_never_revives_in_successor")]
    if rx_only:
        checks = [("rx-dequeue-withdrawal", "lkmm-rx", root,
                   ["herd7", "-conf", str(kernel / "tools/memory-model/linux-kernel.cfg"),
                    "-I", str(kernel / "tools/memory-model")] +
                   [str(repo / "formal/lkmm" / (n + ".litmus")) for n in
                    ("RxDequeueWithdrawal", "RxDequeueWithdrawalWeak")])]
    if fd_grant_only:
        checks = [("fd-grant-scope", "cbmc", root,
                   ["cbmc", str(repo / "formal/channel/grant_cbmc.c"), "--bounds-check", "--pointer-check",
                    "--signed-overflow-check", "--unsigned-overflow-check", "--unwind", "2", "--unwinding-assertions", "--json-ui"])]
    if backend_only:
        checks = [("backend-descriptor", "cbmc", root,
                   ["cbmc", str(repo / "formal/backend/descriptor_cbmc.c"), "-I", str(kernel / "include"),
                    "--function", "proof", "--bounds-check", "--pointer-check", "--signed-overflow-check",
                    "--unsigned-overflow-check", "--unwind", "2", "--unwinding-assertions", "--json-ui"])]
    record["backend_only_requested"] = backend_only
    record["backend_scope"] = "actual production descriptor validator over arbitrary u32 version/size/bus/capabilities/profile, u16 lengths/u8 counts and callback presence; live immutable provider-owned pointers assumed; no callback execution, module/context references, registration allocation/publication/retirement, concurrency or hardware proof"
    record["fd_grant_only_requested"] = fd_grant_only
    record["fd_grant_scope"] = "actual production pure constructor and identity/direction predicate over arbitrary u64/u32 scopes and masks; zero/unminted and unsupported protected requests deny; not Host epoch, C socket/VFS/kref, trust/security-state/downgrade or hardware refinement"
    record["rx_only_requested"] = rx_only
    record["rx_scope"] = "Host lock orders epoch validation and actual RX unlink/PEEK reference against withdrawal; CPU lock abstraction with weak check/drop/dequeue control, not C/Rust/VFS/queue refinement, wait/wakeup, copy completion, firmware or hardware proof"
    record["grant_only_requested"] = grant_only
    record["grant_scope"] = "actual production pure lease constructor and one-step induction over all u64 epoch/representation states; successor never renews revoked epoch; not Managed/Host lock refinement, C socket/VFS, safety/security or hardware proof"
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
    parser.add_argument("--backend-only", action="store_true", help="actual production Backend descriptor admission CBMC only")
    parser.add_argument("--fd-grant-only", action="store_true", help="actual immutable fd grant constructor/identity/direction CBMC")
    parser.add_argument("--rx-only", action="store_true", help="RX admission/withdrawal Host lock LKMM and weak control")
    parser.add_argument("--grant-only", action="store_true", help="actual production lease authority Kani induction only")
    parser.add_argument("--session-only", action="store_true", help="bounded abstract Session/Binding/work lifetime TLC only")
    parser.add_argument("--binding-only", action="store_true", help="actual binding pure-state CBMC only")
    parser.add_argument("--credit-rollback-only", action="store_true", help="only the new actual ledger rollback harness")
    parser.add_argument("--ticket-only", action="store_true", help="scope this run to submission/withdrawal LKMM and weak control")
    parser.add_argument("--budget-seconds", type=int, default=600)
    args = parser.parse_args()
    if not 1 <= args.budget_seconds <= 3600:
        parser.error("budget must be 1..3600 seconds per check")
    raise SystemExit(run(args.output, args.credit_all, args.budget_seconds, args.ticket_only, args.credit_rollback_only, args.binding_only, args.session_only, args.grant_only, args.rx_only, args.fd_grant_only, args.backend_only))
