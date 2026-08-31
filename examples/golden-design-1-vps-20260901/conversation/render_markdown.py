"""Render an OpenHands conversation export (zip) into a readable Markdown log.

Input: the directory extracted from the GUI "Download conversation data" zip.
Output: Markdown with user messages, agent reasoning, tool calls, tool results,
hook executions and rejections, in event order.

Secrets are already masked by the exporter (api_key fields). This renderer also
redacts the VPS address and any bearer/session key looking strings.
"""

from __future__ import annotations

import argparse
import glob
import json
import re
from pathlib import Path

REDACTIONS = [
    (re.compile(r"133\.242\.150\.9"), "[REDACTED-HOST]"),
    (re.compile(r"(?i)(session[-_ ]?api[-_ ]?key[\"'=: ]+)[0-9a-f]{16,}"), r"\1[REDACTED]"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "[REDACTED-TOKEN]"),
]

MAX_TEXT = 12000


def redact(text: str) -> str:
    for pattern, replacement in REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def clip(text: str) -> str:
    text = redact(text)
    if len(text) > MAX_TEXT:
        omitted = len(text) - MAX_TEXT
        return text[:MAX_TEXT] + f"\n… [{omitted} characters omitted]"
    return text


def join_content(blocks: object) -> str:
    if isinstance(blocks, str):
        return blocks
    if not isinstance(blocks, list):
        return ""
    out = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            out.append(block.get("text", ""))
        elif isinstance(block, dict) and "text" in block:
            out.append(str(block["text"]))
    return "\n".join(part for part in out if part)


def fence(text: str, lang: str = "text") -> str:
    return f"```{lang}\n{text.rstrip()}\n```"


def render(events_dir: Path, out_path: Path, title: str, conversation_id: str) -> None:
    lines: list[str] = []
    model = None
    tools: list[str] = []
    system_prompt_chars = 0

    files = sorted(glob.glob(str(events_dir / "*.json")))
    for path in files:
        event = json.loads(Path(path).read_text(encoding="utf-8"))
        kind = event.get("kind")
        stamp = event.get("timestamp", "")

        if kind == "ConversationStateUpdateEvent":
            value = event.get("value")
            if isinstance(value, dict) and "llm" in value:
                model = value["llm"].get("model", model)
                tools = [t.get("name") for t in value.get("tools", []) if isinstance(t, dict)]
            continue

        if kind == "SystemPromptEvent":
            system_prompt_chars = len(json.dumps(event, ensure_ascii=False))
            continue

        if kind == "MessageEvent":
            message = event.get("llm_message", {})
            role = message.get("role", "unknown")
            heading = "ユーザー" if role == "user" else f"メッセージ（{role}）"
            lines.append(f"## {heading}\n\n<sub>{stamp}</sub>\n")
            lines.append(clip(join_content(message.get("content"))) + "\n")
            skills = event.get("activated_skills")
            if skills:
                lines.append(f"<sub>activated skills: {', '.join(skills)}</sub>\n")
            continue

        if kind == "ActionEvent":
            action = event.get("action", {}) or {}
            tool_name = event.get("tool_name", action.get("kind", "action"))
            reasoning = (event.get("reasoning_content") or "").strip()
            thought = join_content(event.get("thought")).strip()
            summary = (event.get("summary") or "").strip()
            lines.append(f"### アクション: `{tool_name}`\n\n<sub>{stamp}</sub>\n")
            if summary:
                lines.append(f"*{redact(summary)}*\n")
            if reasoning:
                lines.append(
                    "<details><summary>推論</summary>\n\n"
                    + clip(reasoning)
                    + "\n\n</details>\n"
                )
            if thought:
                lines.append(clip(thought) + "\n")
            arguments = (event.get("tool_call") or {}).get("arguments")
            if arguments:
                lines.append(fence(clip(str(arguments)), "json") + "\n")
            continue

        if kind == "ObservationEvent":
            observation = event.get("observation", {}) or {}
            content = join_content(observation.get("content"))
            lines.append(
                f"<details><summary>結果: <code>{event.get('tool_name')}</code></summary>\n"
            )
            lines.append(f"<sub>{stamp}</sub>\n")
            lines.append(fence(clip(content)) + "\n")
            lines.append("</details>\n")
            continue

        if kind == "UserRejectObservation":
            lines.append(
                f"> **拒否 ({event.get('rejection_source')})**: "
                f"{redact(event.get('rejection_reason', ''))}\n"
            )
            lines.append(f"<sub>{stamp} / tool: {event.get('tool_name')}</sub>\n")
            continue

        if kind == "HookExecutionEvent":
            status = "ok" if event.get("success") else "failed"
            blocked = " / blocked" if event.get("blocked") else ""
            detail = (event.get("additional_context") or event.get("stderr") or "").strip()
            lines.append(
                f"<sub>hook {event.get('hook_event_type')}: {status}{blocked}"
                + (f" — {redact(detail)}" if detail else "")
                + f" <span>({stamp})</span></sub>\n"
            )
            continue

    header = [
        f"# {title}",
        "",
        f"**conversation id:** `{conversation_id}`",
        f"**モデル:** {model}",
        f"**登録tool:** {', '.join(t for t in tools if t)}",
        f"**event数:** {len(files)}",
        "",
        "OpenHands Local GUIの「会話データをダウンロード」で取得したzipのeventから生成した。"
        f"system promptは{system_prompt_chars}文字で、本ログには含めていない。"
        "12000文字を超えるtool出力は末尾を省略している。",
        "",
        "---",
        "",
    ]
    out_path.write_text("\n".join(header + lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--events-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--conversation-id", required=True)
    args = parser.parse_args()
    render(args.events_dir, args.out, args.title, args.conversation_id)


if __name__ == "__main__":
    main()
