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
    "A direct command, explicit task request, or a reply answering a bot's earlier "
    "question/offer — the sender expects an immediate bot response."
)
DEFAULT_WAIT_CRITERIA = (
    "An open question, help request, data lookup, recommendation, or everyday problem "
    "seeking advice or a solution — asked to the group at large, including messages "
    "phrased as complaints (e.g. what to do about something broken or unripe) or "
    "third-person requests relayed through the group — where humans should get a "
    "chance to reply first, and bots pick it up only if nobody does."
)
DEFAULT_DROP_CRITERIA = (
    "Interpersonal conversation between group members that seeks no answer or "
    "action from any bot — direct 2nd-person address to another human, reactions to "
    "another human's preceding message, casual banter, emotional venting, or sharing daily plans."
)
DEFAULT_ASSIGNMENT_CRITERIA = (
    "Evaluate whether {bot} should respond to this message. "
    "Rules for scoring: "
    "1. DIRECT ADDRESS / DISPATCH: If the sender directly addresses or names {bot} ({aliases}) to talk to {bot} or assign a task (e.g. '{bot}, ...'), score HIGH (0.8-1.0), regardless of topic. "
    "2. THIRD-PERSON OBJECT: If {bot} is merely mentioned in 3rd-person as a topic, target of critique, or work object by someone addressing another bot (e.g. 'A, go check {bot}'), score LOW (~0.1-0.2). "
    "3. PARALLEL: If the sender asks multiple bots to respond together (e.g. 'both', 'all'), all mentioned bots score HIGH. "
    "4. UNNAMED: When no bot is explicitly named, score by how well the message matches {bot}'s responsibility ({role})."
)

DEFAULT_RULE_TEMPLATES: Dict[str, str] = {
    "group": DEFAULT_GROUP_DESCRIPTION,
    "immediate": DEFAULT_IMMEDIATE_CRITERIA,
    "wait": DEFAULT_WAIT_CRITERIA,
    "drop": DEFAULT_DROP_CRITERIA,
    "assignment": DEFAULT_ASSIGNMENT_CRITERIA,
}

DEFAULT_JEV_CHOICE_INSTRUCTIONS = """# Autonomous Routing Timing Rules
Group Context: {group}

Evaluate the conversational urgency and response timing (immediate / wait / drop)
based on social context and conversational rhythm.

Decision Rules (Evaluate in order, first match wins):
1. BOT DIALOGUE CONTINUATION & DIRECT COMMAND (urgency = "immediate"):
   - If recent context shows a bot asked a question, offered options, or proposed a
     plan, and the current message is an acknowledgment, confirmation, decision
     (e.g. "option A", "okay", "yes", "confirmed"), or a follow-up directed to
     that bot -> immediate.
   - Or the message is a direct command / imperative task request (see the
     immediate option criteria).

2. OBJECTIVE INQUIRY & RECOMMENDATION (urgency = "wait_silence"):
   - Open questions, help requests, recommendations, and everyday problem-solving
     addressed to the group at large, where humans should reply first
     (see the wait option criteria).

3. INTERPERSONAL CHITCHAT / SILENCE (urgency = "drop"):
   - Human-to-human conversation, venting, or banter (see the drop option criteria).
"""

DEFAULT_ROUTING_RULES_MD = """# Autonomous Routing Decision Rules
Group Context: {group}

Decision Rules (Evaluate in order, first match wins):
1. BOT DIALOGUE CONTINUATION & DIRECT COMMAND (urgency = "immediate"):
   - If recent context shows a bot asked a question, offered options, or proposed a
     plan, and the current message is an acknowledgment, confirmation, decision
     (e.g. "option A", "okay", "yes", "confirmed"), or a follow-up directed to
     that bot -> Assign to THAT bot in target_bots with urgency "immediate".
   - If the message is a direct command or imperative task request matching a bot's
     role -> Assign to the matching bot(s) in target_bots with urgency "immediate".
   - Direct instruction criteria: {immediate}

2. OBJECTIVE INQUIRY & RECOMMENDATION (urgency = "wait_silence"):
   - If the message is an open question, data lookup, or recommendation request
     addressed to the group at large, matching a bot's role -> Assign to the matching
     bot(s) in target_bots with urgency "wait_silence" (leaves social space for
     humans to reply first).
   - Inquiry criteria: {wait}

3. INTERPERSONAL CHITCHAT / SILENCE (urgency = "drop", target_bots = []):
   - {drop}

4. MULTI-BOT ASSIGNMENT & DISPATCH:
   - DISPATCH: One bot is asked to handle a task involving another bot (e.g. "A, ask B to do X") -> Assign to the DISPATCHER bot only.
   - PARALLEL: The sender explicitly wants multiple bots to participate or collaborate (e.g. "A and B both look at this", "everyone check this") -> Assign all addressed bots in target_bots with urgency "immediate".
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



