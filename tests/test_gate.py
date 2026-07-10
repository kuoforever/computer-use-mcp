from __future__ import annotations

from unittest.mock import patch

from computer_use_mcp.contract import ProcRef
from computer_use_mcp.gate import Gate


class FakeDriver:
    def __init__(self, chains: list[list[str]]) -> None:
        self.chains = iter(chains)

    def foreground_owner_chain(self) -> list[ProcRef]:
        return [ProcRef(pid=index, name=name) for index, name in enumerate(next(self.chains), start=1)]


def test_gate_allows_an_authorized_ancestor_process() -> None:
    gate = Gate(["weixin.exe"], FakeDriver([["WechatAppEx.exe", "Weixin.exe"]]), retries=0)

    allowed, reason = gate.foreground_allowed()

    assert allowed is True
    assert reason == "Weixin.exe"


def test_gate_retries_a_transient_foreground_before_allowing() -> None:
    driver = FakeDriver([["explorer.exe"], ["renderer.exe", "weixin.exe"]])
    gate = Gate(["weixin.exe"], driver, retries=1, retry_wait=0.1)

    with patch("computer_use_mcp.gate.time.sleep") as sleep:
        allowed, reason = gate.foreground_allowed()

    assert allowed is True
    assert reason == "weixin.exe"
    sleep.assert_called_once_with(0.1)


def test_gate_rejection_includes_the_observed_foreground_process() -> None:
    gate = Gate(["notepad.exe"], FakeDriver([["calc.exe"]]), retries=0)

    allowed, reason = gate.foreground_allowed()

    assert allowed is False
    assert "calc.exe" in reason
