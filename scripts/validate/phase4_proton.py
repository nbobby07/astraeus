"""TEST ONLY: retain Win32 stdout across Proton's separate console launch."""
import hashlib
import os
from pathlib import Path
import re
import uuid

from phase4_guest import execute, p2guest


def windows_path(path):
    value = str(Path(path).resolve())
    # cmd.exe expands metacharacters even inside quotes; test paths need none.
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+', value):
        raise ValueError('Use a simple absolute test path without cmd.exe metacharacters')
    return 'Z:' + value.replace('/', '\\')


def completion(log, expected):
    starts = re.findall(r'trace:process:NtCreateUserProcess [^\n]*windows-smoke\.exe[^\n]* '
                        r'pid ([0-9a-f]+) tid [0-9a-f]+ handles', log)
    if len(starts) != 1:
        return dict(verified=False, reason='Expected exactly one traced Win32 fixture child')
    pid = starts[0]
    exits = re.findall(r':' + pid + r':[0-9a-f]+:trace:process:NtTerminateProcess '
                       r'handle 0xffffffffffffffff, exit_code ([0-9a-f]+), process_exiting 1\.', log)
    return dict(pid=pid, exit_codes=exits, verified=exits == [format(expected, 'x')])


def window_lifecycle(log, pid):
    lines = '\n'.join(line for line in log.splitlines() if re.search(':' + pid + r':[0-9a-f]+:trace:win:', line))
    title = re.search(r'NtUserCreateWindowEx [^\n]*window_name L"Astraeus Proton smoke"', lines)
    if not title:
        return dict(verified=False)
    lines = lines[title.end():]
    created = re.search(r'NtUserCreateWindowEx hwnd (0x[0-9a-f]+) cs 0,0 320x160', lines)
    if not created:
        return dict(verified=False)
    hwnd = created[1]
    tail = lines[created.end():]
    completed = re.search('NtUserCreateWindowEx created window ' + re.escape(hwnd) + r'(?:\s|$)', tail)
    destroyed = re.search('trace:win:destroy_window ' + re.escape(hwnd) + r'(?:\s|$)',
                          tail[completed.end():]) if completed else None
    return dict(hwnd=hwnd, verified=destroyed is not None)


def run_case(prefix, proton, runtime, exe, compat, steam_root, work, negative=False):
    case = work / ('proton-exit-control' if negative else 'proton-normal')
    case.mkdir(mode=0o700)
    owner = work.stat()
    os.chown(case, owner.st_uid, owner.st_gid)
    nonce = uuid.uuid4().hex
    stdout, stderr = case / 'fixture.stdout', case / 'fixture.stderr'
    batch = case / 'run.cmd'
    arguments = '' if negative else ' ' + nonce
    # The original PE stays unchanged. cmd waits and propagates its real exit.
    batch.write_bytes(('@echo off\r\n"' + windows_path(exe) + '"' + arguments +
                      ' 1>"' + windows_path(stdout) + '" 2>"' + windows_path(stderr) +
                      '"\r\nexit /b %errorlevel%\r\n').encode('ascii'))
    os.chown(batch, owner.st_uid, owner.st_gid)
    batch.chmod(0o600)
    command = prefix + ['env', f'STEAM_COMPAT_DATA_PATH={compat}',
        f'STEAM_COMPAT_CLIENT_INSTALL_PATH={steam_root}', f'STEAM_COMPAT_INSTALL_PATH={work}',
        'SteamAppId=0', 'SteamGameId=0', 'PROTON_LOG=1', f'PROTON_LOG_DIR={case}',
        'WINEDEBUG=+timestamp,+pid,+tid,+process,+steam,+win',
        str(runtime), '--verb=waitforexitandrun', '--', str(proton), 'run',
        'C:\\windows\\system32\\cmd.exe', '/d', '/c', windows_path(batch)]
    reply = execute(command, timeout=180)
    expected = 2 if negative else 0
    result = dict(reply, status='FAIL', expected_code=expected, nonce=nonce,
                  fixture_sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
                  proton_sha256=hashlib.sha256(proton.read_bytes()).hexdigest(),
                  scope='Normal Proton run via cmd output capture; direct diagnostic, not Steam-managed acceptance')
    try:
        paths = [stdout, stderr, case / 'steam-0.log']
        if any(p.stat().st_size > p2guest.LIMIT for p in paths):
            raise ValueError('Proton evidence exceeded output limit')
        out, err, log = [p.read_text(errors='replace') for p in paths]
        child = completion(log, expected)
        window = window_lifecycle(log, child['pid']) if child.get('pid') else dict(verified=False)
        marker = out.splitlines() == ['PHASE4_WINDOWS_OK ' + nonce]
        result.update(fixture_stdout=out, fixture_stderr=err, child=child, window=window,
                      marker_observed=marker, proton_log=log,
                      log_path=str(paths[2]), log_sha256=hashlib.sha256(paths[2].read_bytes()).hexdigest(),
                      log_bytes=paths[2].stat().st_size)
        if (reply['code'] == expected and not reply['error'] and child['verified']
                and (not out if negative else marker and window['verified'])):
            result['status'] = 'PASS'
    except (OSError, ValueError) as error:
        result['evidence_error'] = str(error)
    return result
