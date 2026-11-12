"""
Autonomous Routing (免@自主感知唤醒) for GroupConnect.

Architecture: Single-Arbiter + Symmetric Observers.
- Exactly ONE bot process (the arbiter, e.g. primary_bot) performs all
  semantic decisions (alias bypass / decision-model tri-state classification).
- The decision is broadcast ONCE via the existing CrossBotRelay IPC.
- Both processes run the SAME observer code: if target_bot == self -> arm a
  countdown window; any other human message during the window cancels it;
  otherwise dispatch with reply anchoring.

Decision-Model Classifiers (`zero_at.classifier.engine`): jev | decisions.
- Both engines speak the SAME questionnaire contract — orthogonal Choice
  (timing) + Noul (assignment) evaluated against a shared state — so question
  building, throttled transport, and arbitration are engine-agnostic; a
  provider is just a thin transport adapter.
- `jev`: TypeSafe systemone endpoint (jev-latest, JEV_API_KEY).
- `decisions`: Google Gemini Decisions API (gemini-decision-1,
  GEMINI_ROUTER_API_KEY, POST /v1beta/decisions).
- Choice (single-select, fixed 3 options): judges ONLY the interaction
  timing / social context (immediate / wait / drop) — independent of bot
  identity, so probabilities never split across bots.
- Noul (per-bot yes/no): each bot independently evaluates "does this
  message need me to handle it?" — the assignment dimension.
- Dynamic threshold (one knob): when Choice says respond, the Noul gate
  relaxes to confidence_threshold × 2/3 (e.g. 0.40) to prevent false
  silences; when Choice says drop, the bar interpolates by the drop's own
  certainty — a fully confident drop keeps the strict confidence_threshold
  (e.g. 0.60, chitchat firewall unchanged), while an uncertain drop slides
  toward the relaxed bar so strong Noul claims can still rescue it.
- Layered arbitration: no candidate bots -> true drop; Choice=drop with
  high-confidence Noul claims -> rescue with wait_silence (4s grace for
  humans to speak first); Choice!=drop -> adopt Choice's urgency directly.

Semantic content (aliases, roles, windows, budget, classifier engine, and
optional rule overrides) is configured in groupconnect.yaml on top of built-in
defaults in groupconnect/routing/defaults.py.
"""

from .router import AutonomousController, AutonomousConfig

__all__ = ["AutonomousController", "AutonomousConfig"]
