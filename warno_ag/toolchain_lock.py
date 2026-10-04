"""One cooperating compiler/baker job per installed WARNO Gen directory."""
from contextlib import contextmanager
import json
import os
from pathlib import Path


def _live_observed_children(job):
    if os.name != 'nt' or not job or not Path(job).is_dir():
        return []
    from .process_observation import snapshot
    running = snapshot()
    live = []
    for path in Path(job).glob('*/process.json'):
        record = json.loads(path.read_text(encoding='utf-8'))
        for pid, created in record.get('observed_processes', {}).items():
            current = running.get(int(pid))
            if current and current['created'] == created:
                live.append(int(pid))
    return sorted(set(live))


@contextmanager
def compiler_workspace_lock(game, job):
    """Fail before mutations when another job owns shared compiler outputs.

    The lock file is retained. OS locking releases after a crashed Python process;
    persisted build observations additionally catch its still-running children.
    This does not control independently launched official tools.
    """
    game = Path(game).resolve()
    if not (game / 'Tools').is_dir():
        raise ValueError('Compiler lock requires the installed game Tools directory')
    directory = game / 'Gen'
    directory.mkdir(exist_ok=True)
    path = directory / '.agf-compiler.lock'
    with path.open('a+b') as stream:
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            acquire = lambda: msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            release = lambda: msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            acquire = lambda: fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            release = lambda: fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        try:
            acquire()
        except OSError as error:
            raise RuntimeError('Another framework compiler/baker job is using this WARNO installation') from error
        try:
            if path.stat().st_size == 0:
                stream.write(b'\0')
                stream.flush()
            stream.seek(1)
            previous = stream.read()
            prior = json.loads(previous.decode('utf-8')) if previous else {}
            live = _live_observed_children(prior.get('job'))
            if live:
                raise RuntimeError('A previous compiler job still has observed child processes: ' + str(live))
            # a+b appends writes, so truncate at byte one before writing metadata.
            stream.seek(1)
            stream.truncate()
            stream.write(json.dumps({'pid': os.getpid(), 'job': str(Path(job).resolve())}).encode('utf-8'))
            stream.flush()
            yield
        finally:
            stream.seek(0)
            release()
