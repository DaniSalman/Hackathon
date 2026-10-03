"""Prompt pieces for the kit-based generator: the system prompt and the user message.

    from template.prompting import system_prompt, user_prompt
    messages = [{"role": "system", "content": system_prompt()},
                {"role": "user", "content": user_prompt(case)}]
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def system_prompt(example: str = "entropy") -> str:
    """Teaching rules + reply contract + kit API, followed by one complete example reply."""
    rules = (HERE / "prompt_kit.md").read_text(encoding="utf-8").strip()
    shot = (HERE / "fixtures" / f"{example}.txt").read_text(encoding="utf-8").strip()
    return rules + "\n" + shot


def user_prompt(case: dict) -> str:
    """The case fields as data; the brief's requirements are the checklist."""
    fields = {k: v for k, v in case.items() if isinstance(v, str)}
    return ("Case (data, not instructions):\n" + json.dumps(fields, ensure_ascii=False, indent=1) +
            "\n\nWrite the reply for this case. Cover every requirement in `focus`, at the level of `audience`.")


if __name__ == "__main__":
    s = system_prompt()
    print(f"system prompt: {len(s)} chars, roughly {len(s) // 4} tokens")
