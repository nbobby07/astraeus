"""Finalize an upstream Calamares installation. No partitioning or passwords here."""
import sys
import libcalamares

sys.path.insert(0, "/usr/share/distro/installer")
from provision import provision


def pretty_name():
    return "Configure boot and services"


def run():
    try:
        provision(libcalamares.globalstorage.value("rootMountPoint"),
                  libcalamares.globalstorage.value("partitions"),
                  (libcalamares.globalstorage.value("keyboardLayout"), libcalamares.globalstorage.value("keyboardVariant")),
                  libcalamares.globalstorage.value("username"))
    except Exception as error:
        return "Installed system configuration failed", str(error)
