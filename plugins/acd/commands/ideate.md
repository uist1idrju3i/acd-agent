---
description: 対話でアイデアrecordを洗練し、confirmed/openを追跡する。
argument-hint: "<idea-dir>"
allowed-tools:
  - terminal
---

# ACD アイデア洗練

対象ideaディレクトリの`idea.json`と`idea-dialogue.json`を対話で洗練する。
各ターンで次の順序を守る:

1. 次の質問を取得する（GUI install経路は
   `~/.openhands/plugins/installed/acd/skills/acd-ideate/question-bank.json`、
   開発checkout経路は`plugins/acd/skills/acd-ideate/question-bank.json`を`--bank`に渡す）:
   `uv run python scripts/idea_next_questions.py --idea <dir>/idea.json --history <dir>/idea-dialogue.json --bank <bank>`
2. 返された質問（既定3件）を選択肢・トレードオフ・推奨案・出所とともに提示し、
   `uncovered_open_items`はbankに質問の無い人手決定項目として報告する。
3. 利用者が答えた項目だけを`user_statement`出所付きのturn JSONへ書き、
   `uv run python scripts/idea_record_turn.py --idea <dir>/idea.json --history <dir>/idea-dialogue.json --turn <turn.json>`
   で適用し、出力された`IdeaProgress`を表示する。

推測で項目を埋めない。`confirmed`は利用者の発言がある項目だけにする。
進捗はL3観測であり合否根拠ではない。`ready_for_promotion`になった場合のみ
promotion経路（`scripts/promote_idea.py`）を提示する。
