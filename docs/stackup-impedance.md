# 4層stackupとインピーダンス契約

`electrical.stackup`は銅層と誘電体層の順序、厚さ、銅厚、材料、誘電率、
finished thicknessを宣言する。宣言は任意であり、既存の2層graphへ暗黙の
stackupを補うことはしない。銅層名、層数、平面層、厚さ合計、boardとの関係は
電気lane抽出時にfail-closedで検証する。

## IPC-2141近似

外層microstripは次式で計算する。

```text
Z0 = 87/sqrt(er+1.41) * ln(5.98h/(0.8w+t))
Zdiff = 2*Z0*(1-0.48*exp(-0.96s/h))
```

内層striplineは次式で計算する。

```text
Z0 = 60/sqrt(er) * ln(4h/(0.67*pi*(0.8w+t)))
Zdiff = 2*Z0*(1-0.347*exp(-2.9s/h))
```

`h`は配線層から参照平面までの誘電体厚、`w`は配線幅、`t`は銅厚、
`s`は差動gap、`er`は誘電率で、すべてmm系で扱う。`differential_pair`はp/n
の完全なペアと、目標、許容差、層、幅、gapの一致を要求する。

これらはIPC-2141のclosed-form近似であり、field solver、製造ばらつき、
ガラスクロス効果、実装状態を表現しない。計算結果は設計時のスクリーニング
に限り、実測インピーダンスEvidenceがauthoritativeな判定入力である。
