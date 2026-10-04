"""Launch one build process; persist native dialog text before dismissing errors."""
import argparse
import json
from pathlib import Path
import subprocess
import time

from warno_ag.build_dialogs import ProcessDialogs
from warno_ag.process_observation import descendants, snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cwd', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or args.timeout <= 0:
        parser.error('A command and positive timeout are required')
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    seen = set()
    ambient_seen = set()
    with (output / 'stdout.log').open('wb') as stdout, (output / 'stderr.log').open('wb') as stderr:
        process = subprocess.Popen(command, cwd=args.cwd, stdout=stdout, stderr=stderr)
        observer = ProcessDialogs(process.pid)
        initial = snapshot()
        owned = {process.pid: initial[process.pid]['created']} if process.pid in initial else {}
        idle_since = None
        report = {'pid': process.pid, 'command': command, 'cwd': args.cwd, 'state': 'running',
                  'observed_processes': owned}
        (output / 'process.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        with (output / 'dialogs.jsonl').open('w', encoding='utf-8') as events, \
                (output / 'desktop-dialogs.jsonl').open('w', encoding='utf-8') as ambient:
            while time.monotonic() - started < args.timeout:
                records = snapshot()
                owned = descendants(records, owned)
                live = {pid for pid, created in owned.items()
                        if pid in records and records[pid]['created'] == created}
                for dialog in observer.collect(desktop=True):
                    key = json.dumps(dialog, sort_keys=True)
                    if dialog['pid'] not in live:
                        if key not in ambient_seen:
                            ambient_seen.add(key)
                            ambient.write(json.dumps({'event': 'unowned-dialog', 'dialog': dialog}, ensure_ascii=False) + '\n')
                            ambient.flush()
                        continue
                    if key in seen:
                        continue
                    seen.add(key)
                    events.write(json.dumps({'event': 'captured', 'dialog': dialog}, ensure_ascii=False) + '\n')
                    events.flush()
                    current = snapshot().get(dialog['pid'])
                    dismissed = bool(current and current['created'] == owned[dialog['pid']] and
                                     ProcessDialogs(dialog['pid']).dismiss_error(dialog))
                    events.write(json.dumps({'event': 'response', 'handle': dialog['handle'],
                                             'dismissed': dismissed}) + '\n')
                    events.flush()
                if process.poll() is not None and not live:
                    if idle_since is None:
                        idle_since = time.monotonic()
                    if time.monotonic() - idle_since >= 2:
                        break
                else:
                    idle_since = None
                time.sleep(0.1)
        report.update(exit_code=process.poll(), elapsed_seconds=time.monotonic() - started,
                      state='exited' if idle_since is not None and time.monotonic() - idle_since >= 2 else 'observation-timeout',
                      captured_dialogs=len(seen), unowned_dialogs=len(ambient_seen),
                      observed_processes=owned, live_processes=sorted(live))
        (output / 'process.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))
    return 124 if report['state'] == 'observation-timeout' else (process.returncode or int(bool(seen)))


if __name__ == '__main__':
    raise SystemExit(main())
