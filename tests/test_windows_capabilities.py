from computer_use_mcp.contract import CONTRACT_VERSION
from computer_use_mcp.drivers.windows import WindowsDriver


def test_windows_driver_advertises_every_implemented_v1_capability() -> None:
    driver = WindowsDriver.__new__(WindowsDriver)
    driver.dpi_mode = "test-dpi"

    assert driver.capabilities() == {
        "contract_version": CONTRACT_VERSION,
        "platform": "windows",
        "features": [
            "capture_screen",
            "list_windows",
            "foreground_owner_chain",
            "get_tree",
            "find",
            "get_document_text",
            "invoke",
            "set_value",
            "select",
            "type",
            "key",
            "click",
            "scroll",
            "drag",
            "activate_window",
        ],
        "dpi_mode": "test-dpi",
    }
