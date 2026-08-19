# ADR-0038: ACDインストール自己診断入口

> ステータス: Accepted
> 日付: 2026-08-18

## コンテキスト

Local GUI（OpenHands Agent Canvas）のplugin installは、指定した
`repo_path: plugins/acd` のサブツリーだけを
`~/.openhands/plugins/installed/acd/`へコピーする。リポジトリ直下の
`scripts/`はコピーされないため、checkoutの構成だけを前提にした確認手順では、
plugin名の誤推論、部分コピー、Skill scriptの依存ref driftを検出できない。

また、インストール確認で`acd`をimportすると、`uv run --script`の隔離環境を
利用者の環境と誤認するおそれがある。大型依存を解決せず、plugin単体をコピーした
直後にも実行できる観測入口が必要である。

## 決定

`plugins/acd/skills/acd-install-doctor/`に、標準ライブラリだけで動く
`install_doctor.py`とKeywordTrigger用の`SKILL.md`を配置する。scriptは自身の
`__file__`からplugin rootを解決し、plugin内の資材を診断する。`acd`はimportせず、
`python3 <path>`で直接実行する。これはADR-0037のPEP 723対象
（`acd`をimportするSkill script）には含めない。

診断は次の二層に分ける。

1. **required**: plugin manifest、Skill／Agent／command／hook資材、agent prompt
   manifest hash、package refとPEP 723 dependencyの一致、Python 3.12以上と`uv`
   の存在を検査する。結果が`unknown`の場合もfail-closedで`failed`とする。
2. **capability**: Docker CLIと`acd.openhands.tools.probe.PROBES`と同じ
   `kicad-cli`／`freerouting`の版、installed plugin storeと現在のplugin rootの関係を
   観測する。ホストEDAツールの不在は観測情報として記録するだけでstatusを下げない。
   build123d／cadquery-ocpは隔離scriptから観測せず、本体側の`scripts/probe_tools.py`を
   正とする。Docker不在時にhost実行を合格側へ緩めず、host EDA結果はprovisional専用とする。

出力は機械可読なJSONで、全checkに名前、required、結果、detail、観測版を含める。
scriptのexit codeは`failed`だけ1、それ以外は0とする。

この入口はL3観測であり、L1の合否権限を持たない。診断結果、Skill出力、
ホスト実行、その他の観測をauthoritative Evidenceへ昇格させない。合否は既存の
決定論的ゲートとrevision一致のauthoritative Evidenceだけが担う。

commandは既存の`gates` entry commandを変更せず、doctor scriptの場所を解決して
実行するだけに限定する。

## 影響

- GUI install直後に`/acd:doctor`を実行して、plugin rootの取り違えと資材driftを
  会話から確認できる。
- pluginに含まれないworkspace scriptの参照は、コピー境界を越える外部参照として
  診断のdetailへ明記する。plugin内hook scriptの欠落はrequired failureとする。
- Dockerが到達不能な開発環境でも、インストール健全性を確認したうえで
  capabilityを`degraded`として報告できる。ホストEDA toolの不在だけではstatusを下げない。

## 検証

- `python3`で開発checkoutのdoctorを実行する。
- `plugins/acd`を一時的なinstalled plugin rootへコピーし、GUI install境界でも
  同じscriptが動作することを確認する。
- doctor自身のpositive testと、manifest名、prompt hash、package refを壊す
  negative testを実行する。
- Dockerが到達可能な環境では、ホストEDA toolの不在にかかわらず`status`が`ok`になる
  ことを確認する。
- `uv run pytest plugins -q`と`uv run python scripts/verify_all.py --stage standard`
  を通す。
