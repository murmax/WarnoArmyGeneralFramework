"""Run a structured build command with combined output and an exit-code receipt."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    request = Path(sys.argv[1]).resolve()
    spec = json.loads(request.read_text(encoding='utf-8-sig'))
    if (not isinstance(spec.get('executable'), str) or not isinstance(spec.get('arguments'), list)
            or any(not isinstance(item, str) for item in spec['arguments'])):
        raise ValueError('Expected a structured executable/arguments command')
    started = time.monotonic()
    with Path(spec['output']).open('wb') as output:
        result = subprocess.run([spec['executable'], *spec['arguments']], cwd=spec['cwd'],
            stdout=output, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    report = {'format': 'agf-logged-process/v1', 'command': str(request), 'exit_code': result.returncode,
              'elapsed_seconds': time.monotonic() - started, 'output': spec['output']}
    request.with_suffix('.result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
