from pathlib import Path
import hashlib,json,os,tarfile
root=Path('/home/ubuntu/p41')
manifest=json.loads((root/'disk-parts.json').read_text())
assert len(manifest)>1
output=root/'base/disk.qcow2'
assert not output.exists(), 'do not replace an existing restored baseline'
staging=root/'base/disk.assembling'
with staging.open('xb') as stream:
 for item in manifest:
  path=root/'parts'/item['name'];assert path.stat().st_size==item['bytes']
  digest=hashlib.sha256()
  with path.open('rb') as part:
   while data:=part.read(1024*1024):digest.update(data);stream.write(data)
  assert digest.hexdigest()==item['sha256'],item['name']
 stream.flush();os.fsync(stream.fileno())
with staging.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
assert actual=='eafebca45776fca62b848c77dfbb40dd3189b616727fe0bc9b8c9cb03eaa67a9'
staging.rename(output);output.chmod(0o444)
(root/'base/vars.fd').chmod(0o444)
base=json.loads((root/'base/baseline.json').read_text())
assert hashlib.sha256((root/'base/vars.fd').read_bytes()).hexdigest()==base['sha256']['vars.fd']
(root/'restored.json').write_text(json.dumps(dict(disk_sha256=actual,bytes=output.stat().st_size,vars_sha256=base['sha256']['vars.fd'],parts=len(manifest)),indent=2)+'\n')
print('RESTORED_BASELINE_VERIFIED',flush=True)
