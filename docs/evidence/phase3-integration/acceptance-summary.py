"""Aggregate only completed, source-bound integrated acceptance evidence."""
from pathlib import Path
import hashlib,json
r=Path('/home/ubuntu/p3i/final')
source=json.loads((r/'source-r3.json').read_text())
commit=source['source_commit']
assert commit=='fdb784c8539fb7679f7ab6e350583f523a80728d'
evidence={}
def read(name):
 p=r/name
 data=p.read_bytes()
 evidence[name]=hashlib.sha256(data).hexdigest()
 return json.loads(data)
def accepted(name):
 result=read(name+'/result.json')
 assert result['passed'] and result['integrated_acceptance'],name
 if 'source_commit' in result: assert result['source_commit']==commit,name
 return result
matrix={}
for name in ['base-plain','base-luks']:
 accepted(name)
 assert read(name+'/baseline.json')['source_commit']==commit
matrix['A']=dict(status='PASS',evidence=['base-plain','base-luks'],scope='Two cold enforced boots and actual Plasma Wayland acceptance for each installation.')
provenance=read('base-plain/public-artifacts/provenance.json')
for role,letters in [('loader','BCD'),('uki','EFG')]:
 inputs=read('refusal-'+role+'-inputs/baseline.json')
 result=read('refusal-'+role+'-run/result.json')
 verdict=read('refusal-'+role+'-run/firmware-verdict.json')
 assert result['passed'] and result['security_acceptance'] and result['source_commit']==commit
 assert inputs['source_commit']==commit and inputs['artifact']['role']==role and inputs['load_only']
 assert inputs['artifact']['sha256']==provenance[role]['sha256']
 assert verdict['trusted']['load_status']=='0000000000000000'
 for letter,kind in zip(letters,['unsigned','untrusted','tampered']):
  assert verdict[kind]['load_status']=='800000000000000f' and verdict[kind]['authentication_record'].startswith('DENIED_IMAGE ')
  matrix[letter]=dict(status='PASS',evidence=['refusal-'+role+'-inputs','refusal-'+role+'-run','base-plain/public-artifacts/provenance.json'],scope='Actual integrated '+role+' bytes; trusted EFI probe observes firmware LoadImage rejection before execution.')
for letter,name in [('H','h-plain'),('I','i-plain'),('J','j-luks'),('K','k-plain'),('L','l-plain'),('M','m-plain')]:
 accepted(name)
 matrix[letter]=dict(status='PASS',evidence=[name])
repro=read('reproducibility.json')
assert repro['passed'] and repro['source']==source and repro['full_cmp_exit']==0
matrix['N']=dict(status='PASS',evidence=['reproducibility.json'],images=repro['images'])
regressions={}
for name in ['reg-payload','reg-space','reg-package','reg-interruption','reg-health','reg-service','security-direct-package']:
 regressions[name]=accepted(name)
audit=read('iso-audit/result.json')
assert audit['passed'] and audit['source_commit']==commit
assert audit['iso']['sha256']==repro['images']['A']['sha256']
result=dict(source=source,matrix=matrix,regressions=regressions,evidence_sha256=evidence,verdict='PHASE 3 VALIDATED',limits=['Initial installation and owner provisioning use compatibility setup; acceptance boots enforce Secure Boot.','Recovery companion signs loader and UKI; live SquashFS is not cryptographically covered.','K covers one bounded sync/rename interruption; its retained journal is not automatically reconciled.','No physical hardware, dual boot, real firmware enrollment, TPM unlock, arbitrary power-loss, whole-disk-full, key rotation/recovery or release signing qualification.'])
(r/'acceptance-summary.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
