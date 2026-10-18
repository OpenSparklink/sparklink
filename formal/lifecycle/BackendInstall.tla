-------------------------- MODULE BackendInstall --------------------------
EXTENDS Naturals, FiniteSets
CONSTANTS Slots, Candidates, MaxGeneration, WeakGeneration
VARIABLES phase, generation, reported, nextGeneration, candidatePhase, candidateSlot, candidateGeneration
vars == <<phase, generation, reported, nextGeneration, candidatePhase, candidateSlot, candidateGeneration>>
Init == /\ phase = [s \in Slots |-> "Free"]
        /\ generation = [s \in Slots |-> 0]
        /\ reported = [s \in Slots |-> 0]
        /\ nextGeneration = 1
        /\ candidatePhase = [c \in Candidates |-> "Idle"]
        /\ candidateSlot = [c \in Candidates |-> CHOOSE s \in Slots : TRUE]
        /\ candidateGeneration = [c \in Candidates |-> 0]
Reserve(s) == /\ phase[s] = "Free" /\ nextGeneration <= MaxGeneration
              /\ phase' = [phase EXCEPT ![s] = "Reserved"]
              /\ generation' = [generation EXCEPT ![s] = nextGeneration]
              /\ reported' = [reported EXCEPT ![s] = 0]
              /\ nextGeneration' = nextGeneration + 1
              /\ UNCHANGED <<candidatePhase, candidateSlot, candidateGeneration>>
Snapshot(c,s) == /\ candidatePhase[c] \in {"Idle","Done"} /\ phase[s] = "Reserved"
                 /\ candidatePhase' = [candidatePhase EXCEPT ![c] = "Building"]
                 /\ candidateSlot' = [candidateSlot EXCEPT ![c] = s]
                 /\ candidateGeneration' = [candidateGeneration EXCEPT ![c] = generation[s]]
                 /\ UNCHANGED <<phase,generation,reported,nextGeneration>>
Construct(c) == /\ candidatePhase[c] = "Building"
                /\ candidatePhase' = [candidatePhase EXCEPT ![c] = "Constructed"]
                /\ UNCHANGED <<phase,generation,reported,nextGeneration,candidateSlot,candidateGeneration>>
FailConstruction(c) == /\ candidatePhase[c] = "Building"
                       /\ candidatePhase' = [candidatePhase EXCEPT ![c] = "Done"]
                       /\ UNCHANGED <<phase,generation,reported,nextGeneration,candidateSlot,candidateGeneration>>
CanPublish(c) == /\ phase[candidateSlot[c]] = "Reserved"
                 /\ (WeakGeneration \/ generation[candidateSlot[c]] = candidateGeneration[c])
Publish(c) == /\ candidatePhase[c] = "Constructed" /\ CanPublish(c)
              /\ phase' = [phase EXCEPT ![candidateSlot[c]] = "Live"]
              /\ reported' = [reported EXCEPT ![candidateSlot[c]] = candidateGeneration[c]]
              /\ candidatePhase' = [candidatePhase EXCEPT ![c] = "Done"]
              /\ UNCHANGED <<generation,nextGeneration,candidateSlot,candidateGeneration>>
Reject(c) == /\ candidatePhase[c] = "Constructed" /\ ~CanPublish(c)
             /\ candidatePhase' = [candidatePhase EXCEPT ![c] = "Done"]
             /\ UNCHANGED <<phase,generation,reported,nextGeneration,candidateSlot,candidateGeneration>>
Cancel(s,g) == /\ phase[s] = "Reserved" /\ generation[s] = g
               /\ phase' = [phase EXCEPT ![s] = "Free"]
               /\ UNCHANGED <<generation,reported,nextGeneration,candidatePhase,candidateSlot,candidateGeneration>>
BeginRetire(s) == /\ phase[s] \in {"Reserved","Live"}
                  /\ phase' = [phase EXCEPT ![s] = "Retiring"]
                  /\ UNCHANGED <<generation,reported,nextGeneration,candidatePhase,candidateSlot,candidateGeneration>>
FinishRetire(s) == /\ phase[s] = "Retiring"
                   /\ phase' = [phase EXCEPT ![s] = "Free"]
                   /\ UNCHANGED <<generation,reported,nextGeneration,candidatePhase,candidateSlot,candidateGeneration>>
Next == (\E s \in Slots : Reserve(s) \/ BeginRetire(s) \/ FinishRetire(s))
        \/ (\E c \in Candidates, s \in Slots : Snapshot(c,s))
        \/ (\E c \in Candidates : Construct(c) \/ FailConstruction(c) \/ Publish(c) \/ Reject(c))
        \/ (\E s \in Slots, g \in 1..MaxGeneration : Cancel(s,g))
Spec == Init /\ [][Next]_vars
TypeOK == /\ phase \in [Slots -> {"Free","Reserved","Live","Retiring"}]
          /\ generation \in [Slots -> 0..MaxGeneration]
          /\ reported \in [Slots -> 0..MaxGeneration]
          /\ nextGeneration \in 1..(MaxGeneration+1)
          /\ candidatePhase \in [Candidates -> {"Idle","Building","Constructed","Done"}]
          /\ candidateSlot \in [Candidates -> Slots]
          /\ candidateGeneration \in [Candidates -> 0..MaxGeneration]
LiveMetadataCurrent == \A s \in Slots : phase[s] = "Live" => reported[s] = generation[s]
=============================================================================
