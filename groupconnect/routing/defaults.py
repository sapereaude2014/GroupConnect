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
    "Direct command, explicit task request, follow-up amendment to an ongoing task, "
    "or reply answering a bot's earlier question/offer — expects immediate bot action."
)
DEFAULT_WAIT_CRITERIA = (
    "Open question, inquiry, data lookup, advice request, or everyday problem asked to the group, "
    "where humans should get a chance to reply first before bots intervene."
)
DEFAULT_DROP_CRITERIA = (
    "Interpersonal conversation between humans, emotional venting, casual banter, "
    "or statements requiring no bot response."
)
DEFAULT_ASSIGNMENT_CRITERIA = (
    "Should {bot} respond to this message?\n"
    "- Yes if the sender directly addresses {bot} ({aliases}), asks multiple bots to assist (e.g. 'both', 'all'), "
    "follows up on an ongoing exchange with {bot}, or requests a task matching {bot}'s role ({role}).\n"
    "- No if addressed to another bot, merely mentioned in passing, "
    "or continuing a conversation with someone else."
)

DEFAULT_RULE_TEMPLATES: Dict[str, str] = {
    "group": DEFAULT_GROUP_DESCRIPTION,
    "immediate": DEFAULT_IMMEDIATE_CRITERIA,
    "wait": DEFAULT_WAIT_CRITERIA,
    "drop": DEFAULT_DROP_CRITERIA,
    "assignment": DEFAULT_ASSIGNMENT_CRITERIA,
}

DEFAULT_JEV_CHOICE_INSTRUCTIONS = """Group Context: {group}

Evaluate conversational timing and urgency for assistant bots (first match wins):
1. BOT DIALOGUE CONTINUATION & DIRECT COMMAND (immediate):
   Direct command, task request, or follow-up response to a bot's earlier offer.
2. OBJECTIVE INQUIRY & RECOMMENDATION (wait_silence):
   Open question, data lookup, or advice asked to the group where humans should reply first.
3. INTERPERSONAL CHITCHAT / SILENCE (drop):
   Human conversation, venting, or banter requiring no bot intervention.
"""

# Decision-model engines (questionnaire contract: 1 orthogonal Choice + N Noul per call).
# Google Gemini Decisions API (Beta): POST {DECISIONS_BASE_URL}/decisions
DECISIONS_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DECISIONS_DEFAULT_MODEL = "gemini-decision-1"

