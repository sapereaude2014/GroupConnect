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
    "Interpersonal conversation between group members not directed at any bot "
    "(direct 2nd-person address to another human, reactions to another human's preceding message, "
    "pure emotional venting without action requests, or 3rd-person banter about bots). "
    "NOT drop-worthy: referring to another member in 3rd-person to record/query tasks, or administrative requests toward the shared assistant."
)
DEFAULT_ASSIGNMENT_CRITERIA = (
    "Whether the current message falls within {bot}'s responsibility or requires {bot} ({role}) to handle it. "
    "Return a high score if the message is a direct question, command, or request that matches {bot}'s domain; "
    "return a low score if it is casual conversation between humans with no action request toward {bot}."
)

DEFAULT_RULE_TEMPLATES: Dict[str, str] = {
    "group": DEFAULT_GROUP_DESCRIPTION,
    "immediate": DEFAULT_IMMEDIATE_CRITERIA,
    "wait": DEFAULT_WAIT_CRITERIA,
    "drop": DEFAULT_DROP_CRITERIA,
    "assignment": DEFAULT_ASSIGNMENT_CRITERIA,
}

DEFAULT_ROUTING_RULES_MD = """# Autonomous Routing Decision Rules
Group Context: {group}

Decision Rules (Evaluate in order, first match wins):
1. BOT DIALOGUE CONTINUATION & DIRECT COMMAND (urgency = "immediate"):
   - If recent context shows a Bot asked a question, offered options, or proposed a plan, and the current message is an acknowledgment, confirmation, decision (e.g. "option A", "okay", "yes", "confirmed"), or a follow-up question/feedback directed to that bot -> Assign to THAT bot immediately.
   - Direct instruction criteria: {immediate}

2. INTERPERSONAL CHITCHAT / SILENCE (urgency = "drop", target_bot = "none"):
   - {drop}

3. OBJECTIVE INQUIRY & RECOMMENDATION (urgency = "wait_silence"):
   - {wait} (leaves social space for humans to reply first).

4. MULTI-BOT DISPATCH vs PARALLEL:
   - DISPATCH: One bot is asked to handle a task involving another bot -> Assign to the DISPATCHER only.
   - PARALLEL: Multiple bots should respond simultaneously -> Each bot's Noul independently determines if it should participate.
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

Output STRICT JSON only (use empty list [] when urgency is "drop"):
{"target_bots": ["<bot_name>"]|[], "urgency": "immediate"|"wait_silence"|"drop", "confidence": 0.0}
"""



