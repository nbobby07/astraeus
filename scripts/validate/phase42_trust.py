"""Image-aware public trust checks for the maintained UKI, not running-root confirmation."""
import json
import re


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def object_json(text, label):
    def invalid_constant(value):
        raise RuntimeError('invalid provider JSON constant: ' + value)

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate provider field: ' + key)
            result[key] = value
        return result

    require(isinstance(text, str) and len(text) <= 1024 * 1024, 'invalid ' + label + ' response size')
    try:
        value = json.loads(text, object_pairs_hook=unique, parse_constant=invalid_constant)
    except ValueError as error:
        raise RuntimeError('invalid ' + label + ' JSON') from error
    require(isinstance(value, dict) and type(value.get('schema_version')) is int
            and value['schema_version'] == 1, 'unsupported ' + label + ' response')
    return value


def enforced(status, pin):
    require(isinstance(status, dict), 'invalid firmware status')
    firmware = status.get('firmware')
    require(isinstance(firmware, dict) and status.get('certificate_sha256') == pin
            and firmware.get('SecureBoot') is True and firmware.get('SetupMode') is False
            and 'AuditMode' in firmware and (firmware['AuditMode'] is False or firmware['AuditMode'] is None),
            'candidate did not boot with the intended owner and enforcing Secure Boot')
    db, dbx = firmware.get('db'), firmware.get('dbx')
    require(isinstance(db, dict) and isinstance(dbx, dict)
            and db.get('contains_signer_certificate') is True
            and dbx.get('contains_signer_certificate') is False,
            'candidate signer enrollment or revocation evidence is incomplete')


def verify_maintained_uki(command, pin, *, require_ready=False):
    """command returns checked stdout. No private-key or clean-state check unless requested."""
    require(isinstance(pin, str) and re.fullmatch('[0-9a-f]{64}', pin), 'invalid baseline certificate pin')
    status = object_json(command('astraeus-secure-boot', 'status', '--json'), 'security status')
    enforced(status, pin)
    require(status.get('policy') == 'configured' and status.get('identity') == 'valid',
            'configured signing identity is invalid or unavailable')
    artifacts = status.get('artifacts')
    uki = artifacts.get('uki') if isinstance(artifacts, dict) else None
    require(isinstance(uki, dict), 'maintained UKI observation is unavailable')
    path, expected = uki.get('path'), uki.get('sha256')
    require(isinstance(path, str) and re.fullmatch(
        r'/efi/EFI/(?:Linux/[a-z][a-z0-9-]*-linux\.efi|Astraeus/maintenance\.efi)', path),
        'unexpected maintained UKI path')
    require(uki.get('signature') == 'valid-for-configured-certificate'
            and isinstance(expected, str) and re.fullmatch('[0-9a-f]{64}', expected),
            'maintained UKI signature or hash is invalid or unavailable')
    if require_ready:
        ready = object_json(command('astraeus-boot-artifact', 'ready', '/efi'), 'boot provider readiness')
        require(set(ready) == {'schema_version', 'systemd_version', 'loader_verified', 'firmware_trusted'}
                and type(ready.get('systemd_version')) is int and ready['systemd_version'] == 262
                and ready.get('loader_verified') is True and ready.get('firmware_trusted') is True,
                'boot provider readiness was not verified')
    verdict = object_json(command('astraeus-boot-artifact', 'verify', path), 'UKI trust verdict')
    require(set(verdict) == {'schema_version', 'sha256', 'signature_verified', 'firmware_trusted'}
            and verdict.get('sha256') == expected and verdict.get('signature_verified') is True
            and verdict.get('firmware_trusted') is True, 'maintained UKI image trust was not verified')
    return {'scope': 'maintained-installed-uki', 'path': path, 'sha256': expected,
            'certificate_sha256': pin, 'signature_verified': True, 'firmware_trusted': True,
            'provider_readiness_checked': require_ready}
