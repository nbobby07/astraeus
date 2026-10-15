#!/bin/bash
set -euo pipefail
chmod 700 /home/ubuntu/p41
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends qemu-system-x86 qemu-utils ovmf python3-pil curl ca-certificates
python3 - <<'PY'
from pathlib import Path
import hashlib,json,subprocess,os
code=Path('/usr/share/OVMF/OVMF_CODE_4M.secboot.fd')
digest=hashlib.sha256(code.read_bytes()).hexdigest()
result=dict(os_release=Path('/etc/os-release').read_text(),kvm=Path('/dev/kvm').exists(),qemu=subprocess.check_output(['qemu-system-x86_64','--version'],text=True),firmware_sha256=digest,packages=subprocess.check_output(['dpkg-query','-W','ovmf','qemu-system-x86','qemu-utils'],text=True),memory=Path('/proc/meminfo').read_text(),cpu=os.cpu_count())
Path('/home/ubuntu/p41/host.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result),flush=True)
assert result['kvm']
assert digest=='1286f2a3217d09b374d05951355d7a561c8bacecd74845c8a1fbb71a48c0de8d', 'firmware CODE mismatch'
PY
