from __future__ import annotations

import json
import ctypes
import os
import secrets
import re
from pathlib import Path


def current_user_sid() -> str:
    import win32api
    import win32con
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()
    return win32security.ConvertSidToStringSid(sid)


def restrict_path(path: Path, directory: bool = False) -> None:
    if os.name != "nt":
        path.chmod(0o700 if directory else 0o600)
        return
    import win32security

    sid = current_user_sid()
    inheritance = "OICI" if directory else ""
    descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        f"D:P(A;{inheritance};FA;;;{sid})(A;{inheritance};FA;;;SY)",
        win32security.SDDL_REVISION_1,
    )
    win32security.SetNamedSecurityInfo(str(path), win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        None, None, descriptor.GetSecurityDescriptorDacl(), None)


def private_directory(root: Path, prefix: str = "job-") -> Path:
    from .native import verified_path
    root = verified_path(root, missing=True)
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or root.is_junction():
        raise PermissionError("Contact workspace must not be a reparse directory")
    restrict_path(root, True)
    path = root / (prefix + secrets.token_hex(16))
    path.mkdir()
    restrict_path(path, True)
    return path


def validate_bootstrap(path: Path) -> dict:
    from .native import verified_path
    path = verified_path(path)
    if path.is_symlink() or path.is_junction() or path.stat().st_size > 16_384:
        raise ValueError("Invalid reader bootstrap")
    if os.name == "nt":
        import win32security
        descriptor = win32security.GetNamedSecurityInfo(str(path), win32security.SE_FILE_OBJECT,
            win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION)
        owner = win32security.ConvertSidToStringSid(descriptor.GetSecurityDescriptorOwner())
        if owner != current_user_sid():
            raise PermissionError("Reader bootstrap belongs to a different user")
        acl = descriptor.GetSecurityDescriptorDacl()
        if acl is None:
            raise PermissionError("Reader bootstrap must have restricted access")
        for index in range(acl.GetAceCount()):
            kind, mask, sid = acl.GetAce(index)
            if kind[0] == win32security.ACCESS_ALLOWED_ACE_TYPE and mask:
                if win32security.ConvertSidToStringSid(sid) not in (owner, "S-1-5-18"):
                    raise PermissionError("Reader bootstrap must have restricted access")
    value = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or value.get("schemaVersion") != 1
            or value.get("ownerSid") != current_user_sid()
            or not isinstance(value.get("pipe"), str)
            or not value["pipe"].startswith("fuge-contacts-")
            or not isinstance(value.get("token"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["token"])
            or not isinstance(value.get("jobId"), str) or not value["jobId"]
            or type(value.get("guiPid")) is not int or value["guiPid"] <= 0
            or type(value.get("guiStartTime")) is not int or value["guiStartTime"] <= 0):
        raise ValueError("Invalid reader bootstrap")
    return value


def verify_pipe_server(descriptor: int, config: dict, *, kernel=None, probe=None) -> None:
    from .native import Win32Probe
    try:
        if kernel is None:
            kernel = ctypes.windll.kernel32
            kernel.GetNamedPipeServerProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            kernel.GetNamedPipeServerProcessId.restype = ctypes.c_bool
        pid = ctypes.c_ulong()
        if not kernel.GetNamedPipeServerProcessId(descriptor, ctypes.byref(pid)) or pid.value != config["guiPid"]:
            raise PermissionError()
        probe = probe or Win32Probe()
        owner, session = probe.current_identity()
        identity = probe.inspect(pid.value)
        if (identity.pid != pid.value or identity.start_time != config["guiStartTime"]
                or identity.sid != config["ownerSid"] or identity.sid != owner
                or identity.session_id != session):
            raise PermissionError()
    except Exception:
        raise PermissionError("Reader server identity could not be verified") from None


def cleanup_bootstraps(root: Path) -> int:
    from .native import process_start_time, verified_path
    if not root.exists(): return 0
    root = verified_path(root)
    removed = 0
    for directory in root.glob("bootstrap-*"):
        if not re.fullmatch(r"bootstrap-[0-9a-f]{32}", directory.name): continue
        try:
            directory = verified_path(directory)
            if {child.name for child in directory.iterdir()} != {"launch.json"}: continue
            path = directory / "launch.json"
            marker = validate_bootstrap(path)
            pid, start = marker.get("guiPid"), marker.get("guiStartTime")
            if type(pid) is not int or pid <= 0 or type(start) is not int or start <= 0: continue
            if process_start_time(pid) == start: continue
            path.unlink()
            directory.rmdir()
            removed += 1
        except (OSError, ValueError, RuntimeError):
            continue
    return removed
