"""Join original results and supplemental evidence without replacing failed attempts."""
from pathlib import Path
import hashlib,json
r=Path('/home/ubuntu/p4i/r2'); hashes={}
source='cac8998ad7730e69ae354c3162ef4a0677cfc162'
def read(name):
    data=(r/name).read_bytes();hashes[name]=hashlib.sha256(data).hexdigest();return json.loads(data)
def rpc(name):
    result=read('gaming-plain/'+name)['result'];assert result['code']==0,name
    return [json.loads(line) for line in result['output'].splitlines() if line.startswith('{')]
def accepted(name):
    result=read(name+'/result.json');assert result['passed'] and result['integrated_acceptance'],name
    if 'source_commit' in result:assert result['source_commit']==source
    return result
for name in ['base-plain','base-luks']:
    accepted(name);assert read(name+'/baseline.json')['source_commit']==source
original=read('gaming-plain/original-guest.json')
rerun=rpc('graphics-rerun.json')[0];checks=rerun['checks']
for name in ['packages','dependencies','gaming-packages','lib32-packages','icds','vulkan-enumeration','opengl','xwayland','elf-64','link-64','vulkan-64','elf-32','link-32','vulkan-32','missing-icd','corrupt-icd','wrong-architecture','missing-lib32-icd','gamemode-readiness','gamemode-invoke','gamemode-restoration']:
    assert checks[name]['status']=='PASS',name
steam=rpc('steam-inspect-closed.json')[0];assert steam['exit']['code']==0
runtime=rpc('steam-runtime.json')[0]
for name in ['client_elf','libraries','runtime_diagnostics']:assert runtime[name]['code']==0
proton=rpc('proton-prefix-diagnostic.json')[0]
assert proton['marker_observed'] and proton['reply']['code']==0
assert 'PHASE4_WINDOWS_OK '+proton['nonce'] in proton['reply']['output']
assert checks['proton-execution']['status']=='FAIL' and checks['proton-execution']['code']==0
assert checks['gamescope-launch']['code']==134 and checks['gamemode-test']['code']==255
negatives=rpc('negative-final.json')[0]['checks'];assert len(negatives)==9
assert all(v['status']=='PASS' for v in negatives.values())
final=rpc('final-inspect.json')[-1]['commands']
for name in ['graphics','gaming_status','gaming_doctor','dependencies','mangohud32']:assert final[name]['code']==0
doctor=json.loads(final['gaming_doctor']['output'])
for name in ['vulkan64','vulkan32']:assert doctor['checks'][name]['runtime']=='passed'
assert doctor['checks']['graphics_acceleration']['state']=='unsupported'
for arch in ['native','compat32']:
    devices=doctor['graphics'][arch]['devices'];assert devices and all(d['software'] for d in devices)
read('gaming-plain/inspection-complete.json')
read('base-luks/gaming-readiness.json')
assert read('graphics32/result.json')['completed']
visual32=read('graphics32/visual-observation.json')
assert visual32['elf32_opengl_presentation']=='PASS' and visual32['visible_mangohud']=='PASS'
read('graphics32/inspection.json');read('graphics32/workload.json')
security={name:accepted(name) for name in ['h-plain','i-plain','j-luks','k-plain','l-plain','m-plain-r2',
    'reg-payload','reg-space','reg-package','reg-health','reg-service','reg-interruption','security-direct-package']}
provenance=read('base-plain/public-artifacts/provenance.json')
for role in ['loader','uki']:
    inputs=read('refusal-'+role+'-inputs/baseline.json')
    outcome=read('refusal-'+role+'-run/result.json')
    verdict=read('refusal-'+role+'-run/firmware-verdict.json')
    assert inputs['artifact']['sha256']==provenance[role]['sha256'] and inputs['source_commit']==source
    assert outcome['passed'] and outcome['security_acceptance'] and outcome['source_commit']==source
    assert verdict['trusted']['load_status']=='0000000000000000'
    for kind in ['unsigned','untrusted','tampered']:
        assert verdict[kind]['load_status']=='800000000000000f'
        assert verdict[kind]['authentication_record'].startswith('DENIED_IMAGE ')
repro=read('reproducibility.json');assert repro['byte_identical'] and repro['full_file_cmp_exit_code']==0
assert repro['source']['source_commit']==source
audit=read('iso-audit/result.json');assert audit['passed'] and audit['source_commit']==source
rows=[
 ('A','PASS','Fresh plain and LUKS2 installations, two cold enforcing UEFI boots each, actual Plasma Wayland, Btrfs, network/audio and health checks.'),
 ('B','PASS','Signed pinned image inputs and coherent native/lib32 package database; Core and tools explicitly selected.'),
 ('C','PASS','Real native loader/ICDs, Vulkan enumeration and software device identity; no physical device qualified.'),
 ('D','PASS','ELF64 Vulkan clears/readbacks all 256 pixels; native WSI moving cube separately observed. Software only.'),
 ('E','PASS','ELF32 loader/ICD and 256-pixel readback pass. ELF32 OpenGL presentation also passes; 32-bit Vulkan WSI remains NOT RUN.'),
 ('F','PASS','Steam client reached usable empty login window, runtime/dependencies diagnosed, normal close exit 0. No authentication or game acceptance.'),
 ('G','FAIL','Normal Proton run exits 0 without nonce. Genuine runinprefix diagnostic in initialized disposable prefix executes Win32 window fixture and fresh nonce, exit 0; this bounded subcheck does not replace the failed normal path.'),
 ('H','UNSUPPORTED','Nested Gamescope aborts 134 on llvmpipe with missing DRM/VK_EXT_physical_device_drm prerequisites; no presentation pass.'),
 ('I','FAIL','Visible native Vulkan/OpenGL and ELF32 OpenGL MangoHud, plus ELF32 Vulkan layer invocation pass. GameMode wrapper/restoration passes; full self-test fails 255 without CPU governor interface. OpenGL window closes return 143, not zero.'),
 ('J','PASS','Actual status/doctor JSON validates and reports software readback separately from unsupported hardware acceleration. Raw PCI binding and driver-selection issues remain visible.'),
 ('K','FAIL','Four ICD/architecture and nine production negatives pass; vendor policies covered by controlled Rust fixtures. Gamescope unsupported-device launch still aborts, so the complete no-crash negative requirement is unmet.'),
 ('L','UNSUPPORTED','Initial signed gaming image passes encrypted boots and probes. Targeted feature transactions remain blocked proposals, not executable setup.'),
 ('M','PASS','All source-bound Phase 3 update/fallback/recovery/powercut/metadata gates and Phase 2 payload/space/package/health/service/interruption/direct-package regressions pass.'),
 ('N','PASS','Enforced real boot plus exact integrated loader/UKI trusted controls and unsigned/untrusted/tampered firmware refusals with denied-image records.'),
 ('O','PASS','Independent clean builds, full-file comparison exit 0 and identical package manifests/ISO SHA256.'),
 ('P','NOT RUN','NVIDIA/AMD/Intel/hybrid, controllers, hardware Vulkan, VRR/HDR and real game frametimes require approved physical qualification.')]
definitions=json.loads((r/'harness/tests/fixtures/phase4/matrix.json').read_text())['scenarios']
assert [x['id'] for x in definitions]==[x[0] for x in rows]
result={'schema_version':1,'source_commit':source,'validation_commit':'722f3b97ae67587b895bce68c44608f34e4c6a8a',
 'gaming_validated':False,'physical_gpu_qualified':False,'verdict':'PHASE 4 NOT YET VALIDATED',
 'scenarios':[dict(definition,status=status,actual=actual) for definition,(_,status,actual) in zip(definitions,rows)],
 'security':security,'evidence_sha256':hashes,'reproducibility':repro,
 'original_checks':{k:{n:v.get(n) for n in ['status','code','error']} for k,v in original['checks'].items()},
 'rerun_checks':{k:{n:v.get(n) for n in ['status','code','error']} for k,v in checks.items()},
 'production_negatives':{k:{'status':v['status'],'code':v['reply']['code']} for k,v in negatives.items()}}
(r/'integration-matrix.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({x['id']:x['status'] for x in result['scenarios']},indent=2))
