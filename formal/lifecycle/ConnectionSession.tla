------------------------- MODULE ConnectionSession -------------------------
EXTENDS Naturals, TLC
CONSTANTS Controllers, MaxLife
Objects == Controllers \X (1..MaxLife)
VARIABLES life, table, owner, phase, aliases, bindingRef, retired, pending, running, freed
vars == <<life,table,owner,phase,aliases,bindingRef,retired,pending,running,freed>>
Init == /\ life = [c \in Controllers |-> 1]
        /\ table = [o \in Objects |-> FALSE]
        /\ owner = [o \in Objects |-> FALSE]
        /\ phase = [o \in Objects |-> "Absent"]
        /\ aliases = [o \in Objects |-> 0]
        /\ bindingRef = [o \in Objects |-> FALSE]
        /\ retired = [o \in Objects |-> FALSE]
        /\ pending = [o \in Objects |-> FALSE]
        /\ running = [o \in Objects |-> FALSE]
        /\ freed = [o \in Objects |-> FALSE]
Create(c) == LET o == <<c,life[c]>> IN
 /\ phase[o] = "Absent" /\ ~freed[o]
 /\ table' = [table EXCEPT ![o] = TRUE]
 /\ owner' = [owner EXCEPT ![o] = TRUE]
 /\ phase' = [phase EXCEPT ![o] = "Negotiating"]
 /\ UNCHANGED <<life,aliases,bindingRef,retired,pending,running,freed>>
Bind(o) == /\ table[o] /\ phase[o] \in {"Negotiating","Open"}
           /\ ~retired[o] /\ ~bindingRef[o]
           /\ aliases' = [aliases EXCEPT ![o] = 1]
           /\ bindingRef' = [bindingRef EXCEPT ![o] = TRUE]
           /\ UNCHANGED <<life,table,owner,phase,retired,pending,running,freed>>
Dup(o) == /\ aliases[o] = 1 /\ aliases' = [aliases EXCEPT ![o] = 2]
          /\ UNCHANGED <<life,table,owner,phase,bindingRef,retired,pending,running,freed>>
CloseDup(o) == /\ aliases[o] = 2 /\ aliases' = [aliases EXCEPT ![o] = 1]
              /\ UNCHANGED <<life,table,owner,phase,bindingRef,retired,pending,running,freed>>
LastClose(o) == /\ aliases[o] = 1
               /\ aliases' = [aliases EXCEPT ![o] = 0]
               /\ bindingRef' = [bindingRef EXCEPT ![o] = FALSE]
               /\ retired' = [retired EXCEPT ![o] = TRUE]
               /\ UNCHANGED <<life,table,owner,phase,pending,running,freed>>
Schedule(o) == /\ phase[o] \in {"Negotiating","Open"} /\ ~pending[o] /\ ~freed[o]
               /\ pending' = [pending EXCEPT ![o] = TRUE]
               /\ UNCHANGED <<life,table,owner,phase,aliases,bindingRef,retired,running,freed>>
Run(o) == /\ pending[o] /\ ~running[o]
          /\ pending' = [pending EXCEPT ![o] = FALSE]
          /\ running' = [running EXCEPT ![o] = TRUE]
          /\ UNCHANGED <<life,table,owner,phase,aliases,bindingRef,retired,freed>>
Finish(o) == /\ running[o] /\ running' = [running EXCEPT ![o] = FALSE]
             /\ UNCHANGED <<life,table,owner,phase,aliases,bindingRef,retired,pending,freed>>
Open(o) == /\ phase[o] = "Negotiating"
           /\ phase' = [phase EXCEPT ![o] = "Open"]
           /\ UNCHANGED <<life,table,owner,aliases,bindingRef,retired,pending,running,freed>>
Stop(o) == /\ table[o]
           /\ table' = [table EXCEPT ![o] = FALSE]
           /\ phase' = [phase EXCEPT ![o] = "Closed"]
           /\ retired' = [retired EXCEPT ![o] = TRUE]
           /\ UNCHANGED <<life,owner,aliases,bindingRef,pending,running,freed>>
CancelPending(o) == /\ phase[o] = "Closed" /\ pending[o]
                    /\ pending' = [pending EXCEPT ![o] = FALSE]
                    /\ UNCHANGED <<life,table,owner,phase,aliases,bindingRef,retired,running,freed>>
JoinAndPutOwner(o) == /\ phase[o] = "Closed" /\ owner[o] /\ ~pending[o] /\ ~running[o]
                      /\ owner' = [owner EXCEPT ![o] = FALSE]
                      /\ UNCHANGED <<life,table,phase,aliases,bindingRef,retired,pending,running,freed>>
Free(o) == /\ phase[o] = "Closed" /\ ~owner[o] /\ aliases[o] = 0
           /\ ~pending[o] /\ ~running[o] /\ ~freed[o]
           /\ freed' = [freed EXCEPT ![o] = TRUE]
           /\ UNCHANGED <<life,table,owner,phase,aliases,bindingRef,retired,pending,running>>
NewLife(c) == /\ life[c] < MaxLife /\ ~table[<<c,life[c]>>]
              /\ life' = [life EXCEPT ![c] = @ + 1]
              /\ UNCHANGED <<table,owner,phase,aliases,bindingRef,retired,pending,running,freed>>
Next == (\E c \in Controllers: Create(c) \/ NewLife(c)) \/
        (\E o \in Objects: Bind(o) \/ Dup(o) \/ CloseDup(o) \/ LastClose(o) \/
         Schedule(o) \/ Run(o) \/ Finish(o) \/ Open(o) \/ Stop(o) \/
         CancelPending(o) \/ JoinAndPutOwner(o) \/ Free(o))
TypeOK == /\ life \in [Controllers -> 1..MaxLife]
          /\ phase \in [Objects -> {"Absent","Negotiating","Open","Closed"}]
          /\ aliases \in [Objects -> 0..2]
NoResurrection == \A o \in Objects: freed[o] => phase[o] = "Closed"
ReferencesProtectObject == \A o \in Objects: freed[o] => (~owner[o] /\ aliases[o]=0 /\ ~pending[o] /\ ~running[o])
NoPrematureRelease == \A o \in Objects: (aliases[o] > 0) => bindingRef[o]
NoRebindRetired == \A o \in Objects: retired[o] => (phase[o]="Closed" \/ aliases[o]=0)
Spec == Init /\ [][Next]_vars
=============================================================================
