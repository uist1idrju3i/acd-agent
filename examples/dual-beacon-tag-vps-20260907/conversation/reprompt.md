会話が停止しました。これ以上の設計変更・コード修正は行わず、現状の生成物だけから最終報告を作成してください。

1. 最新の loop-summary.json / timing-record.json / board exploration report を読み、停止した段（failed_stage）と fail-closed の理由、router診断（unrouted推移・next step）をそのまま報告してください。
2. `uv run python scripts/verify_authoritative_evidence.py --revision-from fixtures/dual-beacon-tag/graph.json --out-root <最新のout root> --require-lane electrical --require-lane mechanical --require-lane firmware` を実行し、終了コードと出力をそのまま報告してください（graph.jsonが無い場合はその事実を報告）。
3. あなたが workspace 内で変更した「設計入力以外のファイル」（src/、scripts/、追加debugスクリプト、order-total.json など）を `git status --short` と `git diff --stat` で列挙し、目的を説明してください。
4. 当初の製品要件（緑・橙LEDの500ms交互点滅、ボタンによる一時停止／再開、I2Cヘッダ、4面のうち指定した開口面、筐体）のうち、最終的な spec / firmware sequence から落ちた・変更した項目を理由とともに正直に列挙してください。
5. 合格・order-ready の主張はしないでください。Evidence が無い／provisional である場合はその旨を明記してください。
