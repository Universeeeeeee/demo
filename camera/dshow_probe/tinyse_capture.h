#pragma once

#include <stdint.h>

#ifdef _WIN32
#  ifdef TINYSE_CAPTURE_EXPORTS
#    define TINYSE_CAPTURE_API __declspec(dllexport)
#  else
#    define TINYSE_CAPTURE_API __declspec(dllimport)
#  endif
#else
#  define TINYSE_CAPTURE_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef void(__stdcall *tinyse_frame_callback)(
    const uint8_t *data,
    int32_t length,
    int64_t frame_index,
    double sample_time,
    void *user);

typedef struct TinySeCaptureStats {
    int32_t requested_width;
    int32_t requested_height;
    int32_t requested_fps;
    int32_t connected_width;
    int32_t connected_height;
    int32_t connected_fps;
    uint32_t connected_subtype;
    int64_t connected_avg_time;
    int64_t frames;
    double wall_fps;
    double sample_fps;
    int32_t last_hresult;
    int32_t running;
} TinySeCaptureStats;

typedef struct TinySeRecordingStats {
    int64_t frames_written;
    int64_t bytes_written;
    int64_t frames_dropped;
    int64_t queue_high_watermark_frames;
    int64_t queue_high_watermark_bytes;
    int64_t queued_frames;
    int64_t queued_bytes;
    int32_t recording;
    int32_t last_hresult;
} TinySeRecordingStats;

TINYSE_CAPTURE_API void *tinyse_capture_create(
    const wchar_t *device_needle,
    int32_t width,
    int32_t height,
    int32_t fps,
    tinyse_frame_callback callback,
    void *user);

TINYSE_CAPTURE_API int32_t tinyse_capture_start(void *handle);
TINYSE_CAPTURE_API int32_t tinyse_capture_stop(void *handle);
TINYSE_CAPTURE_API void tinyse_capture_destroy(void *handle);
TINYSE_CAPTURE_API int32_t tinyse_capture_get_stats(void *handle, TinySeCaptureStats *out_stats);
TINYSE_CAPTURE_API int32_t tinyse_capture_start_record(void *handle, const wchar_t *stem_path);
TINYSE_CAPTURE_API int32_t tinyse_capture_stop_record(void *handle, TinySeRecordingStats *out_stats);
TINYSE_CAPTURE_API int32_t tinyse_capture_get_record_stats(void *handle, TinySeRecordingStats *out_stats);
TINYSE_CAPTURE_API int32_t tinyse_capture_last_error(
    void *handle,
    wchar_t *buffer,
    int32_t max_chars);

#ifdef __cplusplus
}
#endif
