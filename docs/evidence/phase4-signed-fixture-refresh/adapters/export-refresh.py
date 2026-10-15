from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,tarfile
root=Path('/home/ubuntu/p41/fixture-refresh')
result=json.loads((root/'result.json').read_text())
assert result['completed'] and result['test_status']=='PASS' and result['test_exit']==0
assert result['baseline_unchanged'] and result['parent_state_unchanged'] and result['qemu_returncode']==0
processes=[]
for proc in Path('/proc').glob('[0-9]*'):
    try:
        cmd=(proc/'cmdline').read_bytes().split(b'\0')
        if cmd and cmd[0].endswith(b'qemu-system-x86_64'):processes.append(int(proc.name))
    except OSError:pass
assert not processes
(root/'cleanup.json').write_text(json.dumps(dict(time=datetime.now(timezone.utc).isoformat(),qemu_processes=processes,result=result),indent=2)+'\n')
files=[p for p in sorted(root.rglob('*')) if p.is_file() and not p.is_symlink() and
       p.name not in ['disk.qcow2','raw-manifest.json'] and p.suffix!='.sock']
manifest={p.relative_to(root).as_posix():dict(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in files}
(root/'raw-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
archive=root.parent/'fixture-refresh-raw.tar.gz'
assert not archive.exists()
with tarfile.open(archive,'w:gz') as tar:
    for p in files+[root/'raw-manifest.json']:tar.add(p,arcname=p.relative_to(root).as_posix(),recursive=False)
receipt=dict(path=str(archive),bytes=archive.stat().st_size,sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),payload_members=len(files),private=True,private_signing_key_exported=False)
(root.parent/'fixture-refresh-export.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt))
