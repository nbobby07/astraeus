"""Extract explicitly inspected test runtimes as the disposable desktop user."""
from pathlib import Path
import hashlib,json,os,tarfile
assert os.geteuid()!=0 and Path('/dev/virtio-ports/org.astraeus.validation').exists()
home=Path.home();assert home==Path('/home/tester')
share=Path('/mnt/astraeus-validation/runtime-inputs')
items=[('GE-Proton11-7-x86_64.tar.gz','c5448b76a230384e2d7bc6beb5ccb97bafb7e2c3b6c527cb03a1a546bbcb00a0',home/'.local/share/Steam/compatibilitytools.d','GE-Proton11-7-x86_64'),
 ('SteamLinuxRuntime_4.tar.xz','3226d8234e7c0542ee767837832bfb1dad5e5e2dc944ec97eb221b437f6b9349',home/'phase4-runtimes','SteamLinuxRuntime_4')]
result=[]
for name,expected,destination,top in items:
 archive=share/name
 with archive.open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==expected
 destination.mkdir(parents=True,exist_ok=True);assert not (destination/top).exists()
 with tarfile.open(archive) as tar:
  assert all(Path(member.name).parts[0]==top for member in tar.getmembers())
  tar.extractall(destination,filter='data')
 result.append(dict(archive=name,sha256=expected,destination=str(destination/top)))
assert (items[0][2]/items[0][3]/'proton').is_file()
assert (items[1][2]/items[1][3]/'_v2-entry-point').is_file()
print(json.dumps(result))
