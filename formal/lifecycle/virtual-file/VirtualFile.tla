---------------------------- MODULE VirtualFile ----------------------------
EXTENDS Naturals, FiniteSets
CONSTANTS Slots, MaxGeneration, WeakJoin
VARIABLES phase, aliases, queued, running, context, generation, captured,
          emitted, accepted, nextGeneration
vars == <<phase, aliases, queued, running, context, generation, captured,
          emitted, accepted, nextGeneration>>
Init == /\ phase = [s \in Slots |-> "Free"]
        /\ aliases = [s \in Slots |-> 0]
        /\ queued = [s \in Slots |-> FALSE]
        /\ running = [s \in Slots |-> FALSE]
        /\ context = [s \in Slots |-> FALSE]
        /\ generation = [s \in Slots |-> 0]
        /\ captured = [s \in Slots |-> 0]
        /\ emitted = [s \in Slots |-> FALSE]
        /\ accepted = [s \in Slots |-> 0]
        /\ nextGeneration = 1
Open(s) == /\ phase[s] = "Free" /\ nextGeneration <= MaxGeneration
           /\ phase' = [phase EXCEPT ![s] = "Live"]
           /\ aliases' = [aliases EXCEPT ![s] = 1]
           /\ context' = [context EXCEPT ![s] = TRUE]
           /\ generation' = [generation EXCEPT ![s] = nextGeneration]
           /\ nextGeneration' = nextGeneration + 1
           /\ accepted' = [accepted EXCEPT ![s] = 0]
           /\ UNCHANGED <<queued, running, captured, emitted>>
Dup(s) == /\ phase[s] = "Live" /\ aliases[s] = 1
          /\ aliases' = [aliases EXCEPT ![s] = 2]
          /\ UNCHANGED <<phase, queued, running, context, generation, captured,
                         emitted, accepted, nextGeneration>>
CloseAlias(s) == /\ phase[s] = "Live" /\ aliases[s] = 2
                /\ aliases' = [aliases EXCEPT ![s] = 1]
                /\ UNCHANGED <<phase, queued, running, context, generation,
                               captured, emitted, accepted, nextGeneration>>
LastClose(s) == /\ phase[s] = "Live" /\ aliases[s] = 1
               /\ aliases' = [aliases EXCEPT ![s] = 0]
               /\ phase' = [phase EXCEPT ![s] = "Retiring"]
               /\ UNCHANGED <<queued, running, context, generation, captured,
                              emitted, accepted, nextGeneration>>
Send(s) == /\ phase[s] = "Live" /\ ~queued[s]
           /\ queued' = [queued EXCEPT ![s] = TRUE]
           /\ UNCHANGED <<phase, aliases, running, context, generation, captured,
                          emitted, accepted, nextGeneration>>
BeginWork(s) == /\ phase[s] \in {"Live", "Retiring"}
                /\ queued[s] /\ ~running[s]
                /\ queued' = [queued EXCEPT ![s] = FALSE]
                /\ running' = [running EXCEPT ![s] = TRUE]
                /\ captured' = [captured EXCEPT ![s] = generation[s]]
                /\ emitted' = [emitted EXCEPT ![s] = FALSE]
                /\ UNCHANGED <<phase, aliases, context, generation, accepted,
                               nextGeneration>>
Deliver(s) == /\ running[s] /\ ~emitted[s]
              /\ emitted' = [emitted EXCEPT ![s] = TRUE]
              /\ accepted' = IF phase[s] = "Live" /\ captured[s] = generation[s]
                             THEN [accepted EXCEPT ![s] = captured[s]] ELSE accepted
              /\ UNCHANGED <<phase, aliases, queued, running, context, generation,
                             captured, nextGeneration>>
EndWork(s) == /\ running[s] /\ emitted[s]
              /\ running' = [running EXCEPT ![s] = FALSE]
              /\ UNCHANGED <<phase, aliases, queued, context, generation, captured,
                             emitted, accepted, nextGeneration>>
DriverClose(s) == /\ phase[s] = "Retiring"
                 /\ phase' = [phase EXCEPT ![s] = "Stopping"]
                 /\ queued' = [queued EXCEPT ![s] = FALSE]
                 /\ UNCHANGED <<aliases, running, context, generation, captured,
                                emitted, accepted, nextGeneration>>
FinishRetire(s) == /\ phase[s] = "Stopping" /\ (WeakJoin \/ ~running[s])
                  /\ phase' = [phase EXCEPT ![s] = "Free"]
                  /\ context' = [context EXCEPT ![s] = FALSE]
                  /\ UNCHANGED <<aliases, queued, running, generation, captured,
                                 emitted, accepted, nextGeneration>>
Next == \E s \in Slots : Open(s) \/ Dup(s) \/ CloseAlias(s) \/ LastClose(s)
                        \/ Send(s) \/ BeginWork(s) \/ Deliver(s) \/ EndWork(s)
                        \/ DriverClose(s) \/ FinishRetire(s)
Spec == Init /\ [][Next]_vars
Types == /\ phase \in [Slots -> {"Free", "Live", "Retiring", "Stopping"}]
         /\ aliases \in [Slots -> 0..2]
         /\ queued \in [Slots -> BOOLEAN] /\ running \in [Slots -> BOOLEAN]
         /\ context \in [Slots -> BOOLEAN] /\ emitted \in [Slots -> BOOLEAN]
         /\ generation \in [Slots -> 0..MaxGeneration]
         /\ captured \in [Slots -> 0..MaxGeneration]
         /\ accepted \in [Slots -> 0..MaxGeneration]
         /\ nextGeneration \in 1..(MaxGeneration + 1)
WorkHasContext == \A s \in Slots : running[s] => context[s]
LiveHasFile == \A s \in Slots : (phase[s] = "Live") <=> (aliases[s] > 0)
StoppingHasNoQueued == \A s \in Slots : phase[s] \in {"Stopping", "Free"} => ~queued[s]
ExactAcceptance == \A s \in Slots : accepted[s] = 0 \/ accepted[s] = generation[s]
=============================================================================
