"""SilkscreenGateError must survive pickling through ProcessPoolExecutor."""

from __future__ import annotations

import pickle

from acd.adapters.kicad.fab.silkscreen import SilkscreenGateError


def test_silkscreen_gate_error_pickles_with_context() -> None:
    err = SilkscreenGateError("gate rejected", {"status": "measured_fail", "via": 3})
    restored = pickle.loads(pickle.dumps(err))
    assert isinstance(restored, SilkscreenGateError)
    assert str(restored) == "gate rejected"
    assert restored.context == {"status": "measured_fail", "via": 3}
