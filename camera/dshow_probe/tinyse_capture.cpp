#define NOMINMAX
#define TINYSE_CAPTURE_EXPORTS

#include "tinyse_capture.h"

#include <dshow.h>
#include <dvdmedia.h>
#include <windows.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <deque>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

// qedit.h is not shipped with recent Windows SDKs, so define only the legacy
// SampleGrabber COM pieces used by this capture backend.
static const CLSID CLSID_SampleGrabberLocal = {
    0xC1F400A0, 0x3F08, 0x11D3, {0x9F, 0x0B, 0x00, 0x60, 0x08, 0x03, 0x9E, 0x37}};
static const CLSID CLSID_NullRendererLocal = {
    0xC1F400A4, 0x3F08, 0x11D3, {0x9F, 0x0B, 0x00, 0x60, 0x08, 0x03, 0x9E, 0x37}};
static const IID IID_ISampleGrabberLocal = {
    0x6B652FFF, 0x11FE, 0x4FCE, {0x92, 0xAD, 0x02, 0x66, 0xB5, 0xD7, 0xC7, 0x8F}};
static const IID IID_ISampleGrabberCBLocal = {
    0x0579154A, 0x2B53, 0x4994, {0xB0, 0xD0, 0xE7, 0x73, 0x14, 0x8E, 0xFF, 0x85}};

struct ISampleGrabberCBLocal : public IUnknown {
    virtual HRESULT STDMETHODCALLTYPE SampleCB(double sample_time, IMediaSample *sample) = 0;
    virtual HRESULT STDMETHODCALLTYPE BufferCB(double sample_time, BYTE *buffer, long buffer_len) = 0;
};

struct ISampleGrabberLocal : public IUnknown {
    virtual HRESULT STDMETHODCALLTYPE SetOneShot(BOOL one_shot) = 0;
    virtual HRESULT STDMETHODCALLTYPE SetMediaType(const AM_MEDIA_TYPE *type) = 0;
    virtual HRESULT STDMETHODCALLTYPE GetConnectedMediaType(AM_MEDIA_TYPE *type) = 0;
    virtual HRESULT STDMETHODCALLTYPE SetBufferSamples(BOOL buffer_them) = 0;
    virtual HRESULT STDMETHODCALLTYPE GetCurrentBuffer(long *buffer_size, long *buffer) = 0;
    virtual HRESULT STDMETHODCALLTYPE GetCurrentSample(IMediaSample **sample) = 0;
    virtual HRESULT STDMETHODCALLTYPE SetCallback(ISampleGrabberCBLocal *callback, long which_method_to_callback) = 0;
};

template <class T>
void safe_release(T **ptr)
{
    if (ptr && *ptr) {
        (*ptr)->Release();
        *ptr = nullptr;
    }
}

void free_media_type(AM_MEDIA_TYPE *mt)
{
    if (!mt) return;
    if (mt->cbFormat != 0) {
        CoTaskMemFree(mt->pbFormat);
        mt->cbFormat = 0;
        mt->pbFormat = nullptr;
    }
    safe_release(&mt->pUnk);
}

double fps_from_avg_time(LONGLONG avg_time)
{
    return avg_time > 0 ? 10000000.0 / static_cast<double>(avg_time) : 0.0;
}

uint32_t fourcc_from_guid(const GUID &guid)
{
    if (guid.Data2 == 0x0000 && guid.Data3 == 0x0010
        && guid.Data4[0] == 0x80 && guid.Data4[1] == 0x00
        && guid.Data4[2] == 0x00 && guid.Data4[3] == 0xAA
        && guid.Data4[4] == 0x00 && guid.Data4[5] == 0x38
        && guid.Data4[6] == 0x9B && guid.Data4[7] == 0x71) {
        return guid.Data1;
    }
    return 0;
}

bool trace_enabled()
{
    return GetEnvironmentVariableW(L"TINYSE_CAPTURE_TRACE", nullptr, 0) > 0;
}

void trace(const wchar_t *message)
{
    if (trace_enabled()) {
        const int chars = WideCharToMultiByte(CP_UTF8, 0, message, -1, nullptr, 0, nullptr, nullptr);
        if (chars <= 0) {
            return;
        }
        std::string text(static_cast<size_t>(chars), '\0');
        WideCharToMultiByte(CP_UTF8, 0, message, -1, text.data(), chars, nullptr, nullptr);
        if (!text.empty() && text.back() == '\0') {
            text.pop_back();
        }
        std::cerr << "[tinyse_capture] " << text << "\n";
    }
}

class ScopedCriticalSection {
public:
    explicit ScopedCriticalSection(CRITICAL_SECTION *section) : section_(section)
    {
        EnterCriticalSection(section_);
    }

    ~ScopedCriticalSection()
    {
        LeaveCriticalSection(section_);
    }

private:
    CRITICAL_SECTION *section_;
};

constexpr size_t kMaxRecordQueueFrames = 256;
constexpr size_t kMaxRecordQueueBytes = 128ull * 1024ull * 1024ull;

struct RecordPacket {
    std::vector<uint8_t> bytes;
    int64_t capture_frame_index = 0;
    double sample_time = 0.0;
    std::chrono::steady_clock::time_point wall_time;
};

std::wstring read_bstr_property(IPropertyBag *bag, const wchar_t *name)
{
    VARIANT value;
    VariantInit(&value);
    if (FAILED(bag->Read(name, &value, nullptr))) {
        VariantClear(&value);
        return L"";
    }
    std::wstring result;
    if (value.vt == VT_BSTR && value.bstrVal != nullptr) {
        result = value.bstrVal;
    }
    VariantClear(&value);
    return result;
}

bool get_dimensions(AM_MEDIA_TYPE *mt, int *width, int *height, LONGLONG *avg_time)
{
    if (!mt || !mt->pbFormat) {
        return false;
    }
    if (mt->formattype == FORMAT_VideoInfo) {
        auto *vih = reinterpret_cast<VIDEOINFOHEADER *>(mt->pbFormat);
        *width = vih->bmiHeader.biWidth;
        *height = std::abs(vih->bmiHeader.biHeight);
        *avg_time = vih->AvgTimePerFrame;
        return true;
    }
    if (mt->formattype == FORMAT_VideoInfo2) {
        auto *vih = reinterpret_cast<VIDEOINFOHEADER2 *>(mt->pbFormat);
        *width = vih->bmiHeader.biWidth;
        *height = std::abs(vih->bmiHeader.biHeight);
        *avg_time = vih->AvgTimePerFrame;
        return true;
    }
    return false;
}

void set_avg_time(AM_MEDIA_TYPE *mt, LONGLONG avg_time)
{
    if (!mt || !mt->pbFormat) {
        return;
    }
    if (mt->formattype == FORMAT_VideoInfo) {
        reinterpret_cast<VIDEOINFOHEADER *>(mt->pbFormat)->AvgTimePerFrame = avg_time;
    } else if (mt->formattype == FORMAT_VideoInfo2) {
        reinterpret_cast<VIDEOINFOHEADER2 *>(mt->pbFormat)->AvgTimePerFrame = avg_time;
    }
}

class TinySeCapture {
public:
    TinySeCapture(
        const wchar_t *needle,
        int width,
        int height,
        int fps,
        tinyse_frame_callback callback,
        void *user)
        : needle_(needle && needle[0] ? needle : L"OBSBOT Tiny SE"),
          width_(width > 0 ? width : 1920),
          height_(height > 0 ? height : 1080),
          fps_(fps > 0 ? fps : 100),
          callback_(callback),
          user_(user)
    {
        InitializeCriticalSection(&stats_cs_);
        InitializeCriticalSection(&error_cs_);
        InitializeCriticalSection(&record_cs_);
        InitializeConditionVariable(&record_cv_);
    }

    ~TinySeCapture()
    {
        stop();
        DeleteCriticalSection(&record_cs_);
        DeleteCriticalSection(&error_cs_);
        DeleteCriticalSection(&stats_cs_);
    }

    int start()
    {
        trace(L"start: enter");
        if (thread_.joinable()) {
            trace(L"start: already joinable");
            return 0;
        }
        stop_requested_.store(false);
        start_done_.store(false);
        start_result_.store(E_FAIL);
        trace(L"start: launching thread");
        thread_ = std::thread(&TinySeCapture::run, this);

        trace(L"start: waiting for run thread");
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
        while (!start_done_.load() && std::chrono::steady_clock::now() < deadline) {
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        const bool ready = start_done_.load();
        if (!ready) {
            trace(L"start: timeout");
            set_error(L"Timed out while starting DirectShow capture", E_FAIL);
            stop_requested_.store(true);
            if (thread_.joinable()) {
                thread_.join();
            }
            return -1;
        }
        if (FAILED(static_cast<HRESULT>(start_result_.load()))) {
            trace(L"start: failed");
            if (thread_.joinable()) {
                thread_.join();
            }
            return -1;
        }
        trace(L"start: ok");
        return 0;
    }

    int stop()
    {
        trace(L"stop: enter");
        stop_record(nullptr);
        stop_requested_.store(true);
        if (thread_.joinable()) {
            trace(L"stop: joining");
            thread_.join();
        }
        trace(L"stop: ok");
        return 0;
    }

    int get_stats(TinySeCaptureStats *out)
    {
        if (!out) {
            return -1;
        }
        ScopedCriticalSection lock(&stats_cs_);
        *out = stats_;
        out->running = running_.load() ? 1 : 0;
        if (frames_ >= 2) {
            const double wall_seconds = std::chrono::duration<double>(last_wall_ - first_wall_).count();
            out->wall_fps = wall_seconds > 0.0 ? static_cast<double>(frames_ - 1) / wall_seconds : 0.0;
            const double sample_seconds = last_sample_time_ - first_sample_time_;
            out->sample_fps = sample_seconds > 0.0 ? static_cast<double>(frames_ - 1) / sample_seconds : 0.0;
        }
        out->frames = frames_;
        out->last_hresult = last_hresult_;
        return 0;
    }

    int start_record(const wchar_t *stem_path)
    {
        if (!stem_path || stem_path[0] == L'\0') {
            set_record_error(L"Record stem path is empty", E_INVALIDARG);
            return -1;
        }

        {
            ScopedCriticalSection lock(&record_cs_);
            if (recording_) {
                set_record_error(L"Recording is already active", E_FAIL);
                return -1;
            }
        }
        if (record_thread_.joinable()) {
            set_record_error(L"Previous recording thread is still active", E_FAIL);
            return -1;
        }

        const std::wstring stem(stem_path);
        const std::wstring mjpg_path = stem + L".mjpg";
        const std::wstring csv_path = stem + L".csv";

        FILE *mjpg = nullptr;
        FILE *csv = nullptr;
        if (_wfopen_s(&mjpg, mjpg_path.c_str(), L"wb") != 0 || !mjpg) {
            set_record_error(L"Failed to open MJPEG output file", E_FAIL);
            return -1;
        }
        if (_wfopen_s(&csv, csv_path.c_str(), L"wb") != 0 || !csv) {
            std::fclose(mjpg);
            set_record_error(L"Failed to open recording CSV file", E_FAIL);
            return -1;
        }

        std::fprintf(csv, "record_frame_index,capture_frame_index,sample_time,record_elapsed_seconds,offset,length\n");
        std::fflush(csv);

        {
            ScopedCriticalSection lock(&record_cs_);
            record_queue_.clear();
            record_queued_bytes_ = 0;
            record_stats_ = {};
            record_mjpg_ = mjpg;
            record_csv_ = csv;
            record_offset_ = 0;
            record_stop_requested_ = false;
            recording_ = true;
            record_start_wall_ = std::chrono::steady_clock::now();
        }

        record_thread_ = std::thread(&TinySeCapture::record_writer_loop, this);
        return 0;
    }

    int stop_record(TinySeRecordingStats *out)
    {
        {
            ScopedCriticalSection lock(&record_cs_);
            recording_ = false;
            record_stop_requested_ = true;
            WakeAllConditionVariable(&record_cv_);
        }

        if (record_thread_.joinable()) {
            record_thread_.join();
        }

        if (out) {
            return get_record_stats(out);
        }
        return 0;
    }

    int get_record_stats(TinySeRecordingStats *out)
    {
        if (!out) {
            return -1;
        }
        ScopedCriticalSection lock(&record_cs_);
        *out = record_stats_;
        out->queued_frames = static_cast<int64_t>(record_queue_.size());
        out->queued_bytes = static_cast<int64_t>(record_queued_bytes_);
        out->recording = recording_ ? 1 : 0;
        return 0;
    }

    int last_error(wchar_t *buffer, int max_chars)
    {
        if (!buffer || max_chars <= 0) {
            return -1;
        }
        ScopedCriticalSection lock(&error_cs_);
        const int count = static_cast<int>(std::min<size_t>(last_error_.size(), static_cast<size_t>(max_chars - 1)));
        std::wmemcpy(buffer, last_error_.c_str(), static_cast<size_t>(count));
        buffer[count] = L'\0';
        return count;
    }

    void on_frame(double sample_time, BYTE *buffer, long buffer_len)
    {
        int64_t frame_index = 0;
        {
            ScopedCriticalSection lock(&stats_cs_);
            frame_index = ++frames_;
            if (frame_index == 1) {
                first_sample_time_ = sample_time;
                first_wall_ = std::chrono::steady_clock::now();
            }
            last_sample_time_ = sample_time;
            last_wall_ = std::chrono::steady_clock::now();
            stats_.frames = frames_;
        }

        enqueue_record_frame(buffer, buffer_len, frame_index, sample_time);

        if (callback_) {
            callback_(reinterpret_cast<const uint8_t *>(buffer), buffer_len, frame_index, sample_time, user_);
        }
    }

private:
    class FrameCallback final : public ISampleGrabberCBLocal {
    public:
        explicit FrameCallback(TinySeCapture *owner) : owner_(owner) {}

        STDMETHODIMP QueryInterface(REFIID iid, void **out) override
        {
            if (!out) return E_POINTER;
            if (iid == IID_IUnknown || iid == IID_ISampleGrabberCBLocal) {
                *out = static_cast<ISampleGrabberCBLocal *>(this);
                AddRef();
                return S_OK;
            }
            *out = nullptr;
            return E_NOINTERFACE;
        }

        STDMETHODIMP_(ULONG) AddRef() override { return ++refs_; }
        STDMETHODIMP_(ULONG) Release() override { return --refs_; }
        HRESULT STDMETHODCALLTYPE SampleCB(double, IMediaSample *) override { return S_OK; }

        HRESULT STDMETHODCALLTYPE BufferCB(double sample_time, BYTE *buffer, long buffer_len) override
        {
            owner_->on_frame(sample_time, buffer, buffer_len);
            return S_OK;
        }

    private:
        TinySeCapture *owner_;
        std::atomic<ULONG> refs_{1};
    };

    void notify_start(HRESULT hr)
    {
        start_result_.store(static_cast<long>(hr));
        start_done_.store(true);
    }

    void set_error(const std::wstring &message, HRESULT hr)
    {
        {
            ScopedCriticalSection lock(&error_cs_);
            last_error_ = message;
        }
        {
            ScopedCriticalSection lock(&stats_cs_);
            last_hresult_ = static_cast<int32_t>(hr);
            stats_.last_hresult = last_hresult_;
        }
    }

    void set_record_error(const std::wstring &message, HRESULT hr)
    {
        set_error(message, hr);
        ScopedCriticalSection lock(&record_cs_);
        record_stats_.last_hresult = static_cast<int32_t>(hr);
    }

    void enqueue_record_frame(BYTE *buffer, long buffer_len, int64_t frame_index, double sample_time)
    {
        if (!buffer || buffer_len <= 0) {
            return;
        }

        {
            ScopedCriticalSection lock(&record_cs_);
            if (!recording_) {
                return;
            }
        }

        RecordPacket packet;
        try {
            packet.bytes.resize(static_cast<size_t>(buffer_len));
            std::memcpy(packet.bytes.data(), buffer, static_cast<size_t>(buffer_len));
        } catch (...) {
            ScopedCriticalSection lock(&record_cs_);
            ++record_stats_.frames_dropped;
            record_stats_.last_hresult = E_OUTOFMEMORY;
            return;
        }
        packet.capture_frame_index = frame_index;
        packet.sample_time = sample_time;
        packet.wall_time = std::chrono::steady_clock::now();

        {
            ScopedCriticalSection lock(&record_cs_);
            if (!recording_) {
                return;
            }

            const size_t packet_bytes = packet.bytes.size();
            const bool frame_limit_hit = record_queue_.size() >= kMaxRecordQueueFrames;
            const bool byte_limit_hit = record_queued_bytes_ + packet_bytes > kMaxRecordQueueBytes;
            if (frame_limit_hit || byte_limit_hit) {
                ++record_stats_.frames_dropped;
                return;
            }

            record_queued_bytes_ += packet_bytes;
            record_queue_.push_back(std::move(packet));
            record_stats_.queued_frames = static_cast<int64_t>(record_queue_.size());
            record_stats_.queued_bytes = static_cast<int64_t>(record_queued_bytes_);
            record_stats_.queue_high_watermark_frames = std::max(
                record_stats_.queue_high_watermark_frames,
                static_cast<int64_t>(record_queue_.size()));
            record_stats_.queue_high_watermark_bytes = std::max(
                record_stats_.queue_high_watermark_bytes,
                static_cast<int64_t>(record_queued_bytes_));
            WakeConditionVariable(&record_cv_);
        }
    }

    void record_writer_loop()
    {
        while (true) {
            RecordPacket packet;
            {
                ScopedCriticalSection lock(&record_cs_);
                while (record_queue_.empty() && !record_stop_requested_) {
                    SleepConditionVariableCS(&record_cv_, &record_cs_, INFINITE);
                }

                if (record_queue_.empty() && record_stop_requested_) {
                    break;
                }

                packet = std::move(record_queue_.front());
                record_queue_.pop_front();
                record_queued_bytes_ -= packet.bytes.size();
                record_stats_.queued_frames = static_cast<int64_t>(record_queue_.size());
                record_stats_.queued_bytes = static_cast<int64_t>(record_queued_bytes_);
            }

            FILE *mjpg = nullptr;
            FILE *csv = nullptr;
            int64_t record_frame_index = 0;
            int64_t offset = 0;
            {
                ScopedCriticalSection lock(&record_cs_);
                mjpg = record_mjpg_;
                csv = record_csv_;
                record_frame_index = record_stats_.frames_written + 1;
                offset = record_offset_;
            }

            const size_t length = packet.bytes.size();
            const double elapsed = std::chrono::duration<double>(packet.wall_time - record_start_wall_).count();
            const bool write_ok = mjpg && csv
                && std::fwrite(packet.bytes.data(), 1, length, mjpg) == length
                && std::fprintf(
                       csv,
                       "%lld,%lld,%.9f,%.9f,%lld,%zu\n",
                       static_cast<long long>(record_frame_index),
                       static_cast<long long>(packet.capture_frame_index),
                       packet.sample_time,
                       elapsed,
                       static_cast<long long>(offset),
                       length) > 0;

            if (!write_ok) {
                set_record_error(L"Failed to write MJPEG recording data", E_FAIL);
                ScopedCriticalSection lock(&record_cs_);
                recording_ = false;
                record_stop_requested_ = true;
                record_stats_.frames_dropped += static_cast<int64_t>(record_queue_.size());
                record_queue_.clear();
                record_queued_bytes_ = 0;
                record_stats_.queued_frames = 0;
                record_stats_.queued_bytes = 0;
                break;
            }

            {
                ScopedCriticalSection lock(&record_cs_);
                record_offset_ += static_cast<int64_t>(length);
                ++record_stats_.frames_written;
                record_stats_.bytes_written += static_cast<int64_t>(length);
            }
        }

        FILE *mjpg = nullptr;
        FILE *csv = nullptr;
        {
            ScopedCriticalSection lock(&record_cs_);
            mjpg = record_mjpg_;
            csv = record_csv_;
            record_mjpg_ = nullptr;
            record_csv_ = nullptr;
            recording_ = false;
            record_stop_requested_ = true;
            record_stats_.queued_frames = 0;
            record_stats_.queued_bytes = 0;
        }

        if (csv) {
            std::fflush(csv);
            std::fclose(csv);
        }
        if (mjpg) {
            std::fflush(mjpg);
            std::fclose(mjpg);
        }
    }

    IBaseFilter *find_source_filter()
    {
        ICreateDevEnum *dev_enum = nullptr;
        IEnumMoniker *enum_moniker = nullptr;
        IMoniker *moniker = nullptr;
        IBaseFilter *filter = nullptr;

        HRESULT hr = CoCreateInstance(
            CLSID_SystemDeviceEnum, nullptr, CLSCTX_INPROC_SERVER,
            IID_ICreateDevEnum, reinterpret_cast<void **>(&dev_enum));
        if (FAILED(hr) || !dev_enum) {
            set_error(L"CoCreateInstance(SystemDeviceEnum) failed", hr);
            return nullptr;
        }

        hr = dev_enum->CreateClassEnumerator(CLSID_VideoInputDeviceCategory, &enum_moniker, 0);
        if (hr != S_OK || !enum_moniker) {
            set_error(L"CreateClassEnumerator(VideoInputDeviceCategory) failed", hr);
            safe_release(&dev_enum);
            return nullptr;
        }

        bool matched = false;
        while (enum_moniker->Next(1, &moniker, nullptr) == S_OK) {
            IPropertyBag *bag = nullptr;
            std::wstring friendly;
            std::wstring path;
            if (SUCCEEDED(moniker->BindToStorage(nullptr, nullptr, IID_IPropertyBag, reinterpret_cast<void **>(&bag)))) {
                friendly = read_bstr_property(bag, L"FriendlyName");
                path = read_bstr_property(bag, L"DevicePath");
                safe_release(&bag);
            }

            if (friendly.find(needle_) != std::wstring::npos || path.find(needle_) != std::wstring::npos) {
                matched = true;
                hr = moniker->BindToObject(nullptr, nullptr, IID_IBaseFilter, reinterpret_cast<void **>(&filter));
                if (FAILED(hr)) {
                    set_error(L"BindToObject(IBaseFilter) failed", hr);
                }
                safe_release(&moniker);
                break;
            }
            safe_release(&moniker);
        }

        if (!filter && !matched) {
            set_error(L"OBSBOT Tiny SE source filter not found", E_FAIL);
        }
        safe_release(&enum_moniker);
        safe_release(&dev_enum);
        return filter;
    }

    IAMStreamConfig *find_stream_config(IBaseFilter *filter)
    {
        IEnumPins *enum_pins = nullptr;
        if (FAILED(filter->EnumPins(&enum_pins)) || !enum_pins) {
            return nullptr;
        }

        IPin *pin = nullptr;
        while (enum_pins->Next(1, &pin, nullptr) == S_OK) {
            PIN_DIRECTION direction;
            if (SUCCEEDED(pin->QueryDirection(&direction)) && direction == PINDIR_OUTPUT) {
                IAMStreamConfig *config = nullptr;
                if (SUCCEEDED(pin->QueryInterface(IID_IAMStreamConfig, reinterpret_cast<void **>(&config)))) {
                    safe_release(&pin);
                    safe_release(&enum_pins);
                    return config;
                }
            }
            safe_release(&pin);
        }
        safe_release(&enum_pins);
        return nullptr;
    }

    AM_MEDIA_TYPE *find_mjpg_type(IAMStreamConfig *config)
    {
        int count = 0;
        int cap_size = 0;
        HRESULT hr = config->GetNumberOfCapabilities(&count, &cap_size);
        if (FAILED(hr) || count <= 0 || cap_size <= 0) {
            set_error(L"GetNumberOfCapabilities failed", hr);
            return nullptr;
        }

        auto *caps = new BYTE[static_cast<size_t>(cap_size)];
        for (int i = 0; i < count; ++i) {
            AM_MEDIA_TYPE *mt = nullptr;
            std::memset(caps, 0, static_cast<size_t>(cap_size));
            hr = config->GetStreamCaps(i, &mt, caps);
            if (FAILED(hr) || !mt) {
                continue;
            }

            int width = 0;
            int height = 0;
            LONGLONG avg_time = 0;
            if (get_dimensions(mt, &width, &height, &avg_time)
                && width == width_ && height == height_
                && mt->subtype == MEDIASUBTYPE_MJPG) {
                delete[] caps;
                return mt;
            }
            free_media_type(mt);
            CoTaskMemFree(mt);
        }

        delete[] caps;
        set_error(L"Requested MJPG media type not found", E_FAIL);
        return nullptr;
    }

    HRESULT set_source_format(IBaseFilter *source)
    {
        IAMStreamConfig *config = find_stream_config(source);
        if (!config) {
            set_error(L"IAMStreamConfig output pin not found", E_FAIL);
            return E_FAIL;
        }

        AM_MEDIA_TYPE *mt = find_mjpg_type(config);
        if (!mt) {
            safe_release(&config);
            return E_FAIL;
        }

        const LONGLONG target_avg_time = fps_ > 0 ? 10000000LL / fps_ : 100000;
        set_avg_time(mt, target_avg_time);
        HRESULT hr = config->SetFormat(mt);
        if (FAILED(hr)) {
            set_error(L"IAMStreamConfig::SetFormat failed", hr);
        }

        free_media_type(mt);
        CoTaskMemFree(mt);
        safe_release(&config);
        return hr;
    }

    void update_connected_format(ISampleGrabberLocal *grabber)
    {
        AM_MEDIA_TYPE mt;
        std::memset(&mt, 0, sizeof(mt));
        HRESULT hr = grabber->GetConnectedMediaType(&mt);
        if (FAILED(hr)) {
            set_error(L"SampleGrabber::GetConnectedMediaType failed", hr);
            return;
        }

        int width = 0;
        int height = 0;
        LONGLONG avg_time = 0;
        get_dimensions(&mt, &width, &height, &avg_time);
        {
            ScopedCriticalSection lock(&stats_cs_);
            stats_.connected_width = width;
            stats_.connected_height = height;
            stats_.connected_avg_time = avg_time;
            stats_.connected_fps = static_cast<int32_t>(std::lround(fps_from_avg_time(avg_time)));
            stats_.connected_subtype = fourcc_from_guid(mt.subtype);
        }
        free_media_type(&mt);
    }

    void run()
    {
        trace(L"run: enter");
        HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
        if (FAILED(hr)) {
            set_error(L"CoInitializeEx failed", hr);
            notify_start(hr);
            return;
        }
        trace(L"run: COM initialized");

        IGraphBuilder *graph = nullptr;
        ICaptureGraphBuilder2 *capture_graph = nullptr;
        IBaseFilter *source = nullptr;
        IBaseFilter *grabber_filter = nullptr;
        IBaseFilter *null_renderer = nullptr;
        ISampleGrabberLocal *grabber = nullptr;
        IMediaControl *control = nullptr;
        FrameCallback frame_callback(this);

        {
            ScopedCriticalSection lock(&stats_cs_);
            stats_ = {};
            stats_.requested_width = width_;
            stats_.requested_height = height_;
            stats_.requested_fps = fps_;
            frames_ = 0;
        }

        hr = CoCreateInstance(CLSID_FilterGraph, nullptr, CLSCTX_INPROC_SERVER, IID_IGraphBuilder, reinterpret_cast<void **>(&graph));
        trace(L"run: CoCreateInstance FilterGraph returned");
        if (FAILED(hr)) {
            set_error(L"CoCreateInstance(FilterGraph) failed", hr);
            notify_start(hr);
            goto done;
        }

        hr = CoCreateInstance(CLSID_CaptureGraphBuilder2, nullptr, CLSCTX_INPROC_SERVER, IID_ICaptureGraphBuilder2, reinterpret_cast<void **>(&capture_graph));
        trace(L"run: CoCreateInstance CaptureGraphBuilder2 returned");
        if (FAILED(hr)) {
            set_error(L"CoCreateInstance(CaptureGraphBuilder2) failed", hr);
            notify_start(hr);
            goto done;
        }

        hr = capture_graph->SetFiltergraph(graph);
        trace(L"run: SetFiltergraph returned");
        if (FAILED(hr)) {
            set_error(L"SetFiltergraph failed", hr);
            notify_start(hr);
            goto done;
        }

        source = find_source_filter();
        trace(L"run: find_source_filter returned");
        if (!source) {
            notify_start(E_FAIL);
            goto done;
        }

        hr = graph->AddFilter(source, L"OBSBOT Tiny SE");
        trace(L"run: AddFilter source returned");
        if (FAILED(hr)) {
            set_error(L"AddFilter(source) failed", hr);
            notify_start(hr);
            goto done;
        }

        hr = set_source_format(source);
        trace(L"run: set_source_format returned");
        if (FAILED(hr)) {
            notify_start(hr);
            goto done;
        }

        hr = CoCreateInstance(CLSID_SampleGrabberLocal, nullptr, CLSCTX_INPROC_SERVER, IID_IBaseFilter, reinterpret_cast<void **>(&grabber_filter));
        trace(L"run: CoCreateInstance SampleGrabber returned");
        if (FAILED(hr)) {
            set_error(L"CoCreateInstance(SampleGrabber) failed", hr);
            notify_start(hr);
            goto done;
        }

        hr = grabber_filter->QueryInterface(IID_ISampleGrabberLocal, reinterpret_cast<void **>(&grabber));
        trace(L"run: QueryInterface SampleGrabber returned");
        if (FAILED(hr)) {
            set_error(L"QueryInterface(ISampleGrabber) failed", hr);
            notify_start(hr);
            goto done;
        }

        {
            AM_MEDIA_TYPE mt;
            std::memset(&mt, 0, sizeof(mt));
            mt.majortype = MEDIATYPE_Video;
            mt.subtype = MEDIASUBTYPE_NULL;
            mt.formattype = FORMAT_None;
            hr = grabber->SetMediaType(&mt);
            trace(L"run: SampleGrabber SetMediaType returned");
            if (FAILED(hr)) {
                set_error(L"SampleGrabber::SetMediaType failed", hr);
                notify_start(hr);
                goto done;
            }
        }

        grabber->SetBufferSamples(FALSE);
        grabber->SetOneShot(FALSE);
        hr = grabber->SetCallback(&frame_callback, 1);
        trace(L"run: SampleGrabber SetCallback returned");
        if (FAILED(hr)) {
            set_error(L"SampleGrabber::SetCallback failed", hr);
            notify_start(hr);
            goto done;
        }

        hr = graph->AddFilter(grabber_filter, L"SampleGrabber");
        trace(L"run: AddFilter SampleGrabber returned");
        if (FAILED(hr)) {
            set_error(L"AddFilter(SampleGrabber) failed", hr);
            notify_start(hr);
            goto done;
        }

        hr = CoCreateInstance(CLSID_NullRendererLocal, nullptr, CLSCTX_INPROC_SERVER, IID_IBaseFilter, reinterpret_cast<void **>(&null_renderer));
        trace(L"run: CoCreateInstance NullRenderer returned");
        if (FAILED(hr)) {
            set_error(L"CoCreateInstance(NullRenderer) failed", hr);
            notify_start(hr);
            goto done;
        }

        hr = graph->AddFilter(null_renderer, L"NullRenderer");
        trace(L"run: AddFilter NullRenderer returned");
        if (FAILED(hr)) {
            set_error(L"AddFilter(NullRenderer) failed", hr);
            notify_start(hr);
            goto done;
        }

        hr = capture_graph->RenderStream(&PIN_CATEGORY_CAPTURE, &MEDIATYPE_Video, source, grabber_filter, null_renderer);
        trace(L"run: RenderStream returned");
        if (FAILED(hr)) {
            set_error(L"RenderStream(capture -> grabber -> null) failed", hr);
            notify_start(hr);
            goto done;
        }

        update_connected_format(grabber);
        trace(L"run: update_connected_format returned");

        hr = graph->QueryInterface(IID_IMediaControl, reinterpret_cast<void **>(&control));
        trace(L"run: QueryInterface MediaControl returned");
        if (FAILED(hr)) {
            set_error(L"QueryInterface(IMediaControl) failed", hr);
            notify_start(hr);
            goto done;
        }

        hr = control->Run();
        trace(L"run: MediaControl Run returned");
        if (FAILED(hr)) {
            set_error(L"IMediaControl::Run failed", hr);
            notify_start(hr);
            goto done;
        }

        running_.store(true);
        notify_start(S_OK);
        trace(L"run: capture running");
        while (!stop_requested_.load()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(20));
        }

    done:
        trace(L"run: cleanup");
        running_.store(false);
        if (control) {
            control->Stop();
        }
        safe_release(&control);
        safe_release(&grabber);
        safe_release(&null_renderer);
        safe_release(&grabber_filter);
        safe_release(&source);
        safe_release(&capture_graph);
        safe_release(&graph);
        CoUninitialize();
    }

    std::wstring needle_;
    int width_;
    int height_;
    int fps_;
    tinyse_frame_callback callback_;
    void *user_;

    std::thread thread_;
    std::atomic<bool> stop_requested_{false};
    std::atomic<bool> running_{false};

    std::atomic<bool> start_done_{false};
    std::atomic<long> start_result_{E_FAIL};

    CRITICAL_SECTION stats_cs_;
    TinySeCaptureStats stats_{};
    int32_t last_hresult_ = 0;
    int64_t frames_ = 0;
    double first_sample_time_ = 0.0;
    double last_sample_time_ = 0.0;
    std::chrono::steady_clock::time_point first_wall_;
    std::chrono::steady_clock::time_point last_wall_;

    CRITICAL_SECTION error_cs_;
    std::wstring last_error_;

    CRITICAL_SECTION record_cs_;
    CONDITION_VARIABLE record_cv_;
    std::thread record_thread_;
    std::deque<RecordPacket> record_queue_;
    size_t record_queued_bytes_ = 0;
    FILE *record_mjpg_ = nullptr;
    FILE *record_csv_ = nullptr;
    int64_t record_offset_ = 0;
    bool recording_ = false;
    bool record_stop_requested_ = true;
    TinySeRecordingStats record_stats_{};
    std::chrono::steady_clock::time_point record_start_wall_;
};

extern "C" {

TINYSE_CAPTURE_API void *tinyse_capture_create(
    const wchar_t *device_needle,
    int32_t width,
    int32_t height,
    int32_t fps,
    tinyse_frame_callback callback,
    void *user)
{
    try {
        return new TinySeCapture(device_needle, width, height, fps, callback, user);
    } catch (...) {
        return nullptr;
    }
}

TINYSE_CAPTURE_API int32_t tinyse_capture_start(void *handle)
{
    if (!handle) return -1;
    return reinterpret_cast<TinySeCapture *>(handle)->start();
}

TINYSE_CAPTURE_API int32_t tinyse_capture_stop(void *handle)
{
    if (!handle) return -1;
    return reinterpret_cast<TinySeCapture *>(handle)->stop();
}

TINYSE_CAPTURE_API void tinyse_capture_destroy(void *handle)
{
    delete reinterpret_cast<TinySeCapture *>(handle);
}

TINYSE_CAPTURE_API int32_t tinyse_capture_get_stats(void *handle, TinySeCaptureStats *out_stats)
{
    if (!handle) return -1;
    return reinterpret_cast<TinySeCapture *>(handle)->get_stats(out_stats);
}

TINYSE_CAPTURE_API int32_t tinyse_capture_start_record(void *handle, const wchar_t *stem_path)
{
    if (!handle) return -1;
    return reinterpret_cast<TinySeCapture *>(handle)->start_record(stem_path);
}

TINYSE_CAPTURE_API int32_t tinyse_capture_stop_record(void *handle, TinySeRecordingStats *out_stats)
{
    if (!handle) return -1;
    return reinterpret_cast<TinySeCapture *>(handle)->stop_record(out_stats);
}

TINYSE_CAPTURE_API int32_t tinyse_capture_get_record_stats(void *handle, TinySeRecordingStats *out_stats)
{
    if (!handle) return -1;
    return reinterpret_cast<TinySeCapture *>(handle)->get_record_stats(out_stats);
}

TINYSE_CAPTURE_API int32_t tinyse_capture_last_error(
    void *handle,
    wchar_t *buffer,
    int32_t max_chars)
{
    if (!handle) return -1;
    return reinterpret_cast<TinySeCapture *>(handle)->last_error(buffer, max_chars);
}

}
