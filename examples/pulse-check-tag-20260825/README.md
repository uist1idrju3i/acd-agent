# 実行例: pulse-check-tag（2026-08-25）

実機OpenHands（workspace `test5`）で、Devinの補助なしに`acd-agent`単体でVibeBB
（Vibe BreadBoarding）を成立させられるかを検証した実行例である。題材はGD1のコピーではない
新規小規模設計`pulse-check-tag`（USB Type-Cバスパワー、ESP32-C3-MINI-1、緑LED 1個、
tact switch 1個、22 × 16 mm 2層、部品10点前後）で、MCUのみGD1と同一にした。

- graph_id: `pulse-check-tag` / revision: `r1`
- 対象revision: `4b689fece94d82285312b5c7b36a7795ad617cbf`
  （plugin resolved ref、workspaceのcheckout、`main`先端の3者一致を確認）
- 検証日: 2026-08-25（UTC）
- 詳細レポート: [`report/devin-report.md`](report/devin-report.md)
- 気づき・改善提案: [`report/improvement-notes.md`](report/improvement-notes.md)
- 前回検証（workspace `test4`、題材`mini-blink-dongle`）:
  [`../mini-blink-dongle-20260825/`](../mini-blink-dongle-20260825/)

## この実行例の位置づけ（重要）

- **authoritative Evidenceは1件も成立していない。** silkscreen laneはdigest固定container内で
  `status: "resolved"`まで到達したが、これはresolver出力であり、revision一致・`status="valid"`の
  Evidence（`evidence-electrical.json`／`evidence-mechanical.json`相当）ではない。
- **基板lane以降は未通過。** FreeRoutingが`--max-passes 99999`（CLI既定）でも
  `--max-passes 10`でも600秒のsubprocess timeoutに達してfail-closedした。
  `convergence_state = converged`の記録は存在しない。
- **FW lane、筐体lane、order-total集約、pre-orderゲートは未実行**である（実機OpenHandsの
  クラッシュにより到達しなかった）。
- **実発注、見積取得、supplier API呼び出し、決済、注文確定は一切行っていない。**
  実発注はユーザーが実施する。
- 実行環境の識別情報（ホスト名、ドメイン、エンドポイント、ユーザー名、鍵、token、API key）は
  本フォルダに含めない。

## 前回検証からの進展

前回（`mini-blink-dongle`）で「新規設計がlaneの入口に到達できない」直接原因だった
[`../../docs/vibebb-gap-analysis.md`](../../docs/vibebb-gap-analysis.md)のN-1
（`DesignFixtureSpec`がmechanical・silkscreen・firmware moduleを宣言できない）と
N-5（U1のIO-to-pad mappingを宣言経由で与えられない）は解消しており、本検証では新規設計で
silkscreen laneがcontainer内で`resolved`まで到達した。残る律速はN-3（必須宣言の一括preflight、
本検証のQ-5）と、新たに顕在化したQ-1（FreeRoutingのtimeout／pass予算既定値）および
Q-2（container既定メモリ上限とホスト容量の不整合）である。

## フォルダ構成

| フォルダ | 内容 |
|---|---|
| [`report/`](report/) | 詳細レポートと改善提案メモ |
