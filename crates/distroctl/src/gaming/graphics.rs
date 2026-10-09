use super::{Check, Graphics, GraphicsProvider, Runtime, State};
use distro_graphics::{Architecture, GraphicsReport, State as Evidence, VulkanDevice};

fn software(device: &VulkanDevice) -> bool {
    device.software || device.device_type == 4 || device.driver_id == Some(13)
}

fn vulkan(arch: &Architecture) -> Check {
    let devices = arch
        .devices
        .iter()
        .map(|d| {
            format!(
                "{} ({}, readback {:?})",
                d.name,
                if software(d) {
                    "software"
                } else if d.device_type == 3 {
                    "virtual"
                } else {
                    "device"
                },
                d.rendering
            )
        })
        .collect::<Vec<_>>()
        .join(", ");
    let detail = format!("{}-bit: installed loader {:?}; {} usable system ICDs; enumeration {:?}; devices [{}]. Per-device offscreen smoke only; presentation and game compatibility are untested.",
        arch.bits, arch.loader, arch.icds.iter().filter(|i| i.state == Evidence::Present).count(), arch.enumeration, devices);
    let (state, runtime) = match arch.enumeration {
        Evidence::Passed if arch.devices.iter().any(|d| d.rendering == Evidence::Passed) => {
            (State::RuntimeVerified, Runtime::Passed)
        }
        Evidence::Failed => (State::Unknown, Runtime::Failed),
        Evidence::Passed if arch.devices.iter().any(|d| d.rendering == Evidence::Failed) => {
            (State::Unknown, Runtime::Failed)
        }
        Evidence::Absent => (State::NotInstalled, Runtime::Untested),
        Evidence::Unsupported => (State::Unsupported, Runtime::Untested),
        _ if arch.loader == Evidence::Absent => (State::NotInstalled, Runtime::Untested),
        _ => (State::Unknown, Runtime::Untested),
    };
    Check {
        state,
        runtime,
        detail,
    }
}

impl GraphicsProvider for GraphicsReport {
    fn readiness(&self) -> Graphics {
        let physical = |arch: &Architecture, indices: &[usize]| {
            arch.enumeration == Evidence::Passed
                && indices.iter().any(|&i| {
                    arch.devices.get(i).is_some_and(|d| {
                        !software(d)
                            && matches!(d.device_type, 1 | 2)
                            && d.rendering == Evidence::Passed
                    })
                })
        };
        let matched = self.gpus.as_ref().and_then(|gpus| {
            gpus.iter().find(|g| {
                g.hardware.driver.is_some()
                    && physical(&self.native, &g.native_devices)
                    && physical(&self.compat32, &g.compat32_devices)
            })
        });
        let mut acceleration = Check::new(State::Unknown,
            "No same physical GPU has verified 64-bit and 32-bit readback with an observed kernel binding. Use gaming doctor --probe; installed packages do not prove acceleration.");
        if let Some(gpu) = matched {
            acceleration = Check { state: State::RuntimeVerified, runtime: Runtime::Passed,
                detail: format!("Both architectures passed offscreen readback on GPU {:?}, driver {:?}. This does not qualify presentation, driver/module trust or games.", gpu.hardware.pci_address, gpu.hardware.driver) };
        } else if self.native.enumeration == Evidence::Passed
            && !self.native.devices.is_empty()
            && self
                .native
                .devices
                .iter()
                .all(|d| software(d) || d.device_type == 3)
        {
            acceleration = Check::new(State::Unsupported,
                "Only software or virtual Vulkan devices enumerated. Physical hardware acceleration is not established, even when readback passes.");
        }
        Graphics {
            acceleration,
            vulkan64: vulkan(&self.native),
            vulkan32: vulkan(&self.compat32),
            vrr: Check::new(
                State::Unknown,
                "VRR requires actual compositor and physical display qualification",
            ),
            hdr: Check::new(
                State::Unknown,
                "HDR requires actual compositor and physical display qualification",
            ),
        }
    }

    fn evidence(&self) -> Option<&GraphicsReport> {
        Some(self)
    }
}
