# WCA fixture

`gd1-spice-result.json`は、10.1のlocked ngspice 45.2 recorded outputを
既存のSPICE evaluatorで評価して生成した決定論的な`SpiceResult`である。
公差表と環境fixtureを`run_wca.py`へ渡したGD1の結果は次のとおり。

- LED series current: `1.480687 mA` nominal、pass
- I2C SDA rise time: `206 ns` nominal、pass
- 3V3 LDO output: `3.3 V` nominal、pass
- USB peak power budget: `362 mA` peak、pass

WCAは`authority="estimate"`のopt-in L2 stop-side解析であり、
authoritative EvidenceやGD1 default gateの合格側には接続しない。
peak power budgetは16.2 battery power budgetの実装ではなく、
WCA requestに宣言されたloadのpeak電流を供給容量と比較する。
