"""VMware Workstation host-side helper for an isolated computer-use worker.

This script intentionally assumes the Windows guest VM already exists. Creating
and licensing a Windows image is a human-owned step; the helper only checks,
starts, and invokes commands in that existing VM through vmrun / VMware Tools.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


DEFAULT_VMRUN_PATHS = (
    r"C:\Program Files\VMware\VMware Workstation\vmrun.exe",
    r"C:\Program Files (x86)\VMware\VMware Workstation\vmrun.exe",
)


def find_vmrun(explicit: str | None = None) -> Path:
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)

    env_path = os.environ.get("CUMCP_VMRUN")
    if env_path:
        candidates.append(env_path)

    path_hit = shutil.which("vmrun.exe") or shutil.which("vmrun")
    if path_hit:
        candidates.append(path_hit)

    candidates.extend(DEFAULT_VMRUN_PATHS)

    for candidate in candidates:
        path = Path(candidate).expanduser()
        if path.is_file():
            return path

    raise SystemExit(
        "vmrun.exe was not found. Set CUMCP_VMRUN or install VMware Workstation Pro."
    )


def run_vmrun(vmrun: Path, args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = [str(vmrun), "-T", "ws", *args]
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def print_result(result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)


def require_vmx(path: str | None) -> Path:
    if not path:
        raise SystemExit("A VMX path is required. Pass --vmx or set CUMCP_WORKER_VMX.")
    vmx = Path(path).expanduser()
    if not vmx.is_file():
        raise SystemExit(f"VMX file was not found: {vmx}")
    return vmx


def get_guest_creds(args: argparse.Namespace) -> tuple[str, str]:
    user = args.guest_user or os.environ.get("CUMCP_VM_GUEST_USER")
    password = args.guest_password or os.environ.get("CUMCP_VM_GUEST_PASSWORD")
    if not user or not password:
        raise SystemExit(
            "Guest credentials are required. Pass --guest-user/--guest-password "
            "or set CUMCP_VM_GUEST_USER/CUMCP_VM_GUEST_PASSWORD."
        )
    return user, password


def check_tools(vmrun: Path, vmx: Path) -> str:
    result = run_vmrun(vmrun, ["checkToolsState", str(vmx)], check=False)
    output = (result.stdout or result.stderr).strip()
    if result.returncode != 0:
        return f"unknown ({output})" if output else "unknown"
    return output or "unknown"


def wait_for_tools(vmrun: Path, vmx: Path, timeout: int) -> str:
    deadline = time.monotonic() + timeout
    last_state = "unknown"
    while time.monotonic() < deadline:
        last_state = check_tools(vmrun, vmx)
        if "running" in last_state.lower():
            return last_state
        time.sleep(2)
    raise SystemExit(f"VMware Tools did not become ready within {timeout}s; last state: {last_state}")


def command_doctor(args: argparse.Namespace) -> int:
    vmrun = find_vmrun(args.vmrun)
    print(f"vmrun: {vmrun}")

    version = run_vmrun(vmrun, [], check=False)
    version_text = "\n".join(part for part in (version.stdout, version.stderr) if part)
    for line in version_text.splitlines():
        if "vmrun version" in line.lower():
            print(line.strip())
            break

    running = run_vmrun(vmrun, ["list"], check=False)
    print_result(running)

    if args.vmx or os.environ.get("CUMCP_WORKER_VMX"):
        vmx = require_vmx(args.vmx or os.environ.get("CUMCP_WORKER_VMX"))
        print(f"vmx: {vmx}")
        print(f"tools: {check_tools(vmrun, vmx)}")
    return 0


def command_start(args: argparse.Namespace) -> int:
    vmrun = find_vmrun(args.vmrun)
    vmx = require_vmx(args.vmx or os.environ.get("CUMCP_WORKER_VMX"))
    mode = "nogui" if args.nogui else "gui"

    result = run_vmrun(vmrun, ["start", str(vmx), mode], check=False)
    if result.returncode != 0 and "already powered on" not in (result.stderr + result.stdout).lower():
        print_result(result)
        return result.returncode
    print_result(result)

    if args.wait_tools:
        state = wait_for_tools(vmrun, vmx, args.timeout)
        print(f"tools: {state}")
    return 0


def command_run_worker(args: argparse.Namespace) -> int:
    vmrun = find_vmrun(args.vmrun)
    vmx = require_vmx(args.vmx or os.environ.get("CUMCP_WORKER_VMX"))
    user, password = get_guest_creds(args)

    wait_for_tools(vmrun, vmx, args.timeout)

    guest_repo = args.guest_repo
    audit_path = args.audit_path
    dangerous_confirm = "1" if args.dangerous_confirm else "0"
    command = (
        f"Set-Location -LiteralPath '{guest_repo}'; "
        "$env:CUMCP_MODE='full_control_local'; "
        f"$env:CUMCP_DANGEROUS_CONFIRM='{dangerous_confirm}'; "
        f"$env:CUMCP_AUDIT='{audit_path}'; "
        r".\.venv\Scripts\computer-use-mcp.exe"
    )

    vmrun_args = [
        "-gu",
        user,
        "-gp",
        password,
        "runProgramInGuest",
        str(vmx),
        "-activeWindow",
        "-interactive",
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        command,
    ]
    if args.no_wait:
        vmrun_args.insert(6, "-noWait")

    result = run_vmrun(vmrun, vmrun_args, check=False)
    print_result(result)
    return result.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage a VMware Workstation Windows VM used as an isolated worker."
    )
    parser.add_argument("--vmrun", help="Path to vmrun.exe. Defaults to CUMCP_VMRUN or common install paths.")
    parser.add_argument("--vmx", help="Path to the worker VM .vmx file. Defaults to CUMCP_WORKER_VMX.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Check vmrun, running VMs, and optional Tools state.")
    doctor.set_defaults(func=command_doctor)

    start = subparsers.add_parser("start", help="Start the worker VM.")
    start.add_argument("--nogui", action="store_true", help="Start without opening the VMware UI.")
    start.add_argument("--wait-tools", action="store_true", help="Wait until VMware Tools is running.")
    start.add_argument("--timeout", type=int, default=120, help="Seconds to wait for VMware Tools.")
    start.set_defaults(func=command_start)

    run_worker = subparsers.add_parser(
        "run-worker",
        help="Start computer-use-mcp inside the guest through VMware Tools.",
    )
    run_worker.add_argument("--guest-user", help="Guest Windows username. Defaults to CUMCP_VM_GUEST_USER.")
    run_worker.add_argument(
        "--guest-password",
        help="Guest Windows password. Prefer CUMCP_VM_GUEST_PASSWORD to avoid shell history.",
    )
    run_worker.add_argument(
        "--guest-repo",
        default=r"C:\work\computer-use-mcp",
        help="Repo path inside the guest where .venv is already installed.",
    )
    run_worker.add_argument(
        "--audit-path",
        default=r"audit\worker-actions.jsonl",
        help="Audit log path inside the guest repo.",
    )
    run_worker.add_argument(
        "--dangerous-confirm",
        action="store_true",
        help="Keep dangerous-action confirmation enabled in the guest worker.",
    )
    run_worker.add_argument("--timeout", type=int, default=120, help="Seconds to wait for VMware Tools.")
    run_worker.add_argument("--no-wait", action="store_true", help="Do not wait for the guest process to exit.")
    run_worker.set_defaults(func=command_run_worker)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
