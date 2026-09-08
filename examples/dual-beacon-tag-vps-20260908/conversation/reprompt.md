会話が停止しました。これ以上の設計変更・コード修正は行わず、現状の生成物だけから最終報告を作成してください。

1. 最新の loop-summary.json / timing-record.json / board exploration report を読み、停止した段（failed_stage）と fail-closed の理由、router診断（unrouted推移・next step）をそのまま報告してください。
2. `uv run python scripts/verify_authoritative_evidence.py --revision-from fixtures/dual-beacon-tag/graph.json --out-root <最新のout root> --require-lane electrical --require-lane mechanical --require-lane firmware` を実行し、終了コードと出力をそのまま報告してください（graph.jsonが無い場合はその事実を報告）。
3. `uv run python scripts/report_final_basis.py --root <workspace root> --design-input fixtures/dual-beacon-tag/spec.json` を実行し、その出力（source変更節の `git log --stat <bootstrap>..HEAD` block・worktree block・design values表）をそのまま引用してください。あなたが変更した「設計入力以外のファイル」（src/、scripts/、plugins/、追加debugスクリプト、order-total.json など）があれば目的を説明してください。「source変更なし」は `status: clean` の場合にだけ述べてください。
4. 当初の製品要件（緑・橙LEDの500ms交互点滅、ボタンによる一時停止／再開、EN/BOOT strapping、I2Cヘッダ、USB-C・LED窓2個・ボタン・I2Cヘッダの筐体開口）のうち、最終的な spec / graph / firmware sequence から落ちた・変更した項目を理由とともに正直に列挙してください。部品value・netの記述は3の design values 表と一致させてください。
5. 最新のout root配下（生成物・Evidence・loop-summary・timing・lane preflight・coverage report）と fixtures/dual-beacon-tag/ を `tar czf` で workspace 直下へ固めてください（build tree等の再生成可能な大容量出力は除く）。
6. 合格・order-ready の主張はしないでください。Evidence が無い／provisional／container digest や source revision が unknown である場合はその旨を明記してください。