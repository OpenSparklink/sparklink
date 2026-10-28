----------------------- MODULE SSAPClientObligation -----------------------
EXTENDS Naturals, Integers, Sequences
CONSTANTS Parts, AuthorDeadline, DrainBudget, Horizon, RequireAll, RenewDrain
VARIABLES now, active, admitted, first, drain, author, reply, result,
          terminalCount, successParts, successTime, admissionTimes
vars == <<now, active, admitted, first, drain, author, reply, result,
          terminalCount, successParts, successTime, admissionTimes>>

\* One already identity-bound client request. Native admission, locks, RX
\* authentication, credit/NOCP and lifetime reuse are deliberately OUTSIDE
\* this model. An actor retirement does not assert their obligations vanished.
Init == /\ now = 0 /\ active = TRUE /\ admitted = 0
        /\ first = -1 /\ drain = -1 /\ author = TRUE /\ reply = TRUE
        /\ result = "none" /\ terminalCount = 0
        /\ successParts = 0 /\ successTime = 0 /\ admissionTimes = <<>>

Clock == /\ now < Horizon /\ now' = now + 1
         /\ UNCHANGED <<active, admitted, first, drain, author, reply, result,
                        terminalCount, successParts, successTime, admissionTimes>>

\* Wire success here is software admission of ONE SSAP part, never USB
\* completion or peer receipt. Its original Pending.deadline still applies
\* after the author closes; only physical drain has a separate first bound.
Admit == /\ active /\ admitted < Parts /\ now < AuthorDeadline
         /\ admitted' = admitted + 1
         /\ first' = IF admitted = 0 THEN now ELSE first
         /\ drain' = IF admitted = 0 \/ RenewDrain THEN now + DrainBudget ELSE drain
         /\ admissionTimes' = Append(admissionTimes, now)
         /\ UNCHANGED <<now, active, author, reply, result, terminalCount,
                        successParts, successTime>>

Cancel == /\ active /\ author /\ result = "none"
          /\ author' = FALSE /\ result' = "cancelled"
          /\ terminalCount' = terminalCount + 1
          /\ UNCHANGED <<now, active, admitted, first, drain, reply,
                         successParts, successTime, admissionTimes>>

AuthorTimeout == /\ active /\ author /\ result = "none" /\ now >= AuthorDeadline
                 /\ author' = FALSE /\ result' = "timeout"
                 /\ terminalCount' = terminalCount + 1
                 /\ UNCHANGED <<now, active, admitted, first, drain, reply,
                                successParts, successTime, admissionTimes>>

\* retire_client_wait: remove definitely unadmitted work, otherwise retain
\* the same stream/deadline. Dropping reply never makes a new request valid.
Withdraw == /\ active /\ reply /\ (~author \/ now >= AuthorDeadline)
            /\ reply' = FALSE /\ active' = (admitted > 0)
            /\ result' = IF author /\ result = "none" THEN "failure" ELSE result
            /\ terminalCount' = IF author /\ result = "none"
                                  THEN terminalCount + 1 ELSE terminalCount
            /\ UNCHANGED <<now, admitted, first, drain, author,
                           successParts, successTime, admissionTimes>>

Wake == IF admitted = 0 THEN AuthorDeadline
        ELSE IF admitted < Parts \/ (reply /\ author)
             THEN AuthorDeadline ELSE drain

\* The real actor may retire when an unfinished Pending reaches its author
\* deadline, or wait to the first drain bound after complete admission.
Expire == /\ active /\ now >= Wake
          /\ active' = FALSE /\ reply' = FALSE
          /\ result' = IF author /\ result = "none" THEN "failure" ELSE result
          /\ terminalCount' = IF author /\ result = "none"
                                THEN terminalCount + 1 ELSE terminalCount
          /\ UNCHANGED <<now, admitted, first, drain, author,
                         successParts, successTime, admissionTimes>>

\* Validated response availability is optional, with no fairness assumption
\* about firmware response. This action abstracts validation, not decoding.
Response == /\ active /\ admitted > 0 /\ (~RequireAll \/ admitted = Parts)
            /\ now < drain /\ active' = FALSE /\ reply' = FALSE
            /\ result' = IF reply /\ author /\ now < AuthorDeadline /\ result = "none"
                         THEN "success" ELSE result
            /\ terminalCount' = IF reply /\ author /\ now < AuthorDeadline /\ result = "none"
                                  THEN terminalCount + 1 ELSE terminalCount
            /\ successParts' = IF reply /\ author /\ now < AuthorDeadline /\ result = "none"
                                THEN admitted ELSE successParts
            /\ successTime' = IF reply /\ author /\ now < AuthorDeadline /\ result = "none"
                               THEN now ELSE successTime
            /\ UNCHANGED <<now, admitted, first, drain, author, admissionTimes>>

Next == Clock \/ Admit \/ Cancel \/ AuthorTimeout \/ Withdraw \/ Expire \/ Response
Spec == Init /\ [][Next]_vars /\ WF_vars(Clock) /\ WF_vars(Expire)

TypeOK == /\ now \in 0..Horizon /\ active \in BOOLEAN /\ author \in BOOLEAN /\ reply \in BOOLEAN
          /\ admitted \in 0..Parts /\ first \in -1..Horizon /\ drain \in -1..(Horizon+DrainBudget)
          /\ result \in {"none", "success", "failure", "cancelled", "timeout"}
          /\ terminalCount \in Nat /\ successParts \in 0..Parts /\ successTime \in 0..Horizon
          /\ admissionTimes \in Seq(0..Horizon)
NoPrematureSuccess == result = "success" => successParts = Parts
NoLateSuccess == result = "success" => successTime < AuthorDeadline /\ successTime < drain
DrainNotRenewed == admitted > 0 => drain = first + DrainBudget
SingleTerminal == terminalCount <= 1
OriginalAdmissionBound == /\ Len(admissionTimes) = admitted
                          /\ \A i \in 1..Len(admissionTimes) : admissionTimes[i] < AuthorDeadline
NoCancelledSuccess == result \in {"cancelled", "timeout"} => ~author
EventuallyResolved == <> (~active)
=============================================================================
