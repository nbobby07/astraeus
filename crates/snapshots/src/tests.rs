use super::*;

#[test]
fn boot_identity_allows_only_systemd_detected_console_suffixes() {
    let expected = "rd.luks.name=uuid=root root=/dev/mapper/root rootflags=subvol=@ rw astraeus.transaction=7-boot";
    assert!(boot_command_line_matches(expected, expected));
    for suffix in [
        "console=hvc0",
        "console=hvc0 console=tty0",
        "console=uart,io,0x3f8",
        "console=uart,io,0x2f8 console=tty0",
        "console=uart,io,0x3e8 console=hvc0",
        "console=uart,io,0x2e8 console=hvc0 console=tty0",
    ] {
        assert!(boot_command_line_matches(
            expected,
            &format!("{expected} {suffix}")
        ));
    }
    for suffix in [
        "rootflags=subvol=@other",
        "root=/dev/vda3",
        "rd.luks.name=other=root",
        "init=/bin/sh",
        "systemd.unit=emergency.target",
        "astraeus.transaction=8-boot",
        "console=tty0",
        "console=ttyS9",
        "console=hvc0 console=uart,io,0x3f8",
        "console=uart,io,0x3f8 console=tty0 quiet",
    ] {
        assert!(
            !boot_command_line_matches(expected, &format!("{expected} {suffix}")),
            "{suffix}"
        );
    }
    assert!(!boot_command_line_matches(
        expected,
        &expected.replace("7-boot", "8-boot")
    ));
    assert!(!boot_command_line_matches(
        expected,
        expected.split(" astraeus").next().unwrap()
    ));
    let explicit = format!("{expected} console=tty0");
    assert!(boot_command_line_matches(&explicit, &explicit));
    assert!(!boot_command_line_matches(
        &explicit,
        &format!("{explicit} console=hvc0")
    ));
    assert!(!boot_command_line_matches("", "console=hvc0"));
}

pub(crate) fn image(kernel: &[u8], cmdline: &[u8]) -> Vec<u8> {
    let mut bytes = vec![0u8; 512];
    bytes[..2].copy_from_slice(b"MZ");
    bytes[0x3c..0x40].copy_from_slice(&128u32.to_le_bytes());
    bytes[128..132].copy_from_slice(b"PE\0\0");
    bytes[132..134].copy_from_slice(&0x8664u16.to_le_bytes());
    bytes[134..136].copy_from_slice(&5u16.to_le_bytes());
    for (n, (name, data)) in [
        (b".linux".as_slice(), kernel),
        (b".cmdline", cmdline),
        (b".initrd", b"test initrd"),
        (b".osrel", b"ID=astraeus\nPRETTY_NAME=Astraeus\n"),
        (b".uname", b"test-release"),
    ]
    .into_iter()
    .enumerate()
    {
        let h = 152 + n * 40;
        bytes[h..h + name.len()].copy_from_slice(name);
        for offset in [8, 16] {
            bytes[h + offset..h + offset + 4].copy_from_slice(&(data.len() as u32).to_le_bytes());
        }
        let start = bytes.len() as u32;
        bytes[h + 20..h + 24].copy_from_slice(&start.to_le_bytes());
        bytes.extend_from_slice(data);
    }
    bytes
}

#[test]
fn identifiers_and_pe_are_checked_at_the_boundary() {
    for bad in ["", "../1", "/1", "1\\2", "-option", "1\n2"] {
        assert!(SnapshotId::parse(bad).is_err());
    }
    let bytes = image(b"kernel", b"rootflags=subvol=@");
    assert_eq!(pe_section(&bytes, b".linux").unwrap(), b"kernel");
    for len in 0..bytes.len() {
        assert!(pe_section(&bytes[..len], b".uname").is_err());
    }
    let mut wrong = bytes.clone();
    wrong[152 + 20..152 + 24].copy_from_slice(&u32::MAX.to_le_bytes());
    assert!(pe_section(&wrong, b".linux").is_err());
    let mut duplicate = bytes;
    duplicate[192..200].copy_from_slice(b".linux\0\0");
    assert!(pe_section(&duplicate, b".linux").is_err());
}

#[test]
fn btrfs_identity_parser_fails_closed() {
    let text = "@\n UUID: 11111111-1111-1111-1111-111111111111\n Parent UUID: -\n Subvolume ID: 256\n Top level ID: 5\n Flags: -\n";
    let sub = parse_subvolume(text).unwrap();
    assert_eq!(sub.id, 256);
    assert!(!sub.read_only);
    for bad in [
        text.replace("Flags: -", "Flags: unexpected"),
        text.replace("Top level ID: 5", ""),
        format!("{text} UUID: x"),
        text.replace("256", "NaN"),
    ] {
        assert!(parse_subvolume(&bad).is_err());
    }
}
