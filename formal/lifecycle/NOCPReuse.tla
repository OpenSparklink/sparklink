----------------------------- MODULE NOCPReuse -----------------------------
EXTENDS Naturals
VARIABLES stage, lifetime, debt, oldDuplicate
vars == <<stage, lifetime, debt, oldDuplicate>>
Init == /\ stage = 0 /\ lifetime = 1 /\ debt = 1 /\ oldDuplicate = FALSE
OldComplete == /\ stage = 0 /\ debt' = 0 /\ oldDuplicate' = TRUE
               /\ stage' = 1 /\ UNCHANGED lifetime
Reuse == /\ stage = 1 /\ debt = 0 /\ lifetime' = 2 /\ debt' = 1
         /\ stage' = 2 /\ UNCHANGED oldDuplicate
Duplicate == /\ stage = 2 /\ oldDuplicate /\ debt' = 0 /\ stage' = 3
             /\ UNCHANGED <<lifetime, oldDuplicate>>
Next == OldComplete \/ Reuse \/ Duplicate
Spec == Init /\ [][Next]_vars
NoWrongRefill == ~(lifetime = 2 /\ stage = 3 /\ debt = 0)
=============================================================================
