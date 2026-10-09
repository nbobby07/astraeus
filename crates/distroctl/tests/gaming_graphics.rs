use distro_graphics::{
    diagnose, Architecture, GraphicsReport, Observations, State as Evidence, VulkanDevice,
};
use distro_hardware::{normalize, RawGpu, RawHardware};
use distroctl::gaming::{self, GraphicsProvider, Runtime, State};

fn fixture(kind: u32) -> GraphicsReport {
    let device = VulkanDevice {
        name: "fixture renderer".into(),
        vendor_id: 0x1002,
        device_id: 0x744c,
        device_type: kind,
        api_version: (1 << 22) | (3 << 12),
        driver_version: 1,
        driver_name: None,
        driver_info: None,
        driver_id: None,
        pci_address: Some("0000:01:00.0".into()),
        software: kind == 4,
        rendering: Evidence::Passed,
    };
    let arch = |bits| Architecture {
        bits,
        loader: Evidence::Present,
        icds: vec![],
        enumeration: Evidence::Passed,
        loader_version: Some(1 << 22),
        devices: vec![device.clone()],
    };
    diagnose(
        normalize(RawHardware {
            pci: Some(vec![RawGpu {
                vendor_id: Some("0x1002".into()),
                device_id: Some("0x744c".into()),
                pci_address: Some("0000:01:00.0".into()),
                driver: Some("amdgpu".into()),
                ..Default::default()
            }]),
            ..Default::default()
        }),
        Observations {
            native: Some(arch(64)),
            compat32: Some(arch(32)),
            ..Default::default()
        },
    )
}

#[test]
fn preserves_raw_graphics_and_separates_software_virtual_and_physical_execution() {
    for kind in [2, 3, 4] {
        let graphics = fixture(kind);
        let report = gaming::report(&Default::default(), &graphics);
        assert_eq!(report.checks["vulkan64"].runtime, Runtime::Passed);
        assert_eq!(report.checks["vulkan32"].runtime, Runtime::Passed);
        assert_eq!(
            report.checks["graphics_acceleration"].state,
            if kind == 2 {
                State::RuntimeVerified
            } else {
                State::Unsupported
            }
        );
        assert_eq!(
            serde_json::to_value(report.graphics.as_ref().unwrap()).unwrap(),
            serde_json::to_value(&graphics).unwrap()
        );
        let _: gaming::Report =
            serde_json::from_value(serde_json::to_value(&report).unwrap()).unwrap();
        assert_eq!(report.checks["steam_runtime"].runtime, Runtime::Untested);
        assert!(
            !gaming::plan("core", true, &Default::default(), &graphics)
                .unwrap()
                .executable
        );
    }
}

#[test]
fn installation_and_enumeration_do_not_prove_readback_or_cross_architecture_acceleration() {
    let mut graphics = fixture(2);
    graphics.compat32.enumeration = Evidence::Untested;
    graphics.compat32.devices.clear();
    assert_eq!(graphics.readiness().vulkan32.runtime, Runtime::Untested);
    assert_eq!(graphics.readiness().acceleration.state, State::Unknown);
    graphics.native.devices[0].rendering = Evidence::Failed;
    assert_eq!(graphics.readiness().vulkan64.runtime, Runtime::Failed);
    graphics.native.devices[0].rendering = Evidence::Untested;
    assert_eq!(graphics.readiness().vulkan64.state, State::Unknown);
    graphics.native.enumeration = Evidence::Failed;
    assert_eq!(graphics.readiness().vulkan64.runtime, Runtime::Failed);
    graphics.native.enumeration = Evidence::Untested;
    graphics.native.loader = Evidence::Absent;
    assert_eq!(graphics.readiness().vulkan64.state, State::NotInstalled);
}

#[test]
fn different_devices_or_software_cannot_be_combined_into_physical_acceleration() {
    let mut graphics = fixture(2);
    graphics.gpus.as_mut().unwrap()[0].compat32_devices.clear();
    assert_eq!(graphics.readiness().acceleration.state, State::Unknown);
    let mut graphics = fixture(2);
    graphics.compat32.devices[0].driver_id = Some(13);
    assert_eq!(graphics.readiness().acceleration.state, State::Unknown);
    let mut graphics = fixture(2);
    graphics.gpus.as_mut().unwrap()[0].hardware.driver = None;
    assert_eq!(graphics.readiness().acceleration.state, State::Unknown);
}

#[test]
fn software_multilib_mismatch_is_rejected_by_the_shared_update_guard() {
    let packages = [
        ("vulkan-swrast".into(), "1:26.2.3-2".into()),
        ("lib32-vulkan-swrast".into(), "1:26.2.4-1".into()),
    ]
    .into();
    assert!(distro_graphics::validate_update(&Default::default(), &packages).is_err());
}
