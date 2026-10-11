from pathlib import Path
import hashlib,json,os,tarfile,datetime
root=Path('/home/ubuntu/p41');out=root/'guest-r1'
result=json.loads((out/'result.json').read_text());assert result['completed'] and result['qemu_returncode']==0 and result['baseline_unchanged']
processes=[]
for proc in Path('/proc').glob('[0-9]*'):
 try:
  cmd=(proc/'cmdline').read_bytes().split(b'\0')
  if cmd and cmd[0].endswith(b'qemu-system-x86_64'):processes.append(int(proc.name))
 except OSError:pass
assert not processes,processes
cleanup=dict(time=datetime.datetime.now(datetime.timezone.utc).isoformat(),qemu_processes=processes,guest_result=result)
(root/'cleanup.json').write_text(json.dumps(cleanup,indent=2)+'\n')
files=[]
for path in out.rglob('*'):
 if not path.is_file() or path.is_symlink() or path.name=='disk.qcow2' or path.suffix in ['.sock','.ppm']:continue
 if 'runtime-inputs' in path.relative_to(out).parts:continue
 files.append(path)
for path in root.iterdir():
 if path.is_file() and path.suffix in ['.py','.sh','.json','.log']:files.append(path)
files.append(root/'base/baseline.json')
manifest={}
for path in sorted(files):
 with path.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
 manifest[str(path.relative_to(root))]=dict(bytes=path.stat().st_size,sha256=digest)
(root/'raw-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
archive=root/'acceptance-raw.tar.gz'
with tarfile.open(archive,'w:gz') as tar:
 for path in files+[root/'raw-manifest.json']:tar.add(path,arcname=str(path.relative_to(root)),recursive=False)
with archive.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
receipt=dict(path=str(archive),bytes=archive.stat().st_size,sha256=digest,members=len(files)+1,private=True,secret_password_included=False)
(root/'export.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
