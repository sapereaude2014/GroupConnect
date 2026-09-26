"""顺序对照实验：drop 在上 vs wait 在上（wait 保留 group-at-large + third-person relayed 修复）。
只 patch 本进程内常量，不动生产代码。用法: python3 .temp/probe_order_ab.py
"""
import asyncio, sys
sys.path.insert(0, '/home/server/repos/GroupConnect')
import groupconnect.routing.router as R
from groupconnect.routing.router import AutonomousConfig, AutonomousArbiter

DROP_FIRST = """# Autonomous Routing Timing Rules
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

2. INTERPERSONAL CHITCHAT / SILENCE (urgency = "drop"):
   - Human-to-human conversation, venting, or banter (see the drop option criteria).

3. OBJECTIVE INQUIRY & RECOMMENDATION (urgency = "wait_silence"):
   - Open questions, help requests, recommendations, and everyday problem-solving
     addressed to the group at large, where humans should reply first
     (see the wait option criteria).
"""

CASES = [
    ("咱晚上吃啥好呢", "xiaorou", "对配偶商议(防火墙关键)"),
    ("让他早点睡", "xiaorou", "第三人称转述"),
    ("买的蓝莓没熟咋办？", "xiaorou", "求助实案"),
    ("这蓝莓也太酸了，白买了", "xiaorou", "纯吐槽"),
    ("咱晚上吃火锅吧", "xiaorou", "夫妻提议"),
    ("老婆你真好看", "Zheng Ma", "亲昵"),
    ("帮我查下明天去杭州的高铁", "Zheng Ma", "明确指令"),
    ("小迷妹，管家最近智力有点低下，他改完你去看看改对了吗。", "Zheng Ma", "呼唤语实案(应总管)"),
]

async def run(cfg):
    arb = AutonomousArbiter(cfg)
    for text, sender, note in CASES:
        res = await arb.classify(text, sender, "")
        print(f"[{note}] 「{text}」 → target={res.get('target_bot')} "
              f"urgency={res.get('urgency')} conf={res.get('confidence')}")

async def main():
    cfg = AutonomousConfig('/home/server/mama_family_files/.agents/groupconnect.yaml')
    for label in ("第1轮", "第2轮", "第3轮"):
        print(f"===== DROP 在上 · {label} =====")
        R.DEFAULT_JEV_CHOICE_INSTRUCTIONS = DROP_FIRST
        await run(cfg)

if __name__ == "__main__":
    asyncio.run(main())
