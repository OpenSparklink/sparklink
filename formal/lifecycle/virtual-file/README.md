# Virtual control File / callback lifetime model

This is a bounded **abstract safety contract**, not another production driver,
not a C/Rust/VFS/workqueue refinement proof, and not physical acceptance.
The production implementation is `linux/drivers/sparklink/virtual.c` at
`88372a9b7cbcea7fcbca4f34cc9d5707488be46e`. Its actual codec is checked separately
by CBMC. The VM test executes the actual driver and production Core/Host.

Run from this directory, using fresh model-state directories:

```
tlc -workers 2 -config VirtualFile.cfg -metadir /tmp/slk-virtual-production VirtualFile.tla
tlc -workers 2 -config VirtualFileWeak.cfg -metadir /tmp/slk-virtual-weak VirtualFile.tla
```

The positive run must terminate completely with exit 0 and no invariant error;
the weak run must produce `WorkHasContext` violation. Timeouts, parser/tool
failures, unsupported or partial runs are not proofs. TLC requires local RMI;
a restricted environment may reject its local listener.

| Model action/state | Source mapping | Boundary/assumption |
|---|---|---|
| Open, Live, context | `virtual_control_open`, common reserve/register/open | Successful common registration abstracted atomically; partial init/install/refcount/module paths are not modeled |
| aliases 1..2, Dup, CloseAlias | VFS File refs and `virtual_fops.release` | VFS invokes release only on last File reference; bounded aliases, no proof of VFS |
| LastClose/Retiring | `virtual_control_release` -> Core exact unregister/invalidate | Core gate closes before physical driver close; already-entered worker may still deliver old identity |
| queued/Send/BeginWork/captured | `virtual_send` and locked snapshot in `virtual_deliver` | One queued reply slot, one running callback; Linux workqueue non-reentrancy assumed; no Host/credit model |
| Deliver/accepted | `sparklink_backend_standard_receive` -> exact owner and closed-gate ingress | Exact generation and admission gate are assumed seam contracts, not proven here |
| DriverClose/Stopping | `virtual_close`: live=false, pending=false | Lock serialization is abstract; queued work cancellation occurs here |
| FinishRetire | `cancel_delayed_work_sync`, unregister return then control `virtual_put` | **Join completion is a precondition under review**; kernel API/module/context refs need actual regression/refinement |
| WorkHasContext | context memory remains live through work callback/framework return | Dropping join guard deliberately detects memory lifetime risk |

Bounds: two slots, global generations 1..4, at most two control File aliases,
one queued slot and one running callback per context. No fairness or liveness,
command/data credit conservation, Host cancellation, module reference arithmetic,
IRQ/memory-model, PM, controller firmware, NOCP or RF proof is claimed.
Hardware-specific uncertainty must not be excluded by these assumptions.

The weak variant removes the join guard only. Its counterexample is mapped to
the actual requirement to join **already-entered** work before freeing context.
The current VM test covers pending-work last-close cancellation, dup, retirement,
reuse and stale generation; a deterministic already-entered callback join test
is still missing. This model result does not fill that implementation gap.
The two-controller VM query/fault matrix is also required for real implementation
isolation. Original issues remain open.
