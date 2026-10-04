"""Controlled, evidence-producing WARNO startup checks.

This module deliberately proves only process-level startup stability. Campaign
discovery and gameplay observations have separate acceptance criteria.
"""
import csv
import ctypes
import io
import json
import os
from pathlib import Path
import subprocess
import time

from .deployment import plain_path, status_trial
from .storage import sha256, write_json


def warno_pids():
    if os.name != 'nt':
        raise ValueError('Runtime checks currently support Windows only')
    result = subprocess.run(
        ['tasklist.exe', '/FI', 'IMAGENAME eq WARNO.exe', '/FO', 'CSV', '/NH'],
        capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    rows = csv.reader(io.StringIO(result.stdout.decode('utf-8', errors='replace')))
    found = set()
    for row in rows:
        if len(row) == 5 and row[0].casefold() == 'warno.exe':
            try:
                found.add(int(row[1]))
            except ValueError as exc:
                raise ValueError('Cannot parse WARNO process list') from exc
    return found


def crash_snapshot(temp_root=None):
    root = plain_path(temp_root if temp_root is not None else Path(os.environ['LOCALAPPDATA'])/'Temp')
    result = {}
    if not root.is_dir():
        return result
    for report in sorted(root.glob('CrashRpt_*')):
        if not report.is_dir() or report.is_symlink():
            continue
        stat = report.stat()
        marker = report.relative_to(root).as_posix() + '/'
        result[marker] = {'path': marker, 'size': 0,
                          'modified_ns': stat.st_mtime_ns, 'kind': 'report-directory'}
        for path in sorted(report.rglob('*')):
            if path.is_file() and not path.is_symlink():
                data = path.read_bytes()
                result[path.relative_to(root).as_posix()] = {
                    'path': path.relative_to(root).as_posix(),
                    'size': len(data), 'sha256': sha256(data)}
    return result


def crash_delta(before, after):
    return [after[name] for name in sorted(after)
            if name not in before or before[name] != after[name]]


def classify_startup(launched_pid, samples, new_crash_files, required_stable_ms):
    material = [item for item in new_crash_files if item.get('kind') != 'report-directory']
    empty_directories = [item for item in new_crash_files if item.get('kind') == 'report-directory']
    if material:
        return {'status': 'fail', 'reason': 'crash-artifact-created',
                'runtime_pid': None, 'steam_relaunch_observed': False,
                'new_crash_files': material,
                'empty_crash_report_directories': empty_directories}
    if not samples or not samples[-1]['warno_pids']:
        return {'status': 'inconclusive', 'reason': 'runtime-process-not-stable',
                'runtime_pid': None, 'steam_relaunch_observed': False,
                'new_crash_files': [], 'empty_crash_report_directories': empty_directories}
    runtime_pid = min(samples[-1]['warno_pids'])
    first = samples[-1]['elapsed_ms']
    for sample in reversed(samples):
        if runtime_pid not in sample['warno_pids']:
            break
        first = sample['elapsed_ms']
    stable_ms = samples[-1]['elapsed_ms'] - first
    if stable_ms < required_stable_ms:
        return {'status': 'inconclusive', 'reason': 'runtime-process-not-stable',
                'runtime_pid': runtime_pid,
                'steam_relaunch_observed': runtime_pid != launched_pid,
                'stable_ms': stable_ms, 'new_crash_files': [],
                'empty_crash_report_directories': empty_directories}
    return {'status': 'pass', 'reason': 'runtime-process-stable-without-crash-artifact',
            'runtime_pid': runtime_pid,
            'steam_relaunch_observed': runtime_pid != launched_pid,
            'stable_ms': stable_ms, 'new_crash_files': [],
            'empty_crash_report_directories': empty_directories}


def visible_windows(pid):
    """Return visible top-level windows owned by one process; never injects input."""
    if os.name != 'nt':
        raise ValueError('Window inspection currently supports Windows only')
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    result = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    class RECT(ctypes.Structure):
        _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long),
                    ('right', ctypes.c_long), ('bottom', ctypes.c_long)]

    def each(handle, _):
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(owner))
        if owner.value != pid or not user32.IsWindowVisible(handle):
            return True
        rect = RECT()
        if not user32.GetWindowRect(handle, ctypes.byref(rect)):
            return True
        size = user32.GetWindowTextLengthW(handle)
        title = ctypes.create_unicode_buffer(size+1)
        user32.GetWindowTextW(handle, title, len(title))
        result.append({'handle': int(handle), 'title': title.value,
                       'left': rect.left, 'top': rect.top,
                       'width': rect.right-rect.left, 'height': rect.bottom-rect.top})
        return True

    if not user32.EnumWindows(callback_type(each), None):
        error = ctypes.get_last_error()
        if error:
            raise OSError(error, 'EnumWindows failed')
    return result


def classify_interactive_window(windows, min_width=1200, min_height=700):
    if not windows:
        return {'status': 'inconclusive', 'reason': 'no-visible-warno-window'}
    usable = [window for window in windows if window['width'] >= min_width
              and window['height'] >= min_height]
    if not usable:
        return {'status': 'inconclusive', 'reason': 'no-usable-warno-window'}
    return {'status': 'pass', 'reason': 'visible-usable-warno-window', 'window': usable[0]}


def _launch(exe):
    process = subprocess.Popen([str(exe)], cwd=str(exe.parent))
    return process.pid


def _stop_pids(pids):
    for pid in sorted(set(pids)):
        if type(pid) is not int or pid <= 0 or pid == os.getpid():
            raise ValueError('Refusing invalid runtime PID')
        subprocess.run(['taskkill.exe', '/PID', str(pid), '/T', '/F'],
                       capture_output=True, check=False,
                       creationflags=subprocess.CREATE_NO_WINDOW)


def startup_smoke(game_root, output, stable_seconds=20, poll_seconds=.5, temp_root=None,
                  managed_status=None):
    if stable_seconds <= 0 or poll_seconds <= 0:
        raise ValueError('Runtime durations must be positive')
    status = status_trial() if managed_status is None else managed_status
    if not all(status.get(key) for key in
               ('installed', 'active', 'owned', 'integrity_verified', 'activation_managed')):
        raise ValueError('Runtime smoke requires an intact, managed active trial')
    game_root = plain_path(game_root)
    exe = plain_path(game_root/'WARNO.exe')
    if not exe.is_file():
        raise ValueError('WARNO.exe is missing')
    output = plain_path(output)
    output.mkdir(parents=True, exist_ok=True)
    initial = warno_pids()
    if initial:
        raise ValueError('WARNO is already running; runtime ownership is ambiguous')
    before = crash_snapshot(temp_root)
    launched_pid = _launch(exe)
    started = time.monotonic()
    samples = []
    current = set()
    last_pid_set = None
    continuous_since = None
    try:
        while True:
            now = time.monotonic()
            current = warno_pids() - initial
            elapsed = int(round((now-started)*1000))
            samples.append({'elapsed_ms': elapsed, 'warno_pids': sorted(current)})
            frozen = tuple(sorted(current))
            if current and frozen == last_pid_set:
                if elapsed-continuous_since >= int(stable_seconds*1000):
                    break
            else:
                continuous_since = elapsed if current else None
                last_pid_set = frozen
            if elapsed >= int((stable_seconds+30)*1000):
                break
            time.sleep(poll_seconds)
        after = crash_snapshot(temp_root)
        delta = crash_delta(before, after)
        startup = classify_startup(launched_pid, samples, delta,
                                   int(stable_seconds*1000))
        interactive = (classify_interactive_window(visible_windows(startup['runtime_pid']))
                       if startup.get('runtime_pid') is not None else
                       {'status': 'not-run', 'reason': 'no-runtime-process'})
        report = {
            'schema': 1,
            'scope': 'startup-process-only',
            'game': {'path': str(exe), 'sha256': sha256(exe.read_bytes())},
            'trial': {'bundle_id': status['bundle_id'], 'managed_active': True},
            'launched_pid': launched_pid,
            'samples': samples,
            'startup': startup,
            'interactive_window': interactive,
            'limitations': [
                'Does not prove campaign discovery, loading, save compatibility or gameplay mechanics',
                'Absence of a CrashRpt file during the observation window is not a general stability proof'],
        }
        write_json(output/'runtime-startup.json', report)
        return report
    finally:
        live = warno_pids() - initial
        if live:
            _stop_pids(live)
