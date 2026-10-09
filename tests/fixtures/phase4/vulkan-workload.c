/* SPDX-License-Identifier: CC0-1.0. Offscreen clear/readback, not a performance test. */
#include <vulkan/vulkan.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>

#define CHECK(call) do { VkResult r = (call); if (r != VK_SUCCESS) { \
    fprintf(stderr, "%s: VkResult=%d\n", #call, r); goto cleanup; } } while (0)

int main(void) {
    int code = 1;
    VkInstance instance = VK_NULL_HANDLE;
    VkDevice device = VK_NULL_HANDLE;
    VkImage image = VK_NULL_HANDLE;
    VkDeviceMemory memory = VK_NULL_HANDLE;
    VkCommandPool pool = VK_NULL_HANDLE;
    VkFence fence = VK_NULL_HANDLE;
    VkPhysicalDevice *devices = NULL;
    VkQueueFamilyProperties *queues = NULL;
    VkInstanceCreateInfo ici = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
    CHECK(vkCreateInstance(&ici, NULL, &instance));
    uint32_t count = 0;
    CHECK(vkEnumeratePhysicalDevices(instance, &count, NULL));
    if (!count) { fprintf(stderr, "No usable Vulkan device; inspect ICD and driver\n"); goto cleanup; }
    devices = calloc(count, sizeof(*devices));
    if (!devices) goto cleanup;
    CHECK(vkEnumeratePhysicalDevices(instance, &count, devices));
    VkPhysicalDevice gpu = devices[0];
    VkPhysicalDeviceProperties properties;
    vkGetPhysicalDeviceProperties(gpu, &properties);
    printf("renderer=%s\nvendor=0x%04x\ndevice_type=%u\narchitecture_bits=%zu\n",
           properties.deviceName, properties.vendorID, properties.deviceType, sizeof(void *) * 8);
    uint32_t families = 0, family = UINT32_MAX;
    vkGetPhysicalDeviceQueueFamilyProperties(gpu, &families, NULL);
    queues = calloc(families, sizeof(*queues));
    if (!queues) goto cleanup;
    vkGetPhysicalDeviceQueueFamilyProperties(gpu, &families, queues);
    for (uint32_t i = 0; i < families; ++i)
        if (queues[i].queueCount && (queues[i].queueFlags & VK_QUEUE_GRAPHICS_BIT)) { family = i; break; }
    if (family == UINT32_MAX) { fprintf(stderr, "No graphics queue\n"); goto cleanup; }
    float priority = 1.0f;
    VkDeviceQueueCreateInfo qci = {.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
        .queueFamilyIndex = family, .queueCount = 1, .pQueuePriorities = &priority};
    VkDeviceCreateInfo dci = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
        .queueCreateInfoCount = 1, .pQueueCreateInfos = &qci};
    CHECK(vkCreateDevice(gpu, &dci, NULL, &device));
    VkQueue queue;
    vkGetDeviceQueue(device, family, 0, &queue);
    VkImageCreateInfo imci = {.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO,
        .imageType = VK_IMAGE_TYPE_2D, .format = VK_FORMAT_R8G8B8A8_UNORM,
        .extent = {16, 16, 1}, .mipLevels = 1, .arrayLayers = 1,
        .samples = VK_SAMPLE_COUNT_1_BIT, .tiling = VK_IMAGE_TILING_LINEAR,
        .usage = VK_IMAGE_USAGE_TRANSFER_DST_BIT, .sharingMode = VK_SHARING_MODE_EXCLUSIVE};
    CHECK(vkCreateImage(device, &imci, NULL, &image));
    VkMemoryRequirements requirements;
    VkPhysicalDeviceMemoryProperties memprops;
    vkGetImageMemoryRequirements(device, image, &requirements);
    vkGetPhysicalDeviceMemoryProperties(gpu, &memprops);
    uint32_t type = UINT32_MAX;
    VkMemoryPropertyFlags flags = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
    for (uint32_t i = 0; i < memprops.memoryTypeCount; ++i)
        if ((requirements.memoryTypeBits & (1u << i)) && (memprops.memoryTypes[i].propertyFlags & flags) == flags) { type = i; break; }
    if (type == UINT32_MAX) { fprintf(stderr, "UNSUPPORTED: linear coherent image memory\n"); code = 77; goto cleanup; }
    VkMemoryAllocateInfo mai = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
        .allocationSize = requirements.size, .memoryTypeIndex = type};
    CHECK(vkAllocateMemory(device, &mai, NULL, &memory));
    CHECK(vkBindImageMemory(device, image, memory, 0));
    VkCommandPoolCreateInfo pci = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, .queueFamilyIndex = family};
    CHECK(vkCreateCommandPool(device, &pci, NULL, &pool));
    VkCommandBufferAllocateInfo cai = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
        .commandPool = pool, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount = 1};
    VkCommandBuffer cmd;
    CHECK(vkAllocateCommandBuffers(device, &cai, &cmd));
    VkCommandBufferBeginInfo bi = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};
    CHECK(vkBeginCommandBuffer(cmd, &bi));
    VkImageMemoryBarrier barrier = {.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
        .dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT, .oldLayout = VK_IMAGE_LAYOUT_UNDEFINED,
        .newLayout = VK_IMAGE_LAYOUT_GENERAL, .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
        .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .image = image,
        .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
    vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT,
                         0, 0, NULL, 0, NULL, 1, &barrier);
    VkClearColorValue red = {.float32 = {1, 0, 0, 1}};
    vkCmdClearColorImage(cmd, image, VK_IMAGE_LAYOUT_GENERAL, &red, 1, &barrier.subresourceRange);
    barrier.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    barrier.dstAccessMask = VK_ACCESS_HOST_READ_BIT;
    barrier.oldLayout = VK_IMAGE_LAYOUT_GENERAL;
    vkCmdPipelineBarrier(cmd, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT,
                         0, 0, NULL, 0, NULL, 1, &barrier);
    CHECK(vkEndCommandBuffer(cmd));
    VkFenceCreateInfo fci = {.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
    CHECK(vkCreateFence(device, &fci, NULL, &fence));
    VkSubmitInfo si = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &cmd};
    CHECK(vkQueueSubmit(queue, 1, &si, fence));
    CHECK(vkWaitForFences(device, 1, &fence, VK_TRUE, UINT64_C(10000000000)));
    void *mapped = NULL;
    CHECK(vkMapMemory(device, memory, 0, VK_WHOLE_SIZE, 0, &mapped));
    VkImageSubresource sub = {.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT};
    VkSubresourceLayout layout;
    vkGetImageSubresourceLayout(device, image, &sub, &layout);
    code = 0;
    for (size_t y = 0; y < 16; ++y) for (size_t x = 0; x < 16; ++x) {
        uint8_t *p = (uint8_t *)mapped + layout.offset + y * layout.rowPitch + x * 4;
        if (p[0] != 255 || p[1] != 0 || p[2] != 0 || p[3] != 255) code = 1;
    }
    vkUnmapMemory(device, memory);
    if (!code) puts("PHASE4_VULKAN_OK pixels=256");
    else fprintf(stderr, "Readback mismatch\n");
cleanup:
    if (device) {
        vkDeviceWaitIdle(device);
        if (fence) vkDestroyFence(device, fence, NULL);
        if (pool) vkDestroyCommandPool(device, pool, NULL);
        if (image) vkDestroyImage(device, image, NULL);
        if (memory) vkFreeMemory(device, memory, NULL);
        vkDestroyDevice(device, NULL);
    }
    if (instance) vkDestroyInstance(instance, NULL);
    free(queues);
    free(devices);
    return code;
}
