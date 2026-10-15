#!/usr/bin/python3 -I
"""TEST ONLY: stop after a real sync at a native generation-selection boundary."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

state=Path('/var/lib/astraeus-validation')
result=subprocess.run([str(state/'sync-real'),*sys.argv[1:]])
if result.returncode: sys.exit(result.returncode)
if os.geteuid()!=0 or not Path('/dev/virtio-ports/org.astraeus.validation').exists(): sys.exit(0)
config=state/'powercut.json'
pending=Path('/.snapshots/astraeus/pending.json')
if not config.exists() or not pending.exists(): sys.exit(0)
settings=json.loads(config.read_text())
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
if settings['boot_id']!=boot: sys.exit(0)
journal=json.loads(pending.read_text())
selection=journal.get('selection') or {}
generation=selection.get('current')
if journal.get('operation')!='generation-select' or not generation: sys.exit(0)
if not Path('/efi/loader/astraeus.next').exists(): sys.exit(0)
# This is the actual persisted candidate loader configuration before its rename.
metadata=json.loads((Path('/.snapshots/astraeus/generations')/generation/'metadata.json').read_text())
assert metadata['id']==generation and metadata['root_kind']=='current'
assert settings['checkpoint']=='generation-activation'
receipt=dict(checkpoint=settings['checkpoint'],boot_id=boot,generation=generation,
             root_uuid=metadata['root']['uuid'],uki_sha256=metadata['uki_sha256'],
             blocked=True,journal=journal,stage='candidate loader configuration synced before rename')
path=Path('/var/log/astraeus-validation-phase3-barrier.json')
with path.open('x') as stream:
    json.dump(receipt,stream)
    stream.flush()
    os.fsync(stream.fileno())
subprocess.run([str(state/'sync-real')],check=True)
while True: time.sleep(1)
