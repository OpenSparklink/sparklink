------------------------- MODULE SessionNotification -------------------------
EXTENDS Naturals, FiniteSets
CONSTANTS Controllers, MaxEvents, QueueWhileRunning
VARIABLES active, table, borrowed, pending, running, refs, flag, runtimePending,
          stage, took, epoch, observed
vars == <<active, table, borrowed, pending, running, refs, flag, runtimePending,
          stage, took, epoch, observed>>
B(value) == IF value THEN 1 ELSE 0
Init == /\ active = [c \in Controllers |-> TRUE]
        /\ table = [c \in Controllers |-> TRUE]
        /\ borrowed = [c \in Controllers |-> FALSE]
        /\ pending = [c \in Controllers |-> FALSE]
        /\ running = [c \in Controllers |-> FALSE]
        /\ refs = [c \in Controllers |-> 1]
        /\ flag = [c \in Controllers |-> FALSE]
        /\ runtimePending = [c \in Controllers |-> FALSE]
        /\ stage = [c \in Controllers |-> 0]
        /\ took = [c \in Controllers |-> FALSE]
        /\ epoch = [c \in Controllers |-> 0]
        /\ observed = [c \in Controllers |-> 0]
Publish(c) == /\ active[c] /\ epoch[c] < MaxEvents
              /\ flag' = [flag EXCEPT ![c] = TRUE]
              /\ runtimePending' = [runtimePending EXCEPT ![c] =
                     IF QueueWhileRunning \/ stage[c] = 0 THEN TRUE ELSE @]
              /\ epoch' = [epoch EXCEPT ![c] = @ + 1]
              /\ UNCHANGED <<active, table, borrowed, pending, running, refs,
                              stage, took, observed>>
RuntimeBegin(c) == /\ stage[c] = 0 /\ runtimePending[c]
                   /\ runtimePending' = [runtimePending EXCEPT ![c] = FALSE]
                   /\ stage' = [stage EXCEPT ![c] = 1]
                   /\ UNCHANGED <<active, table, borrowed, pending, running,
                                   refs, flag, took, epoch, observed>>
TakeHint(c) == /\ stage[c] = 1
               /\ took' = [took EXCEPT ![c] = flag[c]]
               /\ flag' = [flag EXCEPT ![c] = FALSE]
               /\ stage' = [stage EXCEPT ![c] = 2]
               /\ UNCHANGED <<active, table, borrowed, pending, running, refs,
                               runtimePending, epoch, observed>>
TakeReference(c) == /\ stage[c] = 2
                    /\ borrowed' = [borrowed EXCEPT ![c] = took[c] /\ table[c] /\ active[c]]
                    /\ refs' = [refs EXCEPT ![c] = @ + B(took[c] /\ table[c] /\ active[c])]
                    /\ stage' = [stage EXCEPT ![c] = 3]
                    /\ UNCHANGED <<active, table, pending, running, flag,
                                    runtimePending, took, epoch, observed>>
Notify(c) == /\ stage[c] = 3
             /\ pending' = [pending EXCEPT ![c] = @ \/ (borrowed[c] /\ active[c])]
             /\ refs' = [refs EXCEPT ![c] = @ + B(borrowed[c] /\ active[c] /\ ~pending[c])]
             /\ stage' = [stage EXCEPT ![c] = 4]
             /\ UNCHANGED <<active, table, borrowed, running, flag,
                             runtimePending, took, epoch, observed>>
PutReference(c) == /\ stage[c] = 4
                   /\ refs' = [refs EXCEPT ![c] = @ - B(borrowed[c])]
                   /\ borrowed' = [borrowed EXCEPT ![c] = FALSE]
                   /\ stage' = [stage EXCEPT ![c] = 5]
                   /\ UNCHANGED <<active, table, pending, running, flag,
                                   runtimePending, took, epoch, observed>>
RuntimeFinish(c) == /\ stage[c] = 5
                    /\ stage' = [stage EXCEPT ![c] = 0]
                    /\ UNCHANGED <<active, table, borrowed, pending, running,
                                    refs, flag, runtimePending, took, epoch, observed>>
SessionBegin(c) == /\ pending[c] /\ ~running[c]
                   /\ pending' = [pending EXCEPT ![c] = FALSE]
                   /\ running' = [running EXCEPT ![c] = TRUE]
                   /\ observed' = [observed EXCEPT ![c] = IF active[c] THEN epoch[c] ELSE @]
                   /\ UNCHANGED <<active, table, borrowed, refs, flag,
                                   runtimePending, stage, took, epoch>>
SessionFinish(c) == /\ running[c]
                    /\ running' = [running EXCEPT ![c] = FALSE]
                    /\ refs' = [refs EXCEPT ![c] = @ - 1]
                    /\ UNCHANGED <<active, table, borrowed, pending, flag,
                                    runtimePending, stage, took, epoch, observed>>
Close(c) == /\ active[c]
            /\ active' = [active EXCEPT ![c] = FALSE]
            /\ UNCHANGED <<table, borrowed, pending, running, refs, flag,
                            runtimePending, stage, took, epoch, observed>>
Cancel(c) == /\ ~active[c] /\ pending[c]
             /\ pending' = [pending EXCEPT ![c] = FALSE]
             /\ refs' = [refs EXCEPT ![c] = @ - 1]
             /\ UNCHANGED <<active, table, borrowed, running, flag,
                             runtimePending, stage, took, epoch, observed>>
DropTable(c) == /\ ~active[c] /\ table[c] /\ ~pending[c] /\ ~running[c]
                /\ table' = [table EXCEPT ![c] = FALSE]
                /\ refs' = [refs EXCEPT ![c] = @ - 1]
                /\ UNCHANGED <<active, borrowed, pending, running, flag,
                                runtimePending, stage, took, epoch, observed>>
Next == \E c \in Controllers:
           Publish(c) \/ RuntimeBegin(c) \/ TakeHint(c) \/ TakeReference(c) \/
           Notify(c) \/ PutReference(c) \/ RuntimeFinish(c) \/ SessionBegin(c) \/
           SessionFinish(c) \/ Close(c) \/ Cancel(c) \/ DropTable(c)
Fairness == \A c \in Controllers:
              WF_vars(RuntimeBegin(c)) /\ WF_vars(TakeHint(c)) /\
              WF_vars(TakeReference(c)) /\ WF_vars(Notify(c)) /\
              WF_vars(PutReference(c)) /\ WF_vars(RuntimeFinish(c)) /\
              WF_vars(SessionBegin(c)) /\ WF_vars(SessionFinish(c)) /\
              WF_vars(Cancel(c)) /\ WF_vars(DropTable(c))
Spec == Init /\ [][Next]_vars /\ Fairness
TypeOK == /\ active \in [Controllers -> BOOLEAN]
          /\ table \in [Controllers -> BOOLEAN]
          /\ borrowed \in [Controllers -> BOOLEAN]
          /\ pending \in [Controllers -> BOOLEAN]
          /\ running \in [Controllers -> BOOLEAN]
          /\ refs \in [Controllers -> 0..4]
          /\ flag \in [Controllers -> BOOLEAN]
          /\ runtimePending \in [Controllers -> BOOLEAN]
          /\ stage \in [Controllers -> 0..5]
          /\ took \in [Controllers -> BOOLEAN]
          /\ epoch \in [Controllers -> 0..MaxEvents]
          /\ observed \in [Controllers -> 0..MaxEvents]
Ledger == \A c \in Controllers:
             refs[c] = B(table[c]) + B(borrowed[c]) + B(pending[c]) + B(running[c])
LiveReference == \A c \in Controllers:
                   (table[c] \/ borrowed[c] \/ pending[c] \/ running[c]) => refs[c] > 0
ClosedAdmissionStep == \A c \in Controllers: ~active[c] => (~pending'[c] \/ pending[c])
NoClosedAdmission == [][ClosedAdmissionStep]_vars
EventWake == \A c \in Controllers: \A e \in 1..MaxEvents:
                (active[c] /\ epoch[c] >= e) ~> (~active[c] \/ observed[c] >= e)
ClosedDrain == \A c \in Controllers: ~active[c] ~> refs[c] = 0
=============================================================================
