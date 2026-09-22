# Autonomous Routing Decision Rules

Single source of truth for classifier wording, parsed by groupconnect/routing/router.py.
The prose above the template sections is classifier instructions; the '## <key>'
sections below are per-choice wording, not instructions.

Decision Rules (Evaluate in order, first match wins):
1. BOT DIALOGUE CONTINUATION (Highest Priority):
   If recent context shows a Bot asked a question, offered options, or proposed a plan, and the current message is an acknowledgment, confirmation, decision (e.g. "option A", "okay", "yes", "confirmed"), or a follow-up question/feedback directed to that bot:
   -> Assign to THAT bot immediately.

2. FUNCTIONAL COMMAND:
   A direct functional instruction for a bot (its core job: device control, data lookup, scheduling, alarms/reminders):
   -> Assign to the matching bot immediately.

3. INTERPERSONAL CHITCHAT (Human-to-Human Talk vs Assistant Command):
   Judge whether the humans are talking TO each other:
   - TRUE CHITCHAT (Silence -> drop):
     * Direct address to another human member using 2nd-person pronouns or intimate/personal nicknames.
     * Direct answers or reactions to another human's preceding message.
     * Pure emotional venting or daily trivialities without action requests.
     * Banter mentioning bots in third-person narrative (talking ABOUT the bots, not TO them).
   - NOT CHITCHAT (Must NOT drop; route to the matching bot):
     * 3rd-person reference: if the sender refers to another human member in the 3rd person (by name or "he/she"), the addressee cannot be that person - it is the assistant.
     * Administrative actions toward the shared assistant: bookkeeping, scoring, logging, queries, verification.
   -> Silence only for TRUE CHITCHAT.

4. OBJECTIVE INQUIRY & RECOMMENDATION:
   An explicit question asking for objective knowledge, schedules, data, or recommendations:
   -> Assign to the matching bot with wait_silence (leaves social space for humans to reply first).

5. MULTI-BOT DISPATCH (When multiple bot aliases appear in one message):
   - DISPATCH: One bot is asked to handle a task involving another bot (e.g. "assistant, ask helper to check this").
     The addressee (dispatcher) is the first-mentioned bot; the other bot is the task target, NOT a wake target.
     -> Assign to the DISPATCHER only.
   - PARALLEL: The sender wants ALL mentioned bots to respond together (e.g. "assistant and helper both look at this").
     -> Assign target_bot "all" with immediate urgency.
   - Distinguish by grammar: causative markers (ask/make/have...go/do) = dispatch; coordinative markers (and/with...both/together) = parallel.

# Classifier Templates

## immediate
Reply to {bot}'s earlier question/offer, or an imperative instruction matching: {role}

## wait
A question needing data, information, or recommendations matching: {role}

## drop
Direct human-to-human talk only: 2nd-person pronouns, intimate/personal address, reactions to another human's previous message, or pure venting with no action request. NOT drop-worthy: 3rd-person references to another human member (in a small group that means the speaker is addressing the assistant bots); administrative actions (bookkeeping, logging, queries, verification) addressed to the shared assistant space.

## group
A private group chat whose human members share one or more specialized assistant bots.

## parallel
The sender explicitly wants {bot} ({role}) to participate, respond, or collaborate simultaneously alongside other assistants (e.g. coordinative phrases: "A and B both", "A with B together", "both of you"). Causative dispatch ("A asks B to...") where only A is the dispatcher does NOT trigger parallel response.
