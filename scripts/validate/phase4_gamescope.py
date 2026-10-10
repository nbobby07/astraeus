#!/usr/bin/env python3
"""TEST ONLY: bounded Wayland Gamescope smoke with a conservative DRM preflight."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

from phase4_guest import execute, verdict, p2guest


def capabilities(document):
    """Inspect every enumerated device; never select a convenient passing GPU."""
    devices = document['Device Properties and Extensions']
    if not isinstance(devices, dict) or not devices:
        raise ValueError('Vulkan device inventory is empty or malformed')
    observations = []
    for key, device in devices.items():
        props = device['VkPhysicalDeviceProperties']
        extensions = device['Device Extensions']
        if not isinstance(extensions, dict) or not isinstance(props['deviceName'], str):
            raise ValueError('Unrecognized vulkaninfo device schema')
        reason = None
        if 'VK_EXT_physical_device_drm' not in extensions:
            reason = 'VK_EXT_physical_device_drm is absent'
        else:
            drm = device['VkPhysicalDeviceDrmPropertiesEXT']
            if type(drm['hasRender']) is not bool:
                raise ValueError('Unrecognized Vulkan DRM property type')
            if not drm['hasRender']:
                reason = 'Vulkan device has no DRM render node'
        observations.append(dict(device=key, name=props['deviceName'], missing=reason,
                                 properties=props, extensions=extensions,
                                 drm=device.get('VkPhysicalDeviceDrmPropertiesEXT')))
    missing = [item for item in observations if item['missing']]
    if missing:
        reason = ('No enumerated device supplies the DRM render capability needed by this '
                  'Gamescope Wayland/XWayland test' if len(missing) == len(observations) else
                  'Mixed DRM capabilities: automatic Gamescope device selection is not qualified by this adapter')
        return dict(code=77, status='UNSUPPORTED', reason=reason, devices=observations)
    return dict(code=0, status='PASS', reason='DRM prerequisites observed; presentation remains untested',
                devices=observations)


def smoke(backend='wayland', check_only=False):
    result = dict(presentation='NOT RUN', launched=False, scope='validation adapter, not a product launcher')
    if backend != 'wayland' or not os.environ.get('WAYLAND_DISPLAY'):
        return dict(result, code=77, status='UNSUPPORTED',
                    reason='This adapter requires a live Wayland session and --backend wayland')
    for name in ['gamescope', 'vulkaninfo', 'vkcube']:
        if not shutil.which(name):
            return dict(result, code=77, status='UNSUPPORTED', reason=f'Missing optional tool: {name}')
    with tempfile.TemporaryDirectory(prefix='phase4-gamescope-') as temp:
        query = execute(['vulkaninfo', '--vkconfig_output', temp], timeout=30)
        result['query'] = query
        if query['code'] != 0 or query['error']:
            return dict(result, code=2, status='FAIL', reason='Vulkan capability query failed; inspect its actual exit and diagnostics')
        path = Path(temp) / 'vulkaninfo.json'
        try:
            if path.stat().st_size > p2guest.LIMIT:
                raise ValueError('Vulkan capability output exceeded the evidence limit')
            check = capabilities(json.loads(path.read_text()))
        except (OSError, ValueError, KeyError, TypeError) as error:
            return dict(result, code=2, status='FAIL', reason=f'Cannot establish Gamescope prerequisites: {error}')
    result.update(check)
    if result['code'] != 0 or check_only:
        return result
    # Presence of these prerequisites is not sufficient to promise rendering.
    if not p2guest.PORT.exists():
        return dict(result, code=2, status='FAIL', reason='Rendering requires the disposable validation guest')
    launch = execute(['gamescope', '--backend', 'wayland', '-w', '1280', '-h', '720',
                      '--', 'vkcube', '--c', '60'], timeout=30)
    return dict(result, code=launch['code'] if not launch['error'] else 2,
                status=verdict(launch), launched=True, launch=launch,
                reason='Inspect actual frames separately; process completion alone does not prove presentation')


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def main():
    try:
        parser = Parser(description=__doc__)
        parser.add_argument('--backend', default='wayland')
        parser.add_argument('--check-only', action='store_true')
        args = parser.parse_args()
        if os.geteuid() == 0:
            raise ValueError('Run capability probes as the disposable desktop user, never root')
        result = smoke(args.backend, args.check_only)
    except ValueError as error:
        result = dict(code=2, status='FAIL', launched=False, presentation='NOT RUN', reason=str(error))
    print(json.dumps(result))
    # Preserve a signal as failure, never turn it into an unsupported refusal.
    sys.exit(result['code'] if result['code'] >= 0 else 128 - result['code'])


if __name__ == '__main__':
    main()
