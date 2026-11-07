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


def ssap_client_configuration(raw, *, weak=None):
    """Only this finite declared model matrix; missing properties are not PASS."""
    invariants = {'TypeOK', 'NoPrematureSuccess', 'NoLateSuccess', 'DrainNotRenewed',
                  'SingleTerminal', 'OriginalAdmissionBound', 'NoCancelledSuccess'}
    rows = re.findall(r'^INVARIANTS\s+([^\n]+)$', raw, re.M)
    if len(rows) != 1 or set(rows[0].split()) != invariants or len(rows[0].split()) != len(invariants):
        raise ValueError('complete exact SSAP client invariant set required')
    values = re.findall(r'^(\w+)\s*=\s*(\S+)\s*$', raw, re.M)
    expected = dict(Parts='2', AuthorDeadline='3', DrainBudget='5', Horizon='8',
                    RequireAll='FALSE' if weak == 'parts' else 'TRUE',
                    RenewDrain='TRUE' if weak == 'drain' else 'FALSE')
    temporal = re.findall(r'^PROPERTY\s+([^\n]+)$', raw, re.M)
    if (weak not in (None, 'parts', 'drain') or len(values) != len(expected)
            or dict(values) != expected or temporal != ([] if weak else ['EventuallyResolved'])
            or re.findall(r'^SPECIFICATION\s+(\S+)\s*$', raw, re.M) != ['Spec']
            or re.findall(r'^CHECK_DEADLOCK\s+(\S+)\s*$', raw, re.M) != ['FALSE']):
        raise ValueError('exact SSAP client bounds,weak control and temporal property required')
    return dict(constants=expected, invariants=sorted(invariants), temporal=temporal)


def ssap_shared_configuration(raw,*,weak=False):
    invariants={'TypeOK','NoSiblingClear','DebtPreserved','NoOldResurrection','SingleTerminal','CapacityBound','NoFalseRemoteOff'}
    rows=re.findall(r'^INVARIANTS\s+([^\n]+)$',raw,re.M)
    expected=dict(Tokens='3',Capacity='2',CleanupBudget='2',WeakClose='TRUE'if weak else'FALSE')
    values=re.findall(r'^(\w+)\s*=\s*(\S+)\s*$',raw,re.M)
    temporal=re.findall(r'^PROPERTY\s+([^\n]+)$',raw,re.M)
    if (type(weak)is not bool or len(rows)!=1 or set(rows[0].split())!=invariants or len(rows[0].split())!=len(invariants)
            or len(values)!=len(expected)or dict(values)!=expected or temporal!=([]if weak else['EventuallyTerminal'])
            or re.findall(r'^SPECIFICATION\s+(\S+)\s*$',raw,re.M)!=['Spec']
            or re.findall(r'^CHECK_DEADLOCK\s+(\S+)\s*$',raw,re.M)!=['FALSE']):
        raise ValueError('complete exact bounded shared-owner properties and negative control required')
    return dict(constants=expected,invariants=sorted(invariants),temporal=temporal)


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
    elif kind in ("lkmm", "lkmm-ticket", "lkmm-rx", "lkmm-ingress"):
        expected = {"ChannelSnapshot": "Never", "ChannelSnapshotWeak": "Sometimes",
                    "ChannelCloseAdmission": "Never"}
        if kind == "lkmm-ticket":
            expected = {"TxCommitWithdrawal": "Never", "TxCommitWithdrawalWeak": "Sometimes"}
        if kind == "lkmm-rx":
            expected = {"RxDequeueWithdrawal": "Never", "RxDequeueWithdrawalWeak": "Sometimes"}
        if kind == "lkmm-ingress":
            expected = {"RuntimeRouteRetirement": "Never", "RuntimeRouteRetirementWeak": "Sometimes"}
        found = dict(re.findall(r"Observation (\w+) (Never|Sometimes|Always)\b", output))
        if code == 0 and found == expected:
            return "PROVED_SCOPED_WITH_WEAK_CONTROL"
    elif kind in ("tlc-ssap-client","tlc-ssap-shared") and code == 0:
        states = re.search(r"(\d+) distinct states found", output)
        if ("Model checking completed. No error has been found." in output
                and "Finished checking temporal properties" in output
                and states and int(states[1]) > 0 and not re.search(r"^Error:",output,re.M)):
            return "MODEL_CHECKED_SCOPED_NOT_IMPLEMENTATION_REFINEMENT"
    elif kind == "counterexample-ssap-shared":
        if code == 12 and "Invariant NoSiblingClear is violated." in output and len(re.findall(r"^State \d+:",output,re.M))>=2:
            return "EXPECTED_COUNTEREXAMPLE_WEAK_GUARD"
    elif kind in ("counterexample-ssap-parts", "counterexample-ssap-drain"):
        invariant = "NoPrematureSuccess" if kind.endswith("parts") else "DrainNotRenewed"
        if code == 12 and f"Invariant {invariant} is violated." in output:
            return "EXPECTED_COUNTEREXAMPLE_WEAK_GUARD"
    elif kind == "tlc" and code == 0 and "Model checking completed. No error has been found." in output:
        return "MODEL_CHECKED_SCOPED"
    elif kind == "counterexample-install" and code == 12 and "Invariant LiveMetadataCurrent is violated." in output:
        return "EXPECTED_COUNTEREXAMPLE_WEAK_GUARD"
    elif kind == "counterexample" and code == 12 and "Invariant NoWrongRefill is violated." in output:
        return "EXPECTED_COUNTEREXAMPLE_RISK_OPEN"
    elif kind == "kani" and code == 0 and "VERIFICATION:- SUCCESSFUL" in output and "0 failures, 1 total" in output:
        return "PROVED_SCOPED"
    return "NOT_PROVEN_FAILED_OR_INCOMPLETE"


def kani_export_verdict(data, harness, required=(), negative_marker=None, *, allowed_unreachable=()):
    """Kani0.68 structured results, including actual expected properties.

    This checks tool output, not source mapping/refinement. Callers must also
    bind the exact source, command, raw log, export hash and environment scope.
    Missing/unknown/unsupported/incomplete output cannot become PASS.
    """
    try:
        if data['metadata']['version'] != '1.0' or data['metadata']['kani_version'] != '0.68.0':
            return 'NOT_PROVEN_EXPORT_VERSION'
        result = data['verification_results']
        summary = result['summary']
        if (summary['total_harnesses'], summary['executed'], summary['status']) != (1, 1, 'completed'):
            return 'NOT_PROVEN_INCOMPLETE_EXPORT'
        if len(result['results']) != 1 or result['results'][0]['harness_id'] != harness:
            return 'NOT_PROVEN_HARNESS_MISMATCH'
        checks = result['results'][0]['checks']
        details = data['error_details']
        if len(details) != 1 or details[0]['harness_id'] != harness:
            return 'NOT_PROVEN_INCONSISTENT_ERRORS'
        if not checks or any(c['status'] not in ('Success', 'Failure') and not (c['status']=='Unreachable' and (c.get('function'),c['category'],c['description'])in allowed_unreachable) for c in checks):
            return 'NOT_PROVEN_PROPERTY_STATUS'
        if any(c['category'] == 'unsupported_construct' for c in checks):
            return 'NOT_PROVEN_UNSUPPORTED'
        if any(c['category'] not in {'assertion', 'arithmetic_overflow', 'pointer_dereference', 'unreachable', 'unwinding_assertion', 'division-by-zero'} for c in checks):
            return 'NOT_PROVEN_UNKNOWN_PROPERTY'
        descriptions = [c['description'] for c in checks]
        if negative_marker is None and not required:
            return 'NOT_PROVEN_MISSING_PROPERTY_SPEC'
        if any(not any(fragment in d for d in descriptions) for fragment in required):
            return 'NOT_PROVEN_MISSING_PROPERTY'
        if any(any(c['status']!='Success' for c in checks if fragment in c['description']) for fragment in required):
            return 'NOT_PROVEN_UNREACHABLE_REQUIRED_PROPERTY'
        failures = [c for c in checks if c['status'] == 'Failure']
        if negative_marker is not None:
            if details[0]['has_errors'] is not True or details[0]['error_type'] != 'assertion_failure':
                return 'NOT_PROVEN_WRONG_COUNTEREXAMPLE'
            if (summary['successful'], summary['failed'], result['results'][0]['status']) != (0, 1, 'Failure'):
                return 'NOT_PROVEN_NEGATIVE_CONTROL'
            if len(failures) == 1 and failures[0]['category'] == 'assertion' and negative_marker in failures[0]['description']:
                return 'EXPECTED_REJECTION_NEGATIVE_CONTROL'
            return 'NOT_PROVEN_WRONG_COUNTEREXAMPLE'
        if details[0]['has_errors'] is not False or (summary['successful'], summary['failed'], result['results'][0]['status']) != (1, 0, 'Success') or failures:
            return 'NOT_PROVEN_FAILED_OR_INCOMPLETE'
        return 'PROVED_SCOPED'
    except (KeyError, TypeError, IndexError):
        return 'NOT_PROVEN_INVALID_EXPORT'


def run(output, credit_all, budget, ticket_only=False, credit_rollback_only=False, binding_only=False, session_only=False, grant_only=False, rx_only=False, fd_grant_only=False, backend_only=False, ingress_only=False, usb_registry_only=False, backend_install_only=False, ssap_client_only=False, ssap_shared_only=False):
    if ssap_shared_only and any((credit_all,ticket_only,credit_rollback_only,binding_only,session_only,grant_only,rx_only,fd_grant_only,backend_only,ingress_only,usb_registry_only,backend_install_only,ssap_client_only)):
        raise ValueError("shared-owner proof requires its dedicated declared matrix")
    repo = Path(__file__).resolve().parents[1]
    kernel = Path(os.environ.get("SPARKLINK_KERNEL_SOURCE", repo.parent / "linux")).resolve()
    # Independent worktrees and CI pins need the explicitly selected kernel,
    # never a guessed sibling under .dev or a silent alternative checkout.
    root = Path(os.path.commonpath([repo, kernel]))
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    smoke = Path("/opt/opensparklink-verification-tools-20261013/system-smoke-tests.json")
    sources = [kernel / "net/sparklink" / name for name in (
        "sle_channel_state.h", "sle_channel_grant.h", "sle_channel_socket.c", "sle_data_credit.rs",
        "sle_native.rs", "sle_sessions.rs", "sle_grant.rs", "sle_native_data.rs", "sle_command_queue.rs", "sle_host.rs", "sle_irq_lock.rs", "sle_native_ffi.c", "sle_native_ffi.h")]
    sources += [kernel / "net/core/datagram.c", kernel / "drivers/sparklink/ws73/usb.c", kernel / "include/linux/sparklink_native.h"]
    sources += [kernel / "net/sparklink/sle_dev.rs", kernel / "net/sparklink/sle_dli.rs", kernel / "net/sparklink/sparklink_core.rs"]
    sources += [repo / "formal/usb_registry/Cargo.toml", repo / "formal/usb_registry/generate.py"]
    sources += [kernel / "net/sparklink/sle_ingress.rs", kernel / "net/sparklink/sle_workers.rs"]
    sources += [kernel / "include/linux/sparklink_backend.h", kernel / "tools/testing/selftests/sparklink/sparklink_backend_test.c"]
    sources += sorted((repo / "formal").rglob("*.c"))
    sources += sorted((repo / "formal").rglob("*.rs"))
    sources += sorted((repo / "formal").rglob("*.tla"))
    sources += sorted((repo / "formal").rglob("*.cfg"))
    sources += sorted((repo / "formal").rglob("*.litmus"))
    sources += [kernel / "tools/memory-model" / name for name in
                ("linux-kernel.cfg", "linux-kernel.cat", "linux-kernel.bell", "linux-kernel.def")]
    sources += [repo / "formal/README.md", repo / "formal/credit/Cargo.toml", repo / "formal/grant/Cargo.toml", Path(__file__).resolve()]
    if ssap_shared_only:
        sources += [repo/"crates/slkd/src"/name for name in ("ssap_engine.rs","ssap_receive_transaction.rs","ssap_subscription.rs")]
        sources += [repo/"crates/slk-contract/src/lib.rs",repo/"crates/libsparklink/src/ssap/subscription.rs"]
    if ssap_client_only:
        sources += [repo / "crates/slkd/src/ssap_engine.rs", repo / "crates/slk-protocol/src/ssap/fragments.rs",
                    repo / "crates/slk-channel/src/security.rs"]
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
    if ingress_only:
        checks = [("runtime-route-retirement", "lkmm-ingress", root,
                   ["herd7", "-conf", str(kernel / "tools/memory-model/linux-kernel.cfg"),
                    "-I", str(kernel / "tools/memory-model")] +
                   [str(repo / "formal/lkmm" / (n + ".litmus")) for n in
                    ("RuntimeRouteRetirement", "RuntimeRouteRetirementWeak")])]
    if usb_registry_only:
        checks = [("usb-registry-" + h, "kani", repo,
                   ["cargo", "kani", "--manifest-path", "formal/usb_registry/Cargo.toml", "--harness", h])
                  for h in ("initial_registry_is_empty_and_pending_registration_never_claims_up",
                            "allocator_preserves_occupied_slots_and_fails_closed_at_capacity_or_generation_limit")]
    record["usb_registry_only_requested"] = usb_registry_only
    record["usb_registry_scope"] = "actual production constructor/pending allocator/new registry; generated directly at build, info/stats/logger dependencies. Initial state plus arbitrary u16 allocation bitmap/u64 next generation>=2 with allocated-slot representation consistent and prior generation=next-1; existing generations may coincide (relaxed reachable-state set). Covers fresh pending-only allocation/capacity/overflow/occupied preservation, not uniqueness of preexisting generations, registry concurrent ownership, detach, open/Ready, callbacks, credits or hardware. Unsupported warnings remain NOT_PROVEN even with successful raw solver output."
    record["ingress_only_requested"] = ingress_only
    record["ingress_scope"] = "single live identity, initially absent route, one publish and one retire; schedule_gate held through routes publication and closed before exact unpublication. CPU spinlock abstraction plus check/drop/publish weak control; no Arc/kref, IRQ nesting, registry reuse, callbacks, workqueue, Host, memory reclamation or hardware refinement"
    record["backend_only_requested"] = backend_only
    if backend_install_only:
        checks = [
            ("backend-install", "tlc", repo / "formal/lifecycle",
             ["tlc", "-workers", "1", "-metadir", str(output / "tlc-install"),
              "-config", "BackendInstall.cfg", "BackendInstall.tla"]),
            ("backend-install-weak", "counterexample-install", repo / "formal/lifecycle",
             ["tlc", "-workers", "1", "-metadir", str(output / "tlc-install-weak"),
              "-config", "BackendInstallWeak.cfg", "BackendInstall.tla"]),
        ]
    record["backend_install_only_requested"] = backend_install_only
    record["backend_install_scope"] = "Abstract bounded registry publication safety:2 slots/2 candidates/global3 generations; atomic registry actions, nondeterministic allocation failure/retire/reuse/competing publication; no fairness/liveness, allocator/refcount/module/IRQ/callback/metadata-query/physical proof or implementation refinement. FinishRetire is an abstract joined-cleanup boundary, not a proof cleanup actually joins."
    record["backend_install_mapping"] = {
        "Reserve": "reserve_backend_identity -> SleDevRegistry.register_pending",
        "Snapshot/Construct/FailConstruction": "install_backend_runtime owned RuntimeRegistration then ControllerRuntime.new outside registry",
        "Publish/Reject": "install_backend_runtime final exact identity/retiring/occupied-slot guards before mutation",
        "Cancel": "cancel_backend_reservation exact generation, no Runtime, not retiring",
        "BeginRetire/FinishRetire": "sle_detach_device mark/take -> invalidate -> exact final unregister",
        "regression": "run_backend_install.py actual10 controlled constructor/destructor dependencies; weak model stale-generation trace maps to reuse_during_construction_preserves_new_generation",
    }
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
    if ssap_client_only:
        record['ssap_client_configurations'] = {
            name: ssap_client_configuration((repo / 'formal/lifecycle' / name).read_text(), weak=weak)
            for name, weak in [('SSAPClientObligation.cfg', None),
                               ('SSAPClientPrematureWeak.cfg', 'parts'),
                               ('SSAPClientDrainRenewWeak.cfg', 'drain')]}
        checks = [(name, kind, repo / "formal/lifecycle",
                   ["tlc", "-workers", "1", "-metadir", str(output / name), "-config", config,
                    "SSAPClientObligation.tla"]) for name, kind, config in [
            ("ssap-client-obligation", "tlc-ssap-client", "SSAPClientObligation.cfg"),
            ("ssap-client-premature-weak", "counterexample-ssap-parts", "SSAPClientPrematureWeak.cfg"),
            ("ssap-client-drain-renew-weak", "counterexample-ssap-drain", "SSAPClientDrainRenewWeak.cfg")]]
        record["ssap_client_scope"] = (
            "Bounded abstract single identity-bound client request,two SSAP parts,original author deadline3,"
            "first admission drain5,clock0..8. Maps to actual ClientRequest.admit_part/obligation_deadline,"
            "retire_client_wait,Pending.deadline and validate_reply. Safety and eventual request resolution"
            "under weakly fair clock/expiry scheduling only;not bounded realtime response. Native identity/RX"
            "authentication,syscall/USB admission,credit/NOCP,ticket/Grant,owner revocation,reference/drain"
            "implementation refinement and hardware are outside this model. Two weak guards must have exact"
            "counterexamples;no assumption that firmware sends a response. No full actual kernel/actor proof.")
    record["ssap_client_only_requested"] = ssap_client_only
    if ssap_shared_only:
        record['ssap_shared_configurations']={name:ssap_shared_configuration((repo/'formal/lifecycle'/name).read_text(),weak=weak)for name,weak in [('SSAPSharedOwnership.cfg',False),('SSAPSharedOwnershipWeak.cfg',True)]}
        checks=[(name,kind,repo/'formal/lifecycle',['tlc','-workers','1','-metadir',str(output/name),'-config',config,'SSAPSharedOwnership.tla'])for name,kind,config in [('ssap-shared-ownership','tlc-ssap-shared','SSAPSharedOwnership.cfg'),('ssap-shared-weak-close','counterexample-ssap-shared','SSAPSharedOwnershipWeak.cfg')]]
        record['ssap_shared_scope']='Bounded abstract one alreadyidentity/security-bound exactfilter/mode physicalgroup;3distincttokens,capacity2 (actualRustcapacity8testedseparately),onepossibleEnable/Disableeffect,optionalvalidatedreply orunknownfailure/retirement;no firmwarepositivereply fairness. Seven safety properties and terminalclose underweaklyfairworker/timer only,notboundedwalltime/implementationrefinement. Flagsretained/off are historicalterminalobservations. Independentqueues,Nativeidentity/Grant/credit/Ticket/RXauthentication,USB/callback/refdrain,NOCP,reuse/newgeneration,hardware notproved. Weakenedmulti-owner close-any guard is deliberatecounterexample,not an observed bug in old single-lease production.'
        record['ssap_shared_mapping']={'Start/Enable/EnableUnknown':'ReceiveTransaction.next/submitted/apply:markpossibly_enabled beforemaybesubmit,checkactualcorrelatedresult;unknownphysicaleffectnevererased','Join':'can_join/join:Active/live/currentidentity/filter/mode/token/capacity,originaldeadline;noextraNativewire','Close':'maintain Stream.close/expiry/OwnerLost,detachownSink andfinish(retained=true);closing usesallbindings','DisableVerified/DisableUnknown/Expire':'lastbinding closing,next Disable,originalfirstcleanup,verifiedresponse orretirewithunknown;notcallbackdrain','regression':'productionshared_release_retains_sibling_and_only_last_reference_owes_disable;secondaryowner/expiry/readcancel/capacity andfanout tests','WeakClose':'replaceallbindingclosing withany-owner close afterenablingmultipleowners;counterexample maps toshared-release regression'}
    record['ssap_shared_only_requested']=ssap_shared_only
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
    parser.add_argument("--ssap-shared-only",action="store_true",help="bounded abstract shared subscription ownership/debt with weak close-any counterexample")
    parser.add_argument("--ssap-client-only", action="store_true", help="bounded abstract partial client admission/cancellation/drain TLC and two weak controls")
    parser.add_argument("--backend-install-only", action="store_true", help="bounded abstract Backend reservation/publication TLC and weak generation control")
    parser.add_argument("--usb-registry-only", action="store_true", help="actual generated production pending allocator Kani only")
    parser.add_argument("--ingress-only", action="store_true", help="Runtime route publication/retirement LKMM and weak control only")
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
    raise SystemExit(run(args.output, args.credit_all, args.budget_seconds, args.ticket_only, args.credit_rollback_only, args.binding_only, args.session_only, args.grant_only, args.rx_only, args.fd_grant_only, args.backend_only, args.ingress_only, args.usb_registry_only, args.backend_install_only, args.ssap_client_only, args.ssap_shared_only))
