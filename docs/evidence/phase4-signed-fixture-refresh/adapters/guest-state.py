"""Read-only restoration witness; no key contents are exported."""
from pathlib import Path
import hashlib,json
import phase4_guest as guest
guest.p2guest.guard()
def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
trees={}
for root in ['/etc/pacman.d/gnupg','/var/lib/pacman/local','/var/lib/pacman/sync']:
    entries={str(p.relative_to(root)):digest(p) for p in sorted(Path(root).rglob('*')) if p.is_file()}
    trees[root]=dict(files=len(entries),sha256=hashlib.sha256(json.dumps(entries,sort_keys=True).encode()).hexdigest())
paths=['/etc/pacman.conf','/var/lib/pacman/sync/distro.db','/var/lib/pacman/sync/distro.db.sig',
       '/usr/bin/distroctl','/usr/bin/distro-graphics-probe','/usr/bin/distro-graphics-probe32']
print(json.dumps(dict(trees=trees,files={str(p):digest(p) for p in map(Path,paths) if p.exists()})))
