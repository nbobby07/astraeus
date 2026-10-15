from pathlib import Path
from datetime import datetime,timezone
import json,subprocess,time
root=Path('/home/ubuntu/p41');manifest=json.loads((root/'disk-parts.json').read_text())
deadline=datetime.fromisoformat('2026-10-11T05:00:00+00:00').timestamp()
print('WAITING_FOR_BASELINE_PARTS',datetime.now(timezone.utc).isoformat(),flush=True)
while not all((root/'parts'/x['name']).is_file() and (root/'parts'/x['name']).stat().st_size==x['bytes'] for x in manifest):
 if time.time()>deadline:raise TimeoutError('Restoration deadline exceeded')
 time.sleep(5)
subprocess.run(['python3',str(root/'assemble.py')],check=True)
print('STARTING_INSTALLED_ASTRAEUS',datetime.now(timezone.utc).isoformat(),flush=True)
subprocess.run(['python3',str(root/'run-focused.py')],check=True)
