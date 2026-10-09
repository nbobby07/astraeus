/* Test-only EFI application. It never writes firmware variables or disks. */
#include <efi.h>
#include <efilib.h>

#ifndef RUN_ID
#error RUN_ID must identify this fixture set
#endif

__attribute__((section(".p3data"), used))
const unsigned char tamper_target[] = "ASTRAEUS_SIGNATURE_TAMPER_TARGET";

static void serial(const char *s) {
    while (*s) {
        unsigned char ready;
        do {
            __asm__ volatile("inb %1, %0" : "=a"(ready) : "Nd"((unsigned short)0x3fd));
        } while (!(ready & 0x20));
        __asm__ volatile("outb %0, %1" :: "a"((unsigned char)*s++), "Nd"((unsigned short)0x3f8));
    }
}

#ifndef PAYLOAD
static void hex(UINT64 value, unsigned int digits) {
    const char *alphabet = "0123456789abcdef";
    char text[17];
    for (unsigned int i = 0; i < digits; i++)
        text[i] = alphabet[(value >> (4 * (digits - i - 1))) & 15];
    text[digits] = 0;
    serial(text);
}
#endif

static void prefix(const char *name) {
    serial("P3 " RUN_ID " ");
    serial(name);
    serial(" ");
}

#ifndef PAYLOAD
static void variable(CHAR16 *name, const char *label, EFI_GUID *guid) {
    unsigned char bytes[16384];
    UINTN size = sizeof(bytes);
    UINT32 attributes = 0;
    EFI_STATUS status = uefi_call_wrapper(RT->GetVariable, 5, name, guid,
                                         &attributes, &size, bytes);
    prefix(label);
    hex(status, 16);
    serial(" ");
    hex(attributes, 8);
    serial(" ");
    if (!EFI_ERROR(status))
        for (UINTN i = 0; i < size; i++) hex(bytes[i], 2);
    serial("\r\n");
}

static void launch(EFI_HANDLE parent, EFI_HANDLE device, CHAR16 *file, const char *label) {
    EFI_DEVICE_PATH *path = FileDevicePath(device, file);
    EFI_HANDLE child = NULL;
    EFI_STATUS status = path ? uefi_call_wrapper(BS->LoadImage, 6, FALSE, parent,
                                                path, NULL, 0, &child) : EFI_OUT_OF_RESOURCES;
    prefix(label);
    serial("LOAD ");
    hex(status, 16);
    serial("\r\n");
#ifndef LOAD_ONLY
    if (!EFI_ERROR(status)) {
        status = uefi_call_wrapper(BS->StartImage, 3, child, NULL, NULL);
        prefix(label);
        serial("START ");
        hex(status, 16);
        serial("\r\n");
    }
#endif
    if (child) uefi_call_wrapper(BS->UnloadImage, 1, child);
    if (path) FreePool(path);
}

static void refusals(EFI_GUID *guid) {
    /* UEFI image execution table: UINTN count, then Action/InfoSize/name/path records. */
    unsigned char *table = NULL;
    for (UINTN i = 0; i < ST->NumberOfTableEntries; i++)
        if (!CompareMem(&ST->ConfigurationTable[i].VendorGuid, guid, sizeof(*guid)))
            table = ST->ConfigurationTable[i].VendorTable;
    if (!table) return;
    UINTN count = *(UINTN *)table;
    if (count > 64) return;
    unsigned char *record = table + sizeof(UINTN);
    for (UINTN i = 0; i < count; i++) {
        UINT32 action = *(UINT32 *)record;
        UINT32 size = *(UINT32 *)(record + 4);
        if (size < 10 || size > 65536) return;
        prefix("DENIED_IMAGE");
        hex(action, 8);
        serial(" ");
        CHAR16 *name = (CHAR16 *)(record + 8);
        for (UINTN j = 0; 8 + (j + 1) * 2 <= size && name[j]; j++) {
            char character[2] = {name[j] < 128 ? (char)name[j] : '?', 0};
            serial(character);
        }
        serial("\r\n");
        record += size;
    }
}
#endif

EFI_STATUS efi_main(EFI_HANDLE image, EFI_SYSTEM_TABLE *system) {
    InitializeLib(image, system);
#ifdef PAYLOAD
    prefix("PAYLOAD_EXECUTED");
    serial("\r\n");
    return EFI_SUCCESS;
#else
    EFI_GUID global = EFI_GLOBAL_VARIABLE;
    EFI_GUID database = {0xd719b2cb, 0x3d3a, 0x4596, {0xa3, 0xbc, 0xda, 0xd0, 0x0e, 0x67, 0x65, 0x6f}};
    EFI_LOADED_IMAGE *loaded = NULL;
    EFI_STATUS status = uefi_call_wrapper(BS->HandleProtocol, 3, image, &LoadedImageProtocol, &loaded);
    if (EFI_ERROR(status)) return status;
    serial("\r\n");
    variable(L"SecureBoot", "SecureBoot", &global);
    variable(L"SetupMode", "SetupMode", &global);
    variable(L"PK", "PK", &global);
    variable(L"KEK", "KEK", &global);
    variable(L"db", "db", &database);
    launch(image, loaded->DeviceHandle, L"\\EFI\\tests\\trusted.efi", "trusted");
    launch(image, loaded->DeviceHandle, L"\\EFI\\tests\\unsigned.efi", "unsigned");
    launch(image, loaded->DeviceHandle, L"\\EFI\\tests\\untrusted.efi", "untrusted");
    launch(image, loaded->DeviceHandle, L"\\EFI\\tests\\tampered.efi", "tampered");
    refusals(&database);
    prefix("COMPLETE");
    serial("\r\n");
    /* The host captures QMP state before terminating its own child. */
    for (;;) uefi_call_wrapper(BS->Stall, 1, 100000);
#endif
}
