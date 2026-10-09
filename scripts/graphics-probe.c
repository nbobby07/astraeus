/* Same source builds as ELF64 and ELF32. Vulkan calls stay out of the Rust CLI. */
#define VK_NO_PROTOTYPES
#include <vulkan/vulkan.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define LIMIT 64
#define FUNCTIONS(X) \
 X(vkCreateInstance) X(vkDestroyInstance) X(vkEnumeratePhysicalDevices) \
 X(vkGetPhysicalDeviceProperties) X(vkGetPhysicalDeviceProperties2) \
 X(vkEnumerateDeviceExtensionProperties) X(vkGetPhysicalDeviceQueueFamilyProperties) \
 X(vkGetPhysicalDeviceMemoryProperties) X(vkGetPhysicalDeviceFormatProperties) \
 X(vkCreateDevice) X(vkDestroyDevice) X(vkGetDeviceQueue) \
 X(vkCreateImage) X(vkDestroyImage) X(vkGetImageMemoryRequirements) X(vkBindImageMemory) \
 X(vkCreateBuffer) X(vkDestroyBuffer) X(vkGetBufferMemoryRequirements) X(vkBindBufferMemory) \
 X(vkAllocateMemory) X(vkFreeMemory) X(vkMapMemory) X(vkUnmapMemory) \
 X(vkCreateImageView) X(vkDestroyImageView) X(vkCreateRenderPass) X(vkDestroyRenderPass) \
 X(vkCreateFramebuffer) X(vkDestroyFramebuffer) X(vkCreateCommandPool) X(vkDestroyCommandPool) \
 X(vkAllocateCommandBuffers) X(vkBeginCommandBuffer) X(vkEndCommandBuffer) \
 X(vkCmdBeginRenderPass) X(vkCmdEndRenderPass) X(vkCmdCopyImageToBuffer) X(vkCmdPipelineBarrier) \
 X(vkCreateFence) X(vkDestroyFence) X(vkQueueSubmit) X(vkWaitForFences)
#define DECLARE(name) static PFN_##name name;
FUNCTIONS(DECLARE)

static void string(const char *value) {
    putchar('"');
    for (const unsigned char *p = (const unsigned char *)value; *p; ++p) {
        if (*p == '"' || *p == '\\') printf("\\%c", *p);
        else if (*p < 32 || *p >= 127) printf("\\u%04x", *p);
        else putchar(*p);
    }
    putchar('"');
}

static int memory_type(VkPhysicalDevice gpu, uint32_t mask, VkMemoryPropertyFlags flags) {
    VkPhysicalDeviceMemoryProperties properties;
    vkGetPhysicalDeviceMemoryProperties(gpu, &properties);
    for (uint32_t i = 0; i < properties.memoryTypeCount; ++i)
        if ((mask & (1u << i)) && (properties.memoryTypes[i].propertyFlags & flags) == flags) return (int)i;
    return -1;
}

/* Clear a color attachment through a graphics render pass, copy it back, verify pixels. */
static const char *render(VkPhysicalDevice gpu) {
    const char *result = "failed";
    VkDevice device = VK_NULL_HANDLE;
    VkImage image = VK_NULL_HANDLE;
    VkBuffer buffer = VK_NULL_HANDLE;
    VkDeviceMemory image_memory = VK_NULL_HANDLE, buffer_memory = VK_NULL_HANDLE;
    VkImageView view = VK_NULL_HANDLE;
    VkRenderPass pass = VK_NULL_HANDLE;
    VkFramebuffer framebuffer = VK_NULL_HANDLE;
    VkCommandPool pool = VK_NULL_HANDLE;
    VkFence fence = VK_NULL_HANDLE;
    VkFormatProperties format;
    vkGetPhysicalDeviceFormatProperties(gpu, VK_FORMAT_R8G8B8A8_UNORM, &format);
    if (!(format.optimalTilingFeatures & VK_FORMAT_FEATURE_COLOR_ATTACHMENT_BIT)) return "unsupported";
    uint32_t count = 0;
    vkGetPhysicalDeviceQueueFamilyProperties(gpu, &count, NULL);
    if (!count || count > LIMIT) return "unsupported";
    VkQueueFamilyProperties families[LIMIT];
    vkGetPhysicalDeviceQueueFamilyProperties(gpu, &count, families);
    uint32_t family = 0;
    while (family < count && !(families[family].queueFlags & VK_QUEUE_GRAPHICS_BIT)) ++family;
    if (family == count) return "unsupported";
    float priority = 1;
    VkDeviceQueueCreateInfo queue_info = { .sType=VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, .queueFamilyIndex=family, .queueCount=1, .pQueuePriorities=&priority };
    VkDeviceCreateInfo device_info = { .sType=VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .queueCreateInfoCount=1, .pQueueCreateInfos=&queue_info };
#define CHECK(call) do { if ((call) != VK_SUCCESS) goto done; } while (0)
    CHECK(vkCreateDevice(gpu, &device_info, NULL, &device));
    VkQueue queue;
    vkGetDeviceQueue(device, family, 0, &queue);
    VkImageCreateInfo image_info = { .sType=VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .imageType=VK_IMAGE_TYPE_2D, .format=VK_FORMAT_R8G8B8A8_UNORM, .extent={4,4,1}, .mipLevels=1, .arrayLayers=1, .samples=VK_SAMPLE_COUNT_1_BIT, .tiling=VK_IMAGE_TILING_OPTIMAL, .usage=VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT|VK_IMAGE_USAGE_TRANSFER_SRC_BIT, .sharingMode=VK_SHARING_MODE_EXCLUSIVE };
    CHECK(vkCreateImage(device, &image_info, NULL, &image));
    VkMemoryRequirements req;
    vkGetImageMemoryRequirements(device, image, &req);
    int type = memory_type(gpu, req.memoryTypeBits, 0);
    if (type < 0) goto done;
    VkMemoryAllocateInfo allocation = { .sType=VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize=req.size, .memoryTypeIndex=(uint32_t)type };
    CHECK(vkAllocateMemory(device, &allocation, NULL, &image_memory));
    CHECK(vkBindImageMemory(device, image, image_memory, 0));
    VkBufferCreateInfo buffer_info = { .sType=VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size=64, .usage=VK_BUFFER_USAGE_TRANSFER_DST_BIT, .sharingMode=VK_SHARING_MODE_EXCLUSIVE };
    CHECK(vkCreateBuffer(device, &buffer_info, NULL, &buffer));
    vkGetBufferMemoryRequirements(device, buffer, &req);
    type = memory_type(gpu, req.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    if (type < 0) { result="unsupported"; goto done; }
    allocation.allocationSize=req.size; allocation.memoryTypeIndex=(uint32_t)type;
    CHECK(vkAllocateMemory(device, &allocation, NULL, &buffer_memory));
    CHECK(vkBindBufferMemory(device, buffer, buffer_memory, 0));
    VkImageViewCreateInfo view_info = { .sType=VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, .image=image, .viewType=VK_IMAGE_VIEW_TYPE_2D, .format=VK_FORMAT_R8G8B8A8_UNORM, .subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1} };
    CHECK(vkCreateImageView(device, &view_info, NULL, &view));
    VkAttachmentDescription attachment = { .format=VK_FORMAT_R8G8B8A8_UNORM, .samples=VK_SAMPLE_COUNT_1_BIT, .loadOp=VK_ATTACHMENT_LOAD_OP_CLEAR, .storeOp=VK_ATTACHMENT_STORE_OP_STORE, .stencilLoadOp=VK_ATTACHMENT_LOAD_OP_DONT_CARE, .stencilStoreOp=VK_ATTACHMENT_STORE_OP_DONT_CARE, .initialLayout=VK_IMAGE_LAYOUT_UNDEFINED, .finalLayout=VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL };
    VkAttachmentReference reference = {0, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL};
    VkSubpassDescription subpass = { .pipelineBindPoint=VK_PIPELINE_BIND_POINT_GRAPHICS, .colorAttachmentCount=1, .pColorAttachments=&reference };
    VkSubpassDependency dependency = { .srcSubpass=0, .dstSubpass=VK_SUBPASS_EXTERNAL, .srcStageMask=VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT, .dstStageMask=VK_PIPELINE_STAGE_TRANSFER_BIT, .srcAccessMask=VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT, .dstAccessMask=VK_ACCESS_TRANSFER_READ_BIT };
    VkRenderPassCreateInfo pass_info = { .sType=VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO, .attachmentCount=1, .pAttachments=&attachment, .subpassCount=1, .pSubpasses=&subpass, .dependencyCount=1, .pDependencies=&dependency };
    CHECK(vkCreateRenderPass(device, &pass_info, NULL, &pass));
    VkFramebufferCreateInfo framebuffer_info = { .sType=VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO, .renderPass=pass, .attachmentCount=1, .pAttachments=&view, .width=4, .height=4, .layers=1 };
    CHECK(vkCreateFramebuffer(device, &framebuffer_info, NULL, &framebuffer));
    VkCommandPoolCreateInfo pool_info = { .sType=VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, .queueFamilyIndex=family };
    CHECK(vkCreateCommandPool(device, &pool_info, NULL, &pool));
    VkCommandBuffer command;
    VkCommandBufferAllocateInfo command_info = { .sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, .commandPool=pool, .level=VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount=1 };
    CHECK(vkAllocateCommandBuffers(device, &command_info, &command));
    VkCommandBufferBeginInfo begin = { .sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, .flags=VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT };
    CHECK(vkBeginCommandBuffer(command, &begin));
    VkClearValue clear = { .color={.float32={0.25f,0.5f,0.75f,1.0f}} };
    VkRenderPassBeginInfo pass_begin = { .sType=VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO, .renderPass=pass, .framebuffer=framebuffer, .renderArea={{0,0},{4,4}}, .clearValueCount=1, .pClearValues=&clear };
    vkCmdBeginRenderPass(command, &pass_begin, VK_SUBPASS_CONTENTS_INLINE);
    vkCmdEndRenderPass(command);
    VkBufferImageCopy copy = { .imageSubresource={VK_IMAGE_ASPECT_COLOR_BIT,0,0,1}, .imageExtent={4,4,1} };
    vkCmdCopyImageToBuffer(command, image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, buffer, 1, &copy);
    VkMemoryBarrier barrier = { .sType=VK_STRUCTURE_TYPE_MEMORY_BARRIER, .srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT, .dstAccessMask=VK_ACCESS_HOST_READ_BIT };
    vkCmdPipelineBarrier(command, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &barrier, 0, NULL, 0, NULL);
    CHECK(vkEndCommandBuffer(command));
    VkFenceCreateInfo fence_info = { .sType=VK_STRUCTURE_TYPE_FENCE_CREATE_INFO };
    CHECK(vkCreateFence(device, &fence_info, NULL, &fence));
    VkSubmitInfo submit = { .sType=VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount=1, .pCommandBuffers=&command };
    CHECK(vkQueueSubmit(queue, 1, &submit, fence));
    /* Never destroy resources while a timed-out submission may still own them. */
    if (vkWaitForFences(device, 1, &fence, VK_TRUE, UINT64_C(3000000000)) != VK_SUCCESS) _Exit(3);
    unsigned char *pixels;
    CHECK(vkMapMemory(device, buffer_memory, 0, 64, 0, (void **)&pixels));
    result="passed";
    const int expected[4]={64,128,191,255};
    for (int i=0; i<64; ++i) if (abs((int)pixels[i]-expected[i%4]) > 1) result="failed";
    vkUnmapMemory(device, buffer_memory);
done:
    if (fence) vkDestroyFence(device, fence, NULL);
    if (pool) vkDestroyCommandPool(device, pool, NULL);
    if (framebuffer) vkDestroyFramebuffer(device, framebuffer, NULL);
    if (pass) vkDestroyRenderPass(device, pass, NULL);
    if (view) vkDestroyImageView(device, view, NULL);
    if (image) vkDestroyImage(device, image, NULL);
    if (buffer) vkDestroyBuffer(device, buffer, NULL);
    if (image_memory) vkFreeMemory(device, image_memory, NULL);
    if (buffer_memory) vkFreeMemory(device, buffer_memory, NULL);
    if (device) vkDestroyDevice(device, NULL);
    return result;
}

static int status(const char *state) {
    printf("{\"schema_version\":1,\"architecture\":%zu,\"loader_version\":null,\"status\":\"%s\",\"devices\":[]}\n", sizeof(void*)*8, state);
    return 0;
}

int main(void) {
    if (getuid() == 0 || geteuid() != getuid()) return status("unsupported");
    void *library = dlopen("libvulkan.so.1", RTLD_NOW|RTLD_LOCAL);
    if (!library) return status("absent");
#define LOAD(name) do { *(void **)(&name)=dlsym(library, #name); if (!name) return status("unsupported"); } while (0);
    FUNCTIONS(LOAD)
    PFN_vkEnumerateInstanceVersion version_function = (PFN_vkEnumerateInstanceVersion)dlsym(library, "vkEnumerateInstanceVersion");
    uint32_t version = VK_API_VERSION_1_0;
    if (version_function && version_function(&version) != VK_SUCCESS) return status("failed");
    if (version < VK_API_VERSION_1_1) return status("unsupported");
    VkApplicationInfo app = { .sType=VK_STRUCTURE_TYPE_APPLICATION_INFO, .pApplicationName="Astraeus graphics diagnostic", .apiVersion=VK_API_VERSION_1_1 };
    VkInstanceCreateInfo create = { .sType=VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo=&app };
    VkInstance instance;
    if (vkCreateInstance(&create, NULL, &instance) != VK_SUCCESS) return status("failed");
    uint32_t count=0;
    if (vkEnumeratePhysicalDevices(instance, &count, NULL) != VK_SUCCESS || count>LIMIT) { vkDestroyInstance(instance,NULL); return status("failed"); }
    VkPhysicalDevice devices[LIMIT];
    if (count && vkEnumeratePhysicalDevices(instance, &count, devices) != VK_SUCCESS) { vkDestroyInstance(instance,NULL); return status("failed"); }
    printf("{\"schema_version\":1,\"architecture\":%zu,\"loader_version\":%u,\"status\":\"passed\",\"devices\":[", sizeof(void*)*8, version);
    for (uint32_t i=0; i<count; ++i) {
        if (i) putchar(',');
        VkPhysicalDeviceProperties properties;
        vkGetPhysicalDeviceProperties(devices[i], &properties);
        uint32_t extensions_count=0;
        int has_pci=0, has_driver=properties.apiVersion>=VK_API_VERSION_1_2;
        if (vkEnumerateDeviceExtensionProperties(devices[i],NULL,&extensions_count,NULL) == VK_SUCCESS && extensions_count<=4096) {
            VkExtensionProperties *extensions=calloc(extensions_count ? extensions_count : 1,sizeof(*extensions));
            if (extensions && vkEnumerateDeviceExtensionProperties(devices[i],NULL,&extensions_count,extensions) == VK_SUCCESS) {
                for (uint32_t j=0;j<extensions_count;++j) {
                    has_pci |= strcmp(extensions[j].extensionName,VK_EXT_PCI_BUS_INFO_EXTENSION_NAME)==0;
                    has_driver |= strcmp(extensions[j].extensionName,VK_KHR_DRIVER_PROPERTIES_EXTENSION_NAME)==0;
                }
            }
            free(extensions);
        }
        VkPhysicalDevicePCIBusInfoPropertiesEXT pci = { .sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PCI_BUS_INFO_PROPERTIES_EXT };
        VkPhysicalDeviceDriverProperties driver = { .sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRIVER_PROPERTIES };
        VkPhysicalDeviceProperties2 properties2 = { .sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2 };
        if (has_pci) { pci.pNext=properties2.pNext; properties2.pNext=&pci; }
        if (has_driver) { driver.pNext=properties2.pNext; properties2.pNext=&driver; }
        vkGetPhysicalDeviceProperties2(devices[i], &properties2);
        printf("{\"name\":"); string(properties.deviceName);
        printf(",\"vendor_id\":%u,\"device_id\":%u,\"device_type\":%u,\"api_version\":%u,\"driver_version\":%u,\"driver_name\":",properties.vendorID,properties.deviceID,properties.deviceType,properties.apiVersion,properties.driverVersion);
        if (has_driver) string(driver.driverName); else printf("null");
        printf(",\"driver_info\":"); if (has_driver) string(driver.driverInfo); else printf("null");
        printf(",\"driver_id\":"); if (has_driver) printf("%u",driver.driverID); else printf("null");
        printf(",\"pci_address\":");
        if (has_pci) printf("\"%04x:%02x:%02x.%x\"",pci.pciDomain,pci.pciBus,pci.pciDevice,pci.pciFunction); else printf("null");
        printf(",\"software\":%s,\"rendering\":", (properties.deviceType==VK_PHYSICAL_DEVICE_TYPE_CPU || (has_driver && driver.driverID==VK_DRIVER_ID_MESA_LLVMPIPE)) ? "true":"false");
        string(render(devices[i])); putchar('}');
    }
    puts("]}");
    vkDestroyInstance(instance,NULL);
    dlclose(library);
    return 0;
}
