-------------------------- MODULE ManagedLifetime --------------------------
EXTENDS Naturals, Sequences, TLC
CONSTANTS Controllers, MaxGeneration, QueueBound
VARIABLES generation, mode, refs, queue, inflight, cleanup, result, terminalCount
vars == <<generation, mode, refs, queue, inflight, cleanup, result, terminalCount>>

Init == /\ generation = [c \in Controllers |-> 1]
        /\ mode = [c \in Controllers |-> "Free"]
        /\ refs = [c \in Controllers |-> 0]
        /\ queue = [c \in Controllers |-> <<>>]
        /\ inflight = [c \in Controllers |-> 0]
        /\ cleanup = [c \in Controllers |-> FALSE]
        /\ result = [c \in Controllers |-> "None"]
        /\ terminalCount = [c \in Controllers |-> 0]

Acquire(c) == /\ mode[c] = "Free" /\ result[c] = "None"
              /\ mode' = [mode EXCEPT ![c] = "Owned"]
              /\ refs' = [refs EXCEPT ![c] = 1]
              /\ UNCHANGED <<generation, queue, inflight, cleanup, result, terminalCount>>
Dup(c) == /\ mode[c] = "Owned" /\ refs[c] = 1
          /\ refs' = [refs EXCEPT ![c] = 2]
          /\ UNCHANGED <<generation, mode, queue, inflight, cleanup, result, terminalCount>>
CloseDup(c) == /\ refs[c] = 2 /\ refs' = [refs EXCEPT ![c] = 1]
               /\ UNCHANGED <<generation, mode, queue, inflight, cleanup, result, terminalCount>>
Enqueue(c) == /\ mode[c] = "Owned" /\ refs[c] > 0
              /\ result[c] = "None" /\ Len(queue[c]) = 0 /\ inflight[c] = 0
              /\ Len(queue[c]) < QueueBound
              /\ queue' = [queue EXCEPT ![c] = Append(@, generation[c])]
              /\ UNCHANGED <<generation, mode, refs, inflight, cleanup, result, terminalCount>>
Submit(c) == /\ mode[c] = "Owned" /\ Len(queue[c]) > 0 /\ inflight[c] = 0
             /\ inflight' = [inflight EXCEPT ![c] = Head(queue[c])]
             /\ queue' = [queue EXCEPT ![c] = Tail(@)]
             /\ UNCHANGED <<generation, mode, refs, cleanup, result, terminalCount>>
Revoke(c) == /\ mode[c] = "Owned"
             /\ mode' = [mode EXCEPT ![c] = "Releasing"]
             /\ refs' = [refs EXCEPT ![c] = 0]
             /\ queue' = [queue EXCEPT ![c] = <<>>]
             /\ cleanup' = [cleanup EXCEPT ![c] = TRUE]
             /\ result' = [result EXCEPT ![c] = IF @ = "None" THEN "Cancelled" ELSE @]
             /\ terminalCount' = [terminalCount EXCEPT ![c] = IF result[c] = "None" THEN @ + 1 ELSE @]
             /\ UNCHANGED <<generation, inflight>>
Reply(c, g) == /\ g = generation[c] /\ inflight[c] = g
               /\ inflight' = [inflight EXCEPT ![c] = 0]
               /\ result' = [result EXCEPT ![c] = IF @ = "None" THEN "Success" ELSE @]
               /\ terminalCount' = [terminalCount EXCEPT ![c] = IF result[c] = "None" THEN @ + 1 ELSE @]
               /\ UNCHANGED <<generation, mode, refs, queue, cleanup>>
Cleanup(c) == /\ mode[c] = "Releasing" /\ inflight[c] = 0 /\ cleanup[c]
              /\ cleanup' = [cleanup EXCEPT ![c] = FALSE]
              /\ mode' = [mode EXCEPT ![c] = "Free"]
              /\ UNCHANGED <<generation, refs, queue, inflight, result, terminalCount>>
Advance(c) == /\ mode[c] = "Free" /\ result[c] # "None"
              /\ generation[c] < MaxGeneration
              /\ generation' = [generation EXCEPT ![c] = @ + 1]
              /\ result' = [result EXCEPT ![c] = "None"]
              /\ terminalCount' = [terminalCount EXCEPT ![c] = 0]
              /\ UNCHANGED <<mode, refs, queue, inflight, cleanup>>
Next == \E c \in Controllers : Acquire(c) \/ Dup(c) \/ CloseDup(c) \/ Enqueue(c) \/
        Submit(c) \/ Revoke(c) \/ Cleanup(c) \/ Advance(c) \/
        (\E g \in 1..MaxGeneration : Reply(c, g))
Spec == Init /\ [][Next]_vars

TypeOK == /\ generation \in [Controllers -> 1..MaxGeneration]
          /\ mode \in [Controllers -> {"Free", "Owned", "Releasing"}]
          /\ refs \in [Controllers -> 0..2]
          /\ inflight \in [Controllers -> 0..MaxGeneration]
          /\ cleanup \in [Controllers -> BOOLEAN]
          /\ result \in [Controllers -> {"None", "Success", "Cancelled"}]
          /\ terminalCount \in [Controllers -> 0..1]
Bounded == \A c \in Controllers : Len(queue[c]) <= QueueBound
NotFreeWithObligation == \A c \in Controllers : mode[c] = "Free" =>
       (inflight[c] = 0 /\ ~cleanup[c] /\ Len(queue[c]) = 0 /\ refs[c] = 0)
Identity == \A c \in Controllers :
       (inflight[c] = 0 \/ inflight[c] = generation[c]) /\
       (\A i \in 1..Len(queue[c]) : queue[c][i] = generation[c])
NoQueuedAfterRevoke == \A c \in Controllers : mode[c] # "Owned" => Len(queue[c]) = 0
=============================================================================
