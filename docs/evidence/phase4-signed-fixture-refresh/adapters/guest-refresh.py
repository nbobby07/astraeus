"""TEST ONLY: refresh the exact dry-run database inside a private mount namespace."""
from pathlib import Path
from contextlib import ExitStack
from datetime import datetime, timezone
import base64, hashlib, json, os, subprocess, sys, tempfile, time
import phase4_guest as guest

guest.p2guest.guard()
assert Path('/proc/self/ns/mnt').readlink() != Path('/proc/1/ns/mnt').readlink()
prefix, desktop = guest.session('tester')
assert prefix
result = dict(started=datetime.now(timezone.utc).isoformat(), checks={}, desktop=desktop,
              scope='TEST ONLY: unchanged database bytes; ephemeral namespace trust; no package installation')

def run(name, argv, expected=0):
    reply = guest.execute([str(x) for x in argv], timeout=90)
    result['checks'][name] = reply
    assert reply['error'] is None and reply['code'] == expected, (name, reply)
    return reply['output']

def sha(data):
    return hashlib.sha256(data).hexdigest()

try:
    with tempfile.TemporaryDirectory(prefix='phase41-signing-') as temporary, ExitStack() as mounts:
        work = Path(temporary); work.chmod(0o755)
        database = Path('/var/lib/pacman/sync/distro.db')
        signature = Path(str(database)+'.sig')
        original = database.read_bytes()
        assert sha(original) == '7f3515f1cdc3453ed606340f2ac0715faf0e327898e9b51de1f7ec5d975d6dca'
        config = Path('/etc/pacman.conf').read_bytes()
        result['original'] = dict(database_sha256=sha(original), signature_sha256=sha(signature.read_bytes()),
                                  pacman_conf_sha256=sha(config))
        run('expired-original', prefix+['pacman','--sync','--list','distro'], expected=1)
        assert 'expired' in result['checks']['expired-original']['output']
        for index, target in enumerate(['/etc/pacman.d/gnupg','/var/lib/pacman/sync']):
            area = work/str(index); area.mkdir()
            for name in ['upper','work']: (area/name).mkdir()
            run('mount-'+str(index), ['mount','-t','overlay','overlay','-o',
                f'lowerdir={target},upperdir={area}/upper,workdir={area}/work',target])
            mounts.callback(subprocess.run, ['umount','--lazy',target], check=True)
        home = work/'signer'; home.mkdir(mode=0o700)
        gpg = ['gpg','--homedir',str(home),'--batch']
        mounts.callback(subprocess.run, ['gpgconf','--homedir',str(home),'--kill','all'], check=True)
        mounts.callback(subprocess.run, ['gpgconf','--homedir','/etc/pacman.d/gnupg','--kill','all'], check=True)
        run('generate-key',gpg+['--pinentry-mode','loopback','--passphrase','', '--quick-generate-key',
            'Astraeus Phase 4.1 disposable K-gate database fixture 2026-10-11','ed25519','sign','7d'])
        listing=run('signer-identity',gpg+['--with-colons','--list-keys'])
        fingerprint=next(x.split(':')[9] for x in listing.splitlines() if x.startswith('fpr:'))
        pub=next(x.split(':') for x in listing.splitlines() if x.startswith('pub:'))
        assert len(fingerprint)==40 and int(pub[5]) <= time.time() < int(pub[6])
        assert 0 < int(pub[6])-int(pub[5]) <= 7*86400
        fixture=work/'distro.db';fixture.write_bytes(original)
        run('sign-database',gpg+['--local-user',fingerprint,'--output',str(work/'distro.db.sig'),'--detach-sign',str(fixture)])
        public=work/'repository-key.asc'
        run('export-public-key',gpg+['--armor','--output',str(public),'--export',fingerprint])
        verified=run('verify-detached-signature',gpg+['--status-fd','1','--verify',str(work/'distro.db.sig'),str(fixture)])
        assert '[GNUPG:] VALIDSIG '+fingerprint+' ' in verified
        new_signature=(work/'distro.db.sig').read_bytes()
        signature.write_bytes(new_signature)
        # Required trusted-only policy must reject the new signer until local test trust is explicit.
        run('untrusted-signer',prefix+['pacman','--sync','--list','distro'],expected=1)
        assert any(x in result['checks']['untrusted-signer']['output'].lower() for x in ['unknown','signature','key'])
        run('import-namespace-key',['pacman-key','--add',str(public)])
        run('trust-namespace-key',['pacman-key','--lsign-key',fingerprint])
        run('namespace-fingerprint',['pacman-key','--finger',fingerprint])
        policy=run('signature-policy',['pacman-conf','--repo','distro','SigLevel'])
        for required in ['PackageRequired','PackageTrustedOnly','DatabaseRequired','DatabaseTrustedOnly']:
            assert required in policy.split(),policy
        run('signed-database-accepted',prefix+['pacman','--sync','--list','distro'])
        database.write_bytes(original+b'\nTAMPERED VALIDATION CONTROL\n')
        run('tampered-database',prefix+['pacman','--sync','--list','distro'],expected=1)
        assert any(x in result['checks']['tampered-database']['output'].lower() for x in ['signature','pgp'])
        database.write_bytes(original)
        run('restored-signed-database',prefix+['pacman','--sync','--list','distro'])
        output=run('dependency-mismatch',['unshare','--mount','--propagation','private',sys.executable,
            str(guest.HERE/'phase4_negatives.py'),'--case','dependency-mismatch'])
        case=json.loads(output)
        assert case['status']=='PASS' and case['reply']['code']==1
        assert 'inconsistent graphics package state' in case['reply']['output']
        assert 'expired' not in case['reply']['output'].lower()
        result['dependency_mismatch']=case
        assert database.read_bytes()==original and Path('/etc/pacman.conf').read_bytes()==config
        result['fixture']=dict(fingerprint=fingerprint,created_epoch=int(pub[5]),expires_epoch=int(pub[6]),
            database_sha256=sha(original),signature_sha256=sha(new_signature),public_key_sha256=sha(public.read_bytes()),
            database_base64=base64.b64encode(original).decode(),signature_base64=base64.b64encode(new_signature).decode(),
            public_key_ascii=public.read_text(),package_signatures='Unchanged; package installation is outside this dry-run fixture qualification',
            trust='Existing keyring overlaid in private mount namespace; public key imported and locally signed there only')
        result['status']='PASS'
except BaseException as error:
    result['status']='FAIL'; result['error']=type(error).__name__+': '+str(error)
finally:
    result['finished']=datetime.now(timezone.utc).isoformat()
    print(json.dumps(result))
sys.exit(0 if result['status']=='PASS' else 1)
