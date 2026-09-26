"""修复复验：wait 加回 group-at-large 限定 + 第三人称转述承接。
重点：破口句「咱晚上吃啥好呢」应回到 drop；回归句「让他早点睡」应回到 wait。
连跑 3 轮看稳定性。用法: python3 .temp/probe_verify.py
"""
import asyncio, sys
sys.path.insert(0, '/home/server/repos/GroupConnect')
from groupconnect.routing.router import AutonomousConfig, AutonomousArbiter

CASES = [
    ("咱晚上吃啥好呢", "xiaorou", "破口句:对配偶商议(应drop)"),
    ("让他早点睡", "xiaorou", "回归句:第三人称转述(应wait→管家)"),
    ("买的蓝莓没熟咋办？", "xiaorou", "求助实案(应wait)"),
    ("这蓝莓也太酸了，白买了", "xiaorou", "吐槽(应drop)"),
    ("咱晚上吃火锅吧", "xiaorou", "夫妻提议(应drop)"),
    ("小迷妹，管家最近智力有点低下，他改完你去看看改对了吗。", "Zheng Ma", "呼唤语实案1(应总管)"),
    ("小迷妹 还是你上吧。管家智力有点低。", "Zheng Ma", "呼唤语实案2(应总管)"),
    ("帮我查下明天去杭州的高铁", "Zheng Ma", "明确指令(应管家immediate)"),
]

async def main():
    cfg = AutonomousConfig('/home/server/mama_family_files/.agents/groupconnect.yaml')
    arb = AutonomousArbiter(cfg)
    for rnd in range(3):
        print(f"===== 第 {rnd+1} 轮 =====")
        for text, sender, note in CASES:
            res = await arb.classify(text, sender, "")
            print(f"[{note}] 「{text}」 → target={res.get('target_bot')} "
                  f"bots={res.get('target_bots')} urgency={res.get('urgency')} conf={res.get('confidence')}")

if __name__ == "__main__":
    asyncio.run(main())
