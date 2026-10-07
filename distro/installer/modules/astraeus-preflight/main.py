import os
import libcalamares


def pretty_name():
    return "Check installation requirements"


def run():
    if not os.path.isdir("/sys/firmware/efi"):
        return "UEFI required", "Restart the installation media in UEFI mode."
    if not os.path.isfile("/opt/distro/install-root.sfs"):
        return "Installation image missing", "Use a complete Astraeus ISO."
