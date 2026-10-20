---------------------- MODULE SSAPSharedOwnership ----------------------
EXTENDS Naturals, FiniteSets
CONSTANTS Tokens, Capacity, CleanupBudget, WeakClose
VARIABLES phase, members, used, closed, retained, offProof, debt, remote,
          last, remaining, terminals, results
vars == <<phase,members,used,closed,retained,offProof,debt,remote,last,
          remaining,terminals,results>>
Ids == 1..Tokens
Init == /\ phase="idle" /\ members={} /\ used={} /\ closed={}
        /\ retained={} /\ offProof={} /\ debt=FALSE /\ remote="off"
        /\ last=0 /\ remaining=0 /\ terminals=[p \in Ids |-> 0]
        /\ results=[p \in Ids |-> "none"]

\* One already Native-identity/security-bound exact-filter/mode group.
\* Physical replies are nondeterministic validated inputs,not proved decoding.
\* Starting charges possible physical effect before any successful response.
Start(p) == /\ phase="idle" /\ ~debt /\ p \notin used
            /\ phase'="starting" /\ members'={p} /\ used'=used \cup {p}
            /\ debt'=TRUE /\ remote'="maybe"
            /\ UNCHANGED <<closed,retained,offProof,last,remaining,terminals,results>>
Enable == /\ phase="starting" /\ phase'="active" /\ remote'="on"
          /\ UNCHANGED <<members,used,closed,retained,offProof,debt,last,remaining,terminals,results>>
EnableUnknown == /\ phase="starting" /\ phase'="retired"
                 /\ closed'=closed \cup members
                 /\ terminals'=[p \in Ids |-> IF p \in members THEN 1 ELSE terminals[p]]
                 /\ results'=[p \in Ids |-> IF p \in members THEN "failed" ELSE results[p]]
                 /\ members'={}
                 /\ UNCHANGED <<used,retained,offProof,debt,remote,last,remaining>>
Join(p) == /\ phase="active" /\ members # {} /\ Cardinality(members)<Capacity
           /\ p \notin used /\ members'=members \cup {p} /\ used'=used \cup {p}
           /\ UNCHANGED <<phase,closed,retained,offProof,debt,remote,last,remaining,terminals,results>>
\* Release,owner loss and expiry remove only that caller/token. The actual
\* implementation removes its RX route/queue before returning retained flags.
Close(p) == LET rest==members \ {p} IN
           /\ phase="active" /\ p \in members
           /\ members'=rest /\ closed'=closed \cup {p}
           /\ phase'=IF rest={} \/ WeakClose THEN "closing" ELSE "active"
           /\ last'=IF rest={} \/ WeakClose THEN p ELSE last
           /\ remaining'=IF rest={} \/ WeakClose THEN CleanupBudget ELSE remaining
           /\ retained'=IF rest#{} /\ ~WeakClose THEN retained \cup {p} ELSE retained
           /\ terminals'=IF rest#{} /\ ~WeakClose THEN [terminals EXCEPT ![p]=@+1] ELSE terminals
           /\ results'=IF rest#{} /\ ~WeakClose THEN [results EXCEPT ![p]="retained"] ELSE results
           /\ UNCHANGED <<used,offProof,debt,remote>>
\* No fairness assumption requires firmware to send a positive response.
DisableVerified == /\ phase="closing" /\ phase'="idle" /\ debt'=FALSE
                   /\ remote'="off" /\ offProof'=offProof \cup {last}
                   /\ terminals'=[terminals EXCEPT ![last]=@+1]
                   /\ results'=[results EXCEPT ![last]="off"]
                   /\ UNCHANGED <<members,used,closed,retained,last,remaining>>
DisableUnknown == /\ phase="closing" /\ phase'="retired"
                  /\ terminals'=[terminals EXCEPT ![last]=@+1]
                  /\ results'=[results EXCEPT ![last]="failed"]
                  /\ UNCHANGED <<members,used,closed,retained,offProof,debt,remote,last,remaining>>
Tick == /\ phase="closing" /\ remaining>0 /\ remaining'=remaining-1
        /\ UNCHANGED <<phase,members,used,closed,retained,offProof,debt,remote,last,terminals,results>>
Expire == /\ phase="closing" /\ remaining=0 /\ DisableUnknown
Next == (\E p \in Ids: Start(p) \/ Join(p) \/ Close(p))
        \/ Enable \/ EnableUnknown \/ DisableVerified \/ DisableUnknown \/ Tick \/ Expire
TypeOK == /\ phase \in {"idle","starting","active","closing","retired"}
          /\ members \subseteq Ids /\ used \subseteq Ids /\ closed \subseteq Ids
          /\ retained \subseteq closed /\ offProof \subseteq closed
          /\ debt \in BOOLEAN /\ remote \in {"off","maybe","on"}
          /\ last \in 0..Tokens /\ remaining \in 0..CleanupBudget
          /\ terminals \in [Ids -> 0..1]
          /\ results \in [Ids -> {"none","retained","off","failed"}]
NoSiblingClear == phase \in {"closing","idle"} => members={}
DebtPreserved == remote#"off" => debt
NoOldResurrection == members \cap closed={}
SingleTerminal == \A p \in Ids: terminals[p]<=1
CapacityBound == Cardinality(members)<=Capacity
NoFalseRemoteOff == \A p \in Ids: results[p]="off" => p \in offProof
EventuallyTerminal == [](phase="closing" ~> phase \in {"idle","retired"})
\* Weakly fair worker/timer scheduling only. No bounded wall time/refinement.
Spec == Init /\ [][Next]_vars /\ WF_vars(Tick) /\ WF_vars(Expire)
=======================================================================
