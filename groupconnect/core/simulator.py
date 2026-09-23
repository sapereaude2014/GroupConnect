"""
GroupConnect Local Sandbox Simulator.
Allows offline testing and verification of Zero-@ routing decisions directly in the terminal,
without needing to send messages to a live Telegram group.
"""

import asyncio
import os
import sys
from typing import List, Optional

from groupconnect.core.config import GatewayConfig
from groupconnect.routing.router import AutonomousArbiter, AutonomousConfig


async def run_group_simulator(config: GatewayConfig) -> None:
    print("\n" + "=" * 65)
    print("💬 GroupConnect 本地群聊模拟沙盒 (Simulator)")
    print("=" * 65)
    print("无需连接真实的 Telegram 群组，直接在终端模拟群成员发言，验证 Zero-@ 决策与唤醒。")
    print("输入格式: `发送者: 消息文本` (例如: `Alice: 帮我查一下今天的天气`)")
    print("输入 `exit` 或按 `Ctrl+C` 退出沙盒。\n")

    acfg = config.autonomous_config
    if not acfg or not acfg.enabled:
        print("⚠️ 当前配置未启用 Zero-@ (zero_at: true)。已使用默认参数为您开启模拟。")
        acfg = AutonomousConfig({"enabled": True, "arbiter_bot": config.bot_username})

    arbiter = AutonomousArbiter(acfg)
    history: List[str] = []

    while True:
        try:
            user_input = input("🗣️ 模拟群聊 > ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                print("沙盒已退出。")
                break

            # Parse sender: text
            if ":" in user_input or "：" in user_input:
                sep = ":" if ":" in user_input else "："
                parts = user_input.split(sep, 1)
                sender = parts[0].strip()
                text = parts[1].strip()
            else:
                sender = "群友"
                text = user_input

            print(f"\n[消息捕获] 发送者: {sender} | 消息: \"{text}\"")

            context_str = "\n".join(history[-acfg.context_window_size:]) if history else "(无历史消息)"

            # 1. Sync Evaluation (L0 Noise & L1 Alias)
            sync_res = arbiter.evaluate_sync(text, sender, context=context_str)
            if sync_res is not None:
                urgency = sync_res.get("urgency")
                target = sync_res.get("target_bot", "none")
                targets = sync_res.get("target_bots", [target] if target != "none" else [])
                stage = sync_res.get("source", "L0/L1")
                print(f"  ⚡ 阶段: {stage} (0-Token 命中)")
                print(f"  🎯 判定目标: {targets or target} | 响应紧急度: {urgency}")
                if urgency == "drop":
                    print("  🤫 动作: 保持静默 (判定为噪音/自指/闲聊过滤)\n")
                else:
                    print(f"  📢 动作: 触发唤醒 -> @{target}\n")
                if stage != "noise":
                    history.append(f"{sender}: {text}")
                continue

            # 2. Classifier Evaluation (L3 LLM)
            print("  🧠 正在调用 Zero-@ 分类器进行语义分析...")

            try:
                clf_res = await arbiter.classify(text, sender, context=context_str)
                urgency = clf_res.get("urgency", "drop")
                target = clf_res.get("target_bot", "none")
                targets = clf_res.get("target_bots", [target] if target != "none" else [])
                conf = clf_res.get("confidence", 0.0)

                print(f"  🎯 分类结果: 目标: {targets or target} | 紧急度: {urgency} | 置信度: {conf}")
                if urgency == "immediate":
                    print(f"  ⚡ 动作: 即刻抢答 (0~1s 内响应)")
                elif urgency == "wait_silence":
                    print(f"  ⏳ 动作: 静默等待人类发言 ({acfg.silence_secs}s 后若无打断则抢答)")
                else:
                    print(f"  🤫 动作: 保持静默 (判定为人际闲聊或无需 Bot 介入)")

            except Exception as e:
                print(f"  ❌ 分类器调用失败: {e}")

            # Record history
            history.append(f"{sender}: {text}")
            print()

        except (KeyboardInterrupt, EOFError):
            print("\n沙盒已退出。")
            break
