"""Export text evidence and public EFI fixtures, with separately retained raw context."""
from pathlib import Path
import hashlib,io,json,re,tarfile,time
r=Path('/home/ubuntu/p4i/r2')
def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
excluded={'candidate','harness','harness-validation','repository-keyring','adapters','adapters-latest','__pycache__','public-export'}
suffixes={'.json','.log','.txt','.py','.sh','.c','.md','.efi','.crt','.cer','.esl','.auth'}
secrets=[(r/'private/guest.txt').read_bytes().strip(),Path('/home/ubuntu/p2-secrets/guest.txt').read_bytes().strip()]
assert all(secrets)
public={};private={};redactions={}
for p in sorted(r.rglob('*')):
    rel=p.relative_to(r)
    if not p.is_file() or p.is_symlink() or set(rel.parts)&excluded:continue
    if rel.parts[0]=='build' and 'evidence' not in rel.parts:continue
    if p.name.startswith(('acceptance-public','acceptance-private','acceptance-export')):continue
    is_private='private' in rel.parts or p.suffix in {'.key','.fd'}
    fixture=p.name in {'windows-smoke.exe','vulkan64','vulkan32'}
    screenshot=p.suffix=='.png' and (rel.parts[0]=='visual-evidence' or str(rel) in {'graphics32/frame-1.png','graphics32/frame-2.png','graphics32/closed.png'})
    if p.suffix not in suffixes|{'.key','.fd','.png'} and p.name not in {'exit-code'} and not fixture:continue
    data=p.read_bytes()
    private[str(rel)]={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
    if is_private or p.name=='acceptance-summary.py' or (p.suffix=='.png' and not screenshot):continue
    if p.suffix in {'.efi','.cer','.esl','.auth'} or fixture or screenshot:
        assert not any(s in data for s in secrets),str(rel)
        public[str(rel)]=(data,0)
        continue
    count=0
    for s in secrets:
        count+=data.count(s);data=data.replace(s,b'<redacted-disposable-test-password>')
    data,n=re.subn(rb'\$y\$[A-Za-z0-9./]+\$[A-Za-z0-9./]+\$[A-Za-z0-9./]+',b'<redacted-test-password-hash>',data)
    count+=n
    assert not re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',data),str(rel)
    public[str(rel)]=(data,count)
    if count:redactions[str(rel)]=count
def add(archive,name,data):
    info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o600;info.mtime=0
    archive.addfile(info,io.BytesIO(data))
manifest={name:{'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)} for name,(data,_) in public.items()}
with tarfile.open(r/'acceptance-public.tar.gz','x:gz') as archive:
    for name,(data,_) in public.items():add(archive,name,data)
    add(archive,'EXPORT-MANIFEST.json',(json.dumps(manifest,indent=2)+'\n').encode())
    add(archive,'REDACTIONS.json',(json.dumps(redactions,indent=2)+'\n').encode())
with tarfile.open(r/'acceptance-private-context.tar.gz','x:gz') as archive:
    for name in private:
        data=(r/name).read_bytes()
        assert hashlib.sha256(data).hexdigest()==private[name]['sha256'],name
        add(archive,name,data)
    add(archive,'EXPORT-MANIFEST.json',(json.dumps(private,indent=2)+'\n').encode())
receipt={'created_unix':time.time(),'files':{},'public_members':len(public),'private_members':len(private),
         'redactions':redactions,'excluded':'Guest disks, ISO files, source/build checkouts, downloaded tool archives and signing keyrings. The unused legacy acceptance-summary.py template is only in raw private context. ISO/source/baselines and signed repository have separate verified exports; raw private context contains test keys and VARS.'}
for name in ['acceptance-public.tar.gz','acceptance-private-context.tar.gz']:
    p=r/name;receipt['files'][name]={'bytes':p.stat().st_size,'sha256':digest(p)}
(r/'acceptance-export-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt,indent=2))
