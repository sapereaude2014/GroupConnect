"""
Built-in defaults for GroupConnect Autonomous Routing.
Contains baked-in decision rules, prompt templates, and noise filters.
Users do NOT need to maintain external rule/prompt files unless performing advanced overrides.
"""

from typing import Dict, List

DEFAULT_NOISE_PATTERNS: List[str] = [
    r"^(好的|嗯|哦|哈|对|收到|行|ok|OK)+[~！!。\s]*$",
    r"^[\W_]+$",
    r"^/(stop|restart|status)(@\w+)?(\s.*)?$",
]

DEFAULT_ALIAS_DROP_PATTERNS: List[str] = [
    r"(我|人家)(就?是|叫)(你的|一个小?一个?)?{alias}",
    r"(是|当)(了|上)?(你的|一个小?一个?)?{alias}(啦|了|呀|哟|嘛|咯|~|！|!)",
    r"{alias}(说的?对|说得好|说得对|说的也是|厉害|牛|强|不错|棒|给力)",
    r"{alias}(刚才|之前|刚刚|已经)(说|做|回|答|提|讲|回?复)",
    r"{alias}(也|都)(是(这么|那样)?(说|看|想)|说|做|觉得|认为|建议|推荐)(的|了|得)?",
    r"{alias}(也|都|就)?(是|算|叫).*(老铁|老妹|一对|一伙|搭档|机器人|程序|小弟|助手|大哥|AI|ai)",
    r"(我和|跟|把)?{alias}.*(是|才?是).*(一对|一伙|搭档|朋友|哥们|闺蜜|老铁|老妹)",
    r"{alias}(真|太|挺)(逗|搞笑|好玩|可爱|皮)",
    r"call me {alias}",
    r"I am {alias}",
]

DEFAULT_GROUP_DESCRIPTION = (
    "Private group chat. Configured assistant bots handle different specialized tasks."
)
DEFAULT_IMMEDIATE_CRITERIA = (
    "Reply to {bot}'s earlier question/offer, or an imperative instruction matching: {role}"
)
DEFAULT_WAIT_CRITERIA = (
    "A question needing data, information, or recommendations matching: {role}"
)
DEFAULT_DROP_CRITERIA = (
    "Interpersonal conversation between group members, not directed at any bot"
)
DEFAULT_PARALLEL_CRITERIA = (
    "The sender explicitly wants {bot} ({role}) to participate, respond, or collaborate "
    "simultaneously alongside other assistants (e.g. coordinative phrases: 'A and B both', 'together'). "
    "Not causative dispatch ('A ask B to do X')."
)

DEFAULT_RULE_TEMPLATES: Dict[str, str] = {
    "group": DEFAULT_GROUP_DESCRIPTION,
    "immediate": DEFAULT_IMMEDIATE_CRITERIA,
    "wait": DEFAULT_WAIT_CRITERIA,
    "drop": DEFAULT_DROP_CRITERIA,
    "parallel": DEFAULT_PARALLEL_CRITERIA,
}

DEFAULT_ROUTING_RULES_MD = """# Autonomous Routing Decision Rules

Decision Rules (Evaluate in order, first match wins):
1. BOT DIALOGUE CONTINUATION (Highest Priority):
   If recent context shows a Bot asked a question, offered options, or proposed a plan, and the current message is an acknowledgment, confirmation, decision (e.g. "option A", "okay", "yes", "confirmed"), or a follow-up question/feedback directed to that bot:
   -> Assign to THAT bot immediately.

2. FUNCTIONAL COMMAND:
   A direct functional instruction for a bot (its core job: device control, data lookup, scheduling, alarms/reminders):
   -> Assign to the matching bot immediately.

3. INTERPERSONAL CHITCHAT:
   Judge whether the humans are talking TO each other:
   - TRUE CHITCHAT (Silence -> drop):
     * Direct address to another human member using 2nd-person pronouns or intimate/personal nicknames.
     * Direct answers or reactions to another human's preceding message.
     * Pure emotional venting or daily trivialities without action requests.
     * Banter mentioning bots in third-person narrative.
   - NOT CHITCHAT (Must NOT drop; route to the matching bot):
     * 3rd-person reference: if sender refers to another human member in 3rd person, addressee is the assistant.
     * Administrative actions toward the shared assistant: bookkeeping, queries, verification.
   -> Silence only for TRUE CHITCHAT.

4. OBJECTIVE INQUIRY & RECOMMENDATION:
   An explicit question asking for objective knowledge, schedules, data, or recommendations:
   -> Assign to the matching bot with wait_silence (leaves social space for humans to reply first).

5. MULTI-BOT DISPATCH (When multiple bot aliases appear in one message):
   - DISPATCH: One bot is asked to handle a task involving another bot -> Assign to the DISPATCHER only.
   - PARALLEL: The sender wants multiple specific bots to respond together -> Assign all addressed bots in target_bots with immediate urgency.
"""

DEFAULT_LLM_PROMPT_TEMPLATE = """You are the single arbiter of a private group chat.
Decide whether an assistant bot should reply WITHOUT being explicitly @-mentioned.

Roles of the bots:
{ROLES}

Recent conversation:
{CONTEXT}

Current message from {SENDER}: "{TEXT}"
{ALIAS_HINT}

{RULES_SECTION}

Output STRICT JSON only, no other text:
{"target_bots": ["<bot_name>"], "target_bot": "<primary_bot_name>"|"none", "urgency": "immediate"|"wait_silence"|"drop", "confidence": 0.0}
"""



