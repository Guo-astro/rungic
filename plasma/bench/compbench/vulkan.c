// SPDX-License-Identifier: MIT
// Vulkan renderer: the leased AHardwareBuffer is imported as a linear dma-buf
// VkImage (VK_EXT_image_drm_format_modifier), rendered with dynamic rendering
// and handed back to the foreign (Android) queue family.
//   --sync finish  vkQueueWaitIdle, the analogue of KWin's glFinish
//   --sync fence   wait only for this frame's submission fence
//   --sync none    no CPU wait before commit (upper bound; may show partial frames)
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <vulkan/vulkan.h>

#include "compbench.h"
#include "quad.frag.h"
#include "quad.vert.h"

#define CHECK(x) do { VkResult r_ = (x); if (r_ != VK_SUCCESS) { fprintf(stderr, "%s -> %d\n", #x, r_); die("Vulkan call failed"); } } while (0)

static VkInstance instance;
static VkPhysicalDevice phys;
static VkDevice dev;
static VkQueue queue;
static uint32_t family;
static VkCommandPool pool;
static VkPipelineLayout layout;
static VkPipeline opaque, blend;
static VkDescriptorSetLayout set_layout;
static VkDescriptorPool descriptor_pool;
static VkDescriptorSet sets[MAX_LAYERS + 1];
static VkSampler sampler;
static VkPhysicalDeviceMemoryProperties memory;
static char device[VK_MAX_PHYSICAL_DEVICE_NAME_SIZE];

struct vk_target {
    VkImage image;
    VkDeviceMemory memory;
    VkImageView view;
    VkCommandBuffer cmd;
    VkFence fence;
};

static uint32_t memory_type(uint32_t bits, VkMemoryPropertyFlags want) {
    for (uint32_t i = 0; i < memory.memoryTypeCount; i++)
        if ((bits & (1u << i)) && (memory.memoryTypes[i].propertyFlags & want) == want) return i;
    die("no suitable Vulkan memory type");
    return 0;
}

static VkCommandBuffer one_shot_begin(void) {
    VkCommandBuffer cmd;
    VkCommandBufferAllocateInfo info = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, NULL, pool,
                                        VK_COMMAND_BUFFER_LEVEL_PRIMARY, 1};
    CHECK(vkAllocateCommandBuffers(dev, &info, &cmd));
    VkCommandBufferBeginInfo begin = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, NULL,
                                      VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT, NULL};
    CHECK(vkBeginCommandBuffer(cmd, &begin));
    return cmd;
}

static void one_shot_end(VkCommandBuffer cmd) {
    CHECK(vkEndCommandBuffer(cmd));
    VkSubmitInfo submit = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &cmd};
    CHECK(vkQueueSubmit(queue, 1, &submit, VK_NULL_HANDLE));
    CHECK(vkQueueWaitIdle(queue));
    vkFreeCommandBuffers(dev, pool, 1, &cmd);
}

static void barrier(VkCommandBuffer cmd, VkImage image, VkImageLayout from, VkImageLayout to,
                    VkAccessFlags src_access, VkAccessFlags dst_access, VkPipelineStageFlags src_stage,
                    VkPipelineStageFlags dst_stage, uint32_t src_family, uint32_t dst_family) {
    VkImageMemoryBarrier b = {VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, NULL, src_access, dst_access, from, to,
                              src_family, dst_family, image, {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
    vkCmdPipelineBarrier(cmd, src_stage, dst_stage, 0, 0, NULL, 0, NULL, 1, &b);
}

static void import_target(struct output_buffer *b) {
    struct vk_target *t = calloc(1, sizeof *t);
    VkSubresourceLayout plane = {.offset = 0, .rowPitch = b->stride};
    VkImageDrmFormatModifierExplicitCreateInfoEXT modifier = {
        VK_STRUCTURE_TYPE_IMAGE_DRM_FORMAT_MODIFIER_EXPLICIT_CREATE_INFO_EXT, NULL, 0 /* LINEAR */, 1, &plane};
    VkExternalMemoryImageCreateInfo external = {VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_IMAGE_CREATE_INFO, &modifier,
                                                VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT};
    VkImageCreateInfo image = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .pNext = &external, .imageType = VK_IMAGE_TYPE_2D,
        .format = VK_FORMAT_B8G8R8A8_UNORM,  // DRM XRGB8888 is B,G,R,X in memory
        .extent = {opt.width, opt.height, 1}, .mipLevels = 1, .arrayLayers = 1, .samples = VK_SAMPLE_COUNT_1_BIT,
        .tiling = VK_IMAGE_TILING_DRM_FORMAT_MODIFIER_EXT, .usage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT,
        .sharingMode = VK_SHARING_MODE_EXCLUSIVE, .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED};
    CHECK(vkCreateImage(dev, &image, NULL, &t->image));

    PFN_vkGetMemoryFdPropertiesKHR fd_properties = (void *)vkGetDeviceProcAddr(dev, "vkGetMemoryFdPropertiesKHR");
    VkMemoryFdPropertiesKHR props = {VK_STRUCTURE_TYPE_MEMORY_FD_PROPERTIES_KHR};
    CHECK(fd_properties(dev, VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT, b->fd, &props));
    VkMemoryRequirements req;
    vkGetImageMemoryRequirements(dev, t->image, &req);
    VkMemoryDedicatedAllocateInfo dedicated = {VK_STRUCTURE_TYPE_MEMORY_DEDICATED_ALLOCATE_INFO, NULL, t->image, VK_NULL_HANDLE};
    VkImportMemoryFdInfoKHR import = {VK_STRUCTURE_TYPE_IMPORT_MEMORY_FD_INFO_KHR, &dedicated,
                                      VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT, dup(b->fd)};
    VkMemoryAllocateInfo alloc = {VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, &import, req.size,
                                  memory_type(req.memoryTypeBits & props.memoryTypeBits, 0)};
    CHECK(vkAllocateMemory(dev, &alloc, NULL, &t->memory));
    CHECK(vkBindImageMemory(dev, t->image, t->memory, 0));
    VkImageViewCreateInfo view = {VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, NULL, 0, t->image, VK_IMAGE_VIEW_TYPE_2D,
                                  VK_FORMAT_B8G8R8A8_UNORM, {0}, {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
    CHECK(vkCreateImageView(dev, &view, NULL, &t->view));
    VkCommandBufferAllocateInfo cmd = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, NULL, pool,
                                       VK_COMMAND_BUFFER_LEVEL_PRIMARY, 1};
    CHECK(vkAllocateCommandBuffers(dev, &cmd, &t->cmd));
    VkFenceCreateInfo fence = {VK_STRUCTURE_TYPE_FENCE_CREATE_INFO, NULL, VK_FENCE_CREATE_SIGNALED_BIT};
    CHECK(vkCreateFence(dev, &fence, NULL, &t->fence));
    b->priv = t;
}

static VkImageView upload_texture(int layer) {
    VkImage image;
    VkImageCreateInfo info = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .imageType = VK_IMAGE_TYPE_2D, .format = VK_FORMAT_R8G8B8A8_UNORM,
        .extent = {opt.width, opt.height, 1}, .mipLevels = 1, .arrayLayers = 1, .samples = VK_SAMPLE_COUNT_1_BIT,
        .tiling = VK_IMAGE_TILING_OPTIMAL, .usage = VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT,
        .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED};
    CHECK(vkCreateImage(dev, &info, NULL, &image));
    VkMemoryRequirements req;
    vkGetImageMemoryRequirements(dev, image, &req);
    VkDeviceMemory mem;
    VkMemoryAllocateInfo alloc = {VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, NULL, req.size,
                                  memory_type(req.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)};
    CHECK(vkAllocateMemory(dev, &alloc, NULL, &mem));
    CHECK(vkBindImageMemory(dev, image, mem, 0));

    VkDeviceSize size = (VkDeviceSize)opt.width * opt.height * 4;
    VkBuffer staging;
    VkBufferCreateInfo binfo = {VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, NULL, 0, size, VK_BUFFER_USAGE_TRANSFER_SRC_BIT};
    CHECK(vkCreateBuffer(dev, &binfo, NULL, &staging));
    vkGetBufferMemoryRequirements(dev, staging, &req);
    VkDeviceMemory smem;
    VkMemoryAllocateInfo salloc = {VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, NULL, req.size,
                                   memory_type(req.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT |
                                                                   VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)};
    CHECK(vkAllocateMemory(dev, &salloc, NULL, &smem));
    CHECK(vkBindBufferMemory(dev, staging, smem, 0));
    void *mapped;
    CHECK(vkMapMemory(dev, smem, 0, size, 0, &mapped));
    uint8_t *pixels = layer_pixels(layer, opt.width, opt.height);
    memcpy(mapped, pixels, size);
    free(pixels);
    vkUnmapMemory(dev, smem);

    VkCommandBuffer cmd = one_shot_begin();
    barrier(cmd, image, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 0,
            VK_ACCESS_TRANSFER_WRITE_BIT, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT,
            VK_QUEUE_FAMILY_IGNORED, VK_QUEUE_FAMILY_IGNORED);
    VkBufferImageCopy copy = {0, 0, 0, {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, {0, 0, 0}, {opt.width, opt.height, 1}};
    vkCmdCopyBufferToImage(cmd, staging, image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &copy);
    barrier(cmd, image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL,
            VK_ACCESS_TRANSFER_WRITE_BIT, VK_ACCESS_SHADER_READ_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT,
            VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT, VK_QUEUE_FAMILY_IGNORED, VK_QUEUE_FAMILY_IGNORED);
    one_shot_end(cmd);
    vkDestroyBuffer(dev, staging, NULL);
    vkFreeMemory(dev, smem, NULL);

    VkImageView view;
    VkImageViewCreateInfo vinfo = {VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, NULL, 0, image, VK_IMAGE_VIEW_TYPE_2D,
                                   VK_FORMAT_R8G8B8A8_UNORM, {0}, {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
    CHECK(vkCreateImageView(dev, &vinfo, NULL, &view));
    return view;
}

static VkShaderModule module(const uint32_t *code, size_t size) {
    VkShaderModule m;
    VkShaderModuleCreateInfo info = {VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, NULL, 0, size, code};
    CHECK(vkCreateShaderModule(dev, &info, NULL, &m));
    return m;
}

static VkPipeline pipeline(bool with_blend) {
    VkShaderModule vs = module(quad_vert, sizeof quad_vert), fs = module(quad_frag, sizeof quad_frag);
    VkPipelineShaderStageCreateInfo stages[2] = {
        {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, NULL, 0, VK_SHADER_STAGE_VERTEX_BIT, vs, "main", NULL},
        {VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, NULL, 0, VK_SHADER_STAGE_FRAGMENT_BIT, fs, "main", NULL}};
    VkPipelineVertexInputStateCreateInfo vertex = {VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO};
    VkPipelineInputAssemblyStateCreateInfo assembly = {VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO,
                                                        NULL, 0, VK_PRIMITIVE_TOPOLOGY_TRIANGLE_STRIP, VK_FALSE};
    VkPipelineViewportStateCreateInfo viewport = {VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO, NULL, 0, 1, NULL, 1, NULL};
    VkPipelineRasterizationStateCreateInfo raster = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO, .polygonMode = VK_POLYGON_MODE_FILL,
        .cullMode = VK_CULL_MODE_NONE, .frontFace = VK_FRONT_FACE_COUNTER_CLOCKWISE, .lineWidth = 1.0f};
    VkPipelineMultisampleStateCreateInfo multisample = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO, .rasterizationSamples = VK_SAMPLE_COUNT_1_BIT};
    VkPipelineColorBlendAttachmentState attachment = {
        .blendEnable = with_blend, .srcColorBlendFactor = VK_BLEND_FACTOR_SRC_ALPHA,
        .dstColorBlendFactor = VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA, .colorBlendOp = VK_BLEND_OP_ADD,
        .srcAlphaBlendFactor = VK_BLEND_FACTOR_ONE, .dstAlphaBlendFactor = VK_BLEND_FACTOR_ONE_MINUS_SRC_ALPHA,
        .alphaBlendOp = VK_BLEND_OP_ADD, .colorWriteMask = 0xf};
    VkPipelineColorBlendStateCreateInfo blending = {
        .sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO, .attachmentCount = 1, .pAttachments = &attachment};
    VkDynamicState states[] = {VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR};
    VkPipelineDynamicStateCreateInfo dynamic = {VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO, NULL, 0, 2, states};
    VkFormat format = VK_FORMAT_B8G8R8A8_UNORM;
    VkPipelineRenderingCreateInfo rendering = {VK_STRUCTURE_TYPE_PIPELINE_RENDERING_CREATE_INFO, NULL, 0, 1, &format};
    VkGraphicsPipelineCreateInfo info = {
        .sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO, .pNext = &rendering, .stageCount = 2,
        .pStages = stages, .pVertexInputState = &vertex, .pInputAssemblyState = &assembly,
        .pViewportState = &viewport, .pRasterizationState = &raster, .pMultisampleState = &multisample,
        .pColorBlendState = &blending, .pDynamicState = &dynamic, .layout = layout};
    VkPipeline p;
    CHECK(vkCreateGraphicsPipelines(dev, VK_NULL_HANDLE, 1, &info, NULL, &p));
    vkDestroyShaderModule(dev, vs, NULL);
    vkDestroyShaderModule(dev, fs, NULL);
    return p;
}

static void init(void) {
    VkApplicationInfo app = {VK_STRUCTURE_TYPE_APPLICATION_INFO, NULL, "compbench", 1, NULL, 0, VK_API_VERSION_1_3};
    VkInstanceCreateInfo iinfo = {VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, NULL, 0, &app};
    CHECK(vkCreateInstance(&iinfo, NULL, &instance));
    uint32_t count = 1;
    VkResult r = vkEnumeratePhysicalDevices(instance, &count, &phys);
    if ((r != VK_SUCCESS && r != VK_INCOMPLETE) || !count) die("no Vulkan device");
    VkPhysicalDeviceProperties props;
    vkGetPhysicalDeviceProperties(phys, &props);
    snprintf(device, sizeof device, "%s", props.deviceName);
    vkGetPhysicalDeviceMemoryProperties(phys, &memory);
    VkQueueFamilyProperties families[8];
    count = 8;
    vkGetPhysicalDeviceQueueFamilyProperties(phys, &count, families);
    for (family = 0; family < count && !(families[family].queueFlags & VK_QUEUE_GRAPHICS_BIT); family++) {}
    if (family == count) die("no graphics queue");

    const char *extensions[] = {VK_KHR_EXTERNAL_MEMORY_FD_EXTENSION_NAME, VK_EXT_EXTERNAL_MEMORY_DMA_BUF_EXTENSION_NAME,
                                VK_EXT_IMAGE_DRM_FORMAT_MODIFIER_EXTENSION_NAME, VK_EXT_QUEUE_FAMILY_FOREIGN_EXTENSION_NAME};
    float priority = 1.0f;
    VkDeviceQueueCreateInfo qinfo = {VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, NULL, 0, family, 1, &priority};
    VkPhysicalDeviceVulkan13Features v13 = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES,
                                            .dynamicRendering = VK_TRUE};
    VkDeviceCreateInfo dinfo = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .pNext = &v13, .queueCreateInfoCount = 1,
                                .pQueueCreateInfos = &qinfo, .enabledExtensionCount = 4, .ppEnabledExtensionNames = extensions};
    CHECK(vkCreateDevice(phys, &dinfo, NULL, &dev));
    vkGetDeviceQueue(dev, family, 0, &queue);
    VkCommandPoolCreateInfo pinfo = {VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, NULL,
                                     VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT, family};
    CHECK(vkCreateCommandPool(dev, &pinfo, NULL, &pool));

    for (int i = 0; i < opt.buffers; i++) import_target(&out_buf[i]);

    VkSamplerCreateInfo sinfo = {.sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO, .magFilter = VK_FILTER_LINEAR,
                                 .minFilter = VK_FILTER_LINEAR, .addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
                                 .addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
                                 .addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, .maxLod = 1.0f};
    CHECK(vkCreateSampler(dev, &sinfo, NULL, &sampler));
    VkDescriptorSetLayoutBinding binding = {0, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_FRAGMENT_BIT, NULL};
    VkDescriptorSetLayoutCreateInfo linfo = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, NULL, 0, 1, &binding};
    CHECK(vkCreateDescriptorSetLayout(dev, &linfo, NULL, &set_layout));
    VkDescriptorPoolSize size = {VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, MAX_LAYERS + 1};
    VkDescriptorPoolCreateInfo dpinfo = {VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, NULL, 0, MAX_LAYERS + 1, 1, &size};
    CHECK(vkCreateDescriptorPool(dev, &dpinfo, NULL, &descriptor_pool));
    for (int l = 0; l <= opt.layers; l++) {
        VkDescriptorSetAllocateInfo ainfo = {VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, NULL, descriptor_pool, 1, &set_layout};
        CHECK(vkAllocateDescriptorSets(dev, &ainfo, &sets[l]));
        VkDescriptorImageInfo image = {sampler, upload_texture(l), VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL};
        VkWriteDescriptorSet write = {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = sets[l],
                                      .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
                                      .pImageInfo = &image};
        vkUpdateDescriptorSets(dev, 1, &write, 0, NULL);
    }
    VkPushConstantRange push = {VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof(struct quad)};
    VkPipelineLayoutCreateInfo plinfo = {VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, NULL, 0, 1, &set_layout, 1, &push};
    CHECK(vkCreatePipelineLayout(dev, &plinfo, NULL, &layout));
    opaque = pipeline(false);
    blend = pipeline(true);
}

static void render(struct output_buffer *b, int frame) {
    struct vk_target *t = b->priv;
    CHECK(vkWaitForFences(dev, 1, &t->fence, VK_TRUE, UINT64_MAX));  // the previous use of this buffer
    CHECK(vkResetFences(dev, 1, &t->fence));
    CHECK(vkResetCommandBuffer(t->cmd, 0));
    VkCommandBufferBeginInfo begin = {VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, NULL,
                                      VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT, NULL};
    CHECK(vkBeginCommandBuffer(t->cmd, &begin));
    // Acquire from Android; every pixel is rewritten, so the old contents may be discarded.
    barrier(t->cmd, t->image, VK_IMAGE_LAYOUT_UNDEFINED, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, 0,
            VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT,
            VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT, VK_QUEUE_FAMILY_FOREIGN_EXT, family);
    VkRenderingAttachmentInfo color = {
        .sType = VK_STRUCTURE_TYPE_RENDERING_ATTACHMENT_INFO, .imageView = t->view,
        .imageLayout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, .loadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE,
        .storeOp = VK_ATTACHMENT_STORE_OP_STORE};
    VkRenderingInfo rendering = {.sType = VK_STRUCTURE_TYPE_RENDERING_INFO,
                                 .renderArea = {{0, 0}, {opt.width, opt.height}}, .layerCount = 1,
                                 .colorAttachmentCount = 1, .pColorAttachments = &color};
    vkCmdBeginRendering(t->cmd, &rendering);
    VkViewport viewport = {0, 0, opt.width, opt.height, 0, 1};
    VkRect2D scissor = {{0, 0}, {opt.width, opt.height}};
    vkCmdSetViewport(t->cmd, 0, 1, &viewport);
    vkCmdSetScissor(t->cmd, 0, 1, &scissor);
    for (int l = 0; l <= opt.layers; l++) {
        struct quad q;
        layer_quad(l, frame, &q);
        // Flip Y: GL NDC has +Y up, Vulkan +Y down; keeps both renderers' images identical.
        q.rect[1] = -(q.rect[1] + q.rect[3]);
        vkCmdBindPipeline(t->cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, l ? blend : opaque);
        vkCmdBindDescriptorSets(t->cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, layout, 0, 1, &sets[l], 0, NULL);
        vkCmdPushConstants(t->cmd, layout, VK_SHADER_STAGE_VERTEX_BIT | VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof q, &q);
        vkCmdDraw(t->cmd, 4, 1, 0, 0);
    }
    vkCmdEndRendering(t->cmd);
    barrier(t->cmd, t->image, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL, VK_IMAGE_LAYOUT_GENERAL,
            VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT, 0, VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT,
            VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, family, VK_QUEUE_FAMILY_FOREIGN_EXT);
    CHECK(vkEndCommandBuffer(t->cmd));
    VkSubmitInfo submit = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &t->cmd};
    CHECK(vkQueueSubmit(queue, 1, &submit, t->fence));
}

static void wait(struct output_buffer *b) {
    struct vk_target *t = b->priv;
    if (!strcmp(opt.sync, "finish")) CHECK(vkQueueWaitIdle(queue));
    else if (!strcmp(opt.sync, "fence")) CHECK(vkWaitForFences(dev, 1, &t->fence, VK_TRUE, UINT64_MAX));
}

static const char *device_name(void) { return device; }
static void destroy(void) { vkDeviceWaitIdle(dev); }

const struct renderer vulkan_renderer = {init, render, wait, device_name, destroy};
