#!/usr/bin/env python3
"""Ordinary-user Phase 5 production CLI checks in a disposable candidate guest.

The root harness must separately attest Secure Boot, candidate identities and
unchanged managed OS state. This script never installs packages or changes policy.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import time


def require(value, message):
    if not value:
        raise RuntimeError(message)


def run(*args, timeout=210):
    result = subprocess.run(['/usr/bin/distroctl', 'performance', *args, '--json'],
                            capture_output=True, text=True, timeout=timeout)
    require(len(result.stdout.encode()) <= 16 * 1024 ** 2, 'oversized backend output')
    return result


def events(result):
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    require(rows and all(row.get('schema_version') == 1 and row.get('event') in
                        {'started', 'sample', 'phase', 'result'} for row in rows), 'invalid event stream')
    require(rows[0]['event'] == 'started' and rows[-1]['event'] == 'result', 'missing stream boundary')
    report = rows[-1]['data']
    require(report['id'] == rows[0]['data']['id'] and re.fullmatch('[0-9a-f]{32}', report['id']), 'run ID mismatch')
    require(report['schema_version'] == 1 and report['state'] == 'completed' and result.returncode == 0,
            'production run did not complete: ' + result.stderr[-1000:])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['guest'])
    args = parser.parse_args()
    require(args.action == 'guest' and os.geteuid() != 0, 'ordinary desktop user required')
    config = json.loads(Path('/mnt/astraeus-validation/phase5-config.json').read_text())
    require(config['schema_version'] == 1 and config['disposable'] is True, 'dedicated validator marker required')
    for name in ['distroctl', 'astraeus-control-center']:
        with Path('/usr/bin', name).open('rb') as stream:
            require(hashlib.file_digest(stream, 'sha256').hexdigest() == config['binaries'][name], 'candidate binary mismatch')
    status = json.loads(run('status').stdout)
    require(status['schema_version'] == 1 and status['context']['virtual_machine'] is True, 'disposable VM required')
    require(not status['baseline_blockers'], 'unexpected baseline blockers: ' + str(status['baseline_blockers']))
    first = events(run('record', '--duration', '2'))
    require(len(first['samples']) >= 2 and first['kind'] == 'record', 'recording lacks interval evidence')
    baselines = [events(run('baseline')) for _ in range(2)]
    for report in baselines:
        require(report['kind'] == 'baseline' and report['elapsed_seconds'] <= 180, 'baseline exceeded budget')
        require(len(report['measurements']) == 3, 'incomplete baseline workloads')
        for measurement in report['measurements']:
            require(len(measurement['values']) == 3 and all(v > 0 for v in measurement['values']), 'missing throughput')
            require(1 <= measurement['workload']['threads'] <= 4 and
                    0 < measurement['workload']['bytes'] <= 128 * 1024 ** 2, 'resource limits differ')
        shown = run('show', report['id'])
        exported = run('export', report['id'])
        require(shown.returncode == exported.returncode == 0 and
                json.loads(shown.stdout) == json.loads(exported.stdout) == report, 'stored/exported result differs')
    comparison = json.loads(run('compare', baselines[0]['id'], baselines[1]['id']).stdout)
    require(comparison['comparable'] is True and len(comparison['measurements']) == 3, 'equivalent runs not comparable')
    refused = json.loads(run('compare', first['id'], baselines[0]['id']).stdout)
    require(refused['comparable'] is False and not refused['measurements'], 'passive record became benchmark comparison')
    child = subprocess.Popen(['/usr/bin/distroctl', 'performance', 'record', '--duration', '60', '--json'],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    started = json.loads(child.stdout.readline())
    require(started['event'] == 'started', 'cancellation run did not start')
    concurrent = run('record', '--duration', '1')
    require(concurrent.returncode != 0 and not concurrent.stdout, 'concurrent user measurement was accepted')
    os.kill(child.pid, signal.SIGTERM)
    output, diagnostic = child.communicate(timeout=10)
    require(child.returncode != 0, 'cancelled process claimed success')
    stopped = json.loads(run('show', started['data']['id']).stdout)
    require(stopped['state'] == 'cancelled', 'cancellation was not persisted')
    for bad in [('record', '--duration', '301'), ('baseline', '--command', 'sh'), ('show', '../escape')]:
        result = run(*bad)
        require(result.returncode != 0 and not result.stdout, 'invalid input accepted')
    state = Path(os.environ.get('XDG_STATE_HOME') or str(Path.home() / '.local/state')) / 'astraeus/performance'
    require(stat.S_IMODE(state.stat().st_mode) == 0o700, 'state directory is not private')
    for report in [first, *baselines, stopped]:
        p = state / report['id'] / 'result.json'
        require(p.stat().st_uid == os.geteuid() and stat.S_IMODE(p.stat().st_mode) == 0o600, 'report ownership/mode mismatch')
        require(not (p.parent / 'scratch.bin').exists(), 'named scratch residue')
    proof = dict(schema_version=1, passed=True, uid=os.geteuid(), source_commit=config['source_commit'],
                 binary_sha256=config['binaries'], recorded=first['id'], baselines=[r['id'] for r in baselines],
                 cancelled=stopped['id'], comparison=comparison, completed_at_unix=time.time(),
                 cases=['real collection', 'two bounded baselines', 'same-backend show/export', 'compatible comparison',
                        'passive comparison refused', 'concurrent measurement refused', 'SIGTERM persisted',
                        'bounded arguments', 'private owned state', 'no named scratch residue'],
                 limits=['VM software evidence only; no physical or gaming performance qualification'])
    print(json.dumps(proof))


if __name__ == '__main__':
    main()
