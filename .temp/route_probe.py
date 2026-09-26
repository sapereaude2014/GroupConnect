"""临时实测脚本：用生产配置跑三条对照消息，验证路由行为。
用法: python3 .temp/route_probe.py
读取 /home/server/mama_family_files/.agents/groupconnect.yaml
"""
import asyncio, sys
sys.path.insert(0, '/home/server/repos/GroupConnect')
from groupconnect.routing.router import AutonomousConfig, AutonomousArbiter

CASES = [
    ("买的蓝莓没熟咋办？", "xiaorou", "实案求助"),
    ("这蓝莓也太酸了，白买了", "xiaorou", "纯吐槽防火墙"),
    ("帮我查下明天去杭州的高铁", "Zheng Ma", "明确指令"),
]

async def main(label):
    cfg = AutonomousConfig('/home/server/mama_family_files/.agents/groupconnect.yaml')
    arb = AutonomousArbiter(cfg)
    print(f"\n========== {label} ==========")
    print(f"drop 生效版: {'自定义' if 'drop' in cfg.custom_rules else '默认'}")
    print(f"wait 生效版: {'自定义' if 'wait' in cfg.custom_rules else '默认'}")
    print(f"assignment 生效版: {'自定义' if 'assignment' in cfg.custom_rules else '默认'}")
    for text, sender, note in CASES:
        res = await arb.classify(text, sender, "")
        print(f"\n[{note}] 「{text}」")
        print(f"  → target={res.get('target_bot')} bots={res.get('target_bots')} "
              f"urgency={res.get('urgency')} conf={res.get('confidence')} src={res.get('source')}")

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "基线"))
