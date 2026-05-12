#define NOMINMAX

#include <dshow.h>
#include <dvdmedia.h>
#include <windows.h>

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <string>
#include <thread>

// qedit.h is not shipped with recent Windows SDKs, so define the small part of
// SampleGrabber that we need.
// {C1F400A0-3F08-11D3-9F0B-006008039E37}
static const CLSID CLSID_SampleGrabber = {
    0xC1F400A0, 0x3F08, 0x11D3, {0x9F, 0x0B, 0x00, 0x60, 0x08, 0x03, 0x9E, 0x37}};

// {C1F400A4-3F08-11D3-9F0B-006008039E37}
static const CLSID CLSID_NullRendererLocal = {
    0xC1F400A4, 0x3F08, 0x11D3, {0x9F, 0x0B, 0x00, 0x60, 0x08, 0x03, 0x9E, 0x37}};

// {6B652FFF-11FE-4FCE-92AD-0266B5D7C78F}
static const IID IID_ISampleGrabber = {
    0x6B652FFF, 0x11FE, 0x4FCE, {0x92, 0xAD, 0x02, 0x66, 0xB5, 0xD7, 0xC7, 0x8F}};

// {0579154A-2B53-4994-B0D0-E773148EFF85}
static const IID IID_ISampleGrabberCB = {
    0x0579154A, 0x2B53, 0x4994, {0xB0, 0xD0, 0xE7, 0x73, 0x14, 0x8E, 0xFF, 0x85}};

struct ISampleGrabberCB : public IUnknown {
    virtual HRESULT STDMETHODCALLTYPE SampleCB(double sample_time, IMediaSample *sample) = 0;
    virtual HRESULT STDMETHODCALLTYPE BufferCB(double sample_time, BYTE *buffer, long buffer_len) = 0;
};

struct ISampleGrabber : public IUnknown {
    virtual HRESULT STDMETHODCALLTYPE SetOneShot(BOOL one_shot) = 0;
    virtual HRESULT STDMETHODCALLTYPE SetMediaType(const AM_MEDIA_TYPE *type) = 0;
    virtual HRESULT STDMETHODCALLTYPE GetConnectedMediaType(AM_MEDIA_TYPE *type) = 0;
    virtual HRESULT STDMETHODCALLTYPE SetBufferSamples(BOOL buffer_them) = 0;
    virtual HRESULT STDMETHODCALLTYPE GetCurrentBuffer(long *buffer_size, long *buffer) = 0;
    virtual HRESULT STDMETHODCALLTYPE GetCurrentSample(IMediaSample **sample) = 0;
    virtual HRESULT STDMETHODCALLTYPE SetCallback(ISampleGrabberCB *callback, long which_method_to_callback) = 0;
};

template <class T>
void safe_release(T **ptr)
{
    if (ptr && *ptr) {
        (*ptr)->Release();
        *ptr = nullptr;
    }
}

void print_hresult(const wchar_t *label, HRESULT hr)
{
    std::wcout << L"  " << label << L": hr=0x" << std::hex << std::setw(8)
               << std::setfill(L'0') << static_cast<unsigned long>(hr)
               << std::dec << std::setfill(L' ') << L"\n";
}

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

double fps_from_avg_time(LONGLONG avg_time)
{
    return avg_time > 0 ? 10000000.0 / static_cast<double>(avg_time) : 0.0;
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

class FrameCounter final : public ISampleGrabberCB {
public:
    STDMETHODIMP QueryInterface(REFIID iid, void **out) override
    {
        if (!out) return E_POINTER;
        if (iid == IID_IUnknown || iid == IID_ISampleGrabberCB) {
            *out = static_cast<ISampleGrabberCB *>(this);
            AddRef();
            return S_OK;
        }
        *out = nullptr;
        return E_NOINTERFACE;
    }

    STDMETHODIMP_(ULONG) AddRef() override { return ++refs_; }
    STDMETHODIMP_(ULONG) Release() override
    {
        const ULONG value = --refs_;
        return value;
    }

    HRESULT STDMETHODCALLTYPE SampleCB(double, IMediaSample *) override { return S_OK; }

    HRESULT STDMETHODCALLTYPE BufferCB(double sample_time, BYTE *, long) override
    {
        const long value = ++frames_;
        if (value == 1) {
            first_sample_time_ = sample_time;
            first_wall_ = std::chrono::steady_clock::now();
        }
        last_sample_time_ = sample_time;
        last_wall_ = std::chrono::steady_clock::now();
        return S_OK;
    }

    long frames() const { return frames_.load(); }

    double wall_fps() const
    {
        if (frames_ < 2) return 0.0;
        const double seconds = std::chrono::duration<double>(last_wall_ - first_wall_).count();
        return seconds > 0 ? static_cast<double>(frames_ - 1) / seconds : 0.0;
    }

    double sample_fps() const
    {
        if (frames_ < 2) return 0.0;
        const double seconds = last_sample_time_ - first_sample_time_;
        return seconds > 0 ? static_cast<double>(frames_ - 1) / seconds : 0.0;
    }

private:
    std::atomic<ULONG> refs_{1};
    std::atomic<long> frames_{0};
    double first_sample_time_ = 0.0;
    double last_sample_time_ = 0.0;
    std::chrono::steady_clock::time_point first_wall_;
    std::chrono::steady_clock::time_point last_wall_;
};

IBaseFilter *find_tiny_filter(const std::wstring &needle)
{
    ICreateDevEnum *dev_enum = nullptr;
    IEnumMoniker *enum_moniker = nullptr;
    IMoniker *moniker = nullptr;
    IBaseFilter *filter = nullptr;

    HRESULT hr = CoCreateInstance(
        CLSID_SystemDeviceEnum, nullptr, CLSCTX_INPROC_SERVER,
        IID_ICreateDevEnum, reinterpret_cast<void **>(&dev_enum));
    if (FAILED(hr) || !dev_enum) {
        print_hresult(L"CoCreateInstance(SystemDeviceEnum)", hr);
        return nullptr;
    }

    hr = dev_enum->CreateClassEnumerator(CLSID_VideoInputDeviceCategory, &enum_moniker, 0);
    if (hr != S_OK || !enum_moniker) {
        print_hresult(L"CreateClassEnumerator(VideoInputDeviceCategory)", hr);
        safe_release(&dev_enum);
        return nullptr;
    }

    while (enum_moniker->Next(1, &moniker, nullptr) == S_OK) {
        IPropertyBag *bag = nullptr;
        std::wstring friendly;
        std::wstring path;
        if (SUCCEEDED(moniker->BindToStorage(nullptr, nullptr, IID_IPropertyBag, reinterpret_cast<void **>(&bag)))) {
            friendly = read_bstr_property(bag, L"FriendlyName");
            path = read_bstr_property(bag, L"DevicePath");
            safe_release(&bag);
        }
        if (friendly.find(needle) != std::wstring::npos || path.find(needle) != std::wstring::npos) {
            std::wcout << L"Matched device: " << friendly << L"\n";
            std::wcout << L"  path=" << path << L"\n";
            hr = moniker->BindToObject(nullptr, nullptr, IID_IBaseFilter, reinterpret_cast<void **>(&filter));
            print_hresult(L"BindToObject(IBaseFilter)", hr);
            safe_release(&moniker);
            break;
        }
        safe_release(&moniker);
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

AM_MEDIA_TYPE *find_mjpg_type(IAMStreamConfig *config, int target_width, int target_height)
{
    int count = 0;
    int cap_size = 0;
    if (FAILED(config->GetNumberOfCapabilities(&count, &cap_size)) || count <= 0 || cap_size <= 0) {
        return nullptr;
    }

    auto *caps = new BYTE[static_cast<size_t>(cap_size)];
    for (int i = 0; i < count; ++i) {
        AM_MEDIA_TYPE *mt = nullptr;
        std::memset(caps, 0, static_cast<size_t>(cap_size));
        if (FAILED(config->GetStreamCaps(i, &mt, caps)) || !mt) {
            continue;
        }
        int w = 0;
        int h = 0;
        LONGLONG avg = 0;
        if (get_dimensions(mt, &w, &h, &avg) && w == target_width && h == target_height && mt->subtype == MEDIASUBTYPE_MJPG) {
            delete[] caps;
            return mt;
        }
        free_media_type(mt);
        CoTaskMemFree(mt);
    }
    delete[] caps;
    return nullptr;
}

int wmain(int argc, wchar_t **argv)
{
    const std::wstring needle = argc > 1 ? argv[1] : L"OBSBOT Tiny SE";
    const int seconds = argc > 2 ? _wtoi(argv[2]) : 5;
    const int target_fps = argc > 3 ? _wtoi(argv[3]) : 100;
    const int target_width = argc > 4 ? _wtoi(argv[4]) : 1920;
    const int target_height = argc > 5 ? _wtoi(argv[5]) : 1080;
    const std::wstring grabber_mode = argc > 6 ? argv[6] : L"any";
    const LONGLONG target_avg_time = target_fps > 0 ? 10000000LL / target_fps : 100000;

    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hr)) {
        print_hresult(L"CoInitializeEx", hr);
        return 1;
    }

    IGraphBuilder *graph = nullptr;
    ICaptureGraphBuilder2 *capture_graph = nullptr;
    IBaseFilter *source = nullptr;
    IBaseFilter *grabber_filter = nullptr;
    IBaseFilter *null_renderer = nullptr;
    ISampleGrabber *grabber = nullptr;
    IMediaControl *control = nullptr;
    FrameCounter counter;

    hr = CoCreateInstance(CLSID_FilterGraph, nullptr, CLSCTX_INPROC_SERVER, IID_IGraphBuilder, reinterpret_cast<void **>(&graph));
    print_hresult(L"CoCreateInstance(FilterGraph)", hr);
    if (FAILED(hr)) goto done;

    hr = CoCreateInstance(CLSID_CaptureGraphBuilder2, nullptr, CLSCTX_INPROC_SERVER, IID_ICaptureGraphBuilder2, reinterpret_cast<void **>(&capture_graph));
    print_hresult(L"CoCreateInstance(CaptureGraphBuilder2)", hr);
    if (FAILED(hr)) goto done;

    hr = capture_graph->SetFiltergraph(graph);
    print_hresult(L"SetFiltergraph", hr);
    if (FAILED(hr)) goto done;

    source = find_tiny_filter(needle);
    if (!source) {
        std::wcout << L"Tiny SE source filter not found\n";
        goto done;
    }
    hr = graph->AddFilter(source, L"OBSBOT Tiny SE");
    print_hresult(L"AddFilter(source)", hr);
    if (FAILED(hr)) goto done;

    {
        IAMStreamConfig *config = find_stream_config(source);
        if (!config) {
            std::wcout << L"IAMStreamConfig not found\n";
            goto done;
        }
        AM_MEDIA_TYPE *mt = find_mjpg_type(config, target_width, target_height);
        if (!mt) {
            std::wcout << target_width << L"x" << target_height << L" MJPG media type not found\n";
            safe_release(&config);
            goto done;
        }
        set_avg_time(mt, target_avg_time);
        hr = config->SetFormat(mt);
        std::wcout << L"Requesting " << target_width << L"x" << target_height
                   << L" MJPG @" << target_fps << L"fps avg_time=" << target_avg_time << L"\n";
        print_hresult(L"SetFormat(target MJPG fps)", hr);
        free_media_type(mt);
        CoTaskMemFree(mt);
        safe_release(&config);
        if (FAILED(hr)) goto done;
    }

    hr = CoCreateInstance(CLSID_SampleGrabber, nullptr, CLSCTX_INPROC_SERVER, IID_IBaseFilter, reinterpret_cast<void **>(&grabber_filter));
    print_hresult(L"CoCreateInstance(SampleGrabber filter)", hr);
    if (FAILED(hr)) goto done;

    hr = grabber_filter->QueryInterface(IID_ISampleGrabber, reinterpret_cast<void **>(&grabber));
    print_hresult(L"QueryInterface(ISampleGrabber)", hr);
    if (FAILED(hr)) goto done;

    {
        AM_MEDIA_TYPE mt;
        std::memset(&mt, 0, sizeof(mt));
        mt.majortype = MEDIATYPE_Video;
        if (grabber_mode == L"rgb24") {
            mt.subtype = MEDIASUBTYPE_RGB24;
        } else if (grabber_mode == L"mjpg") {
            mt.subtype = MEDIASUBTYPE_MJPG;
        } else {
            mt.subtype = MEDIASUBTYPE_NULL;
        }
        mt.formattype = FORMAT_None;
        hr = grabber->SetMediaType(&mt);
        std::wcout << L"SampleGrabber mode=" << grabber_mode << L"\n";
        print_hresult(L"SampleGrabber SetMediaType", hr);
        if (FAILED(hr)) goto done;
    }
    grabber->SetBufferSamples(FALSE);
    grabber->SetOneShot(FALSE);
    hr = grabber->SetCallback(&counter, 1);
    print_hresult(L"SampleGrabber SetCallback(BufferCB)", hr);
    if (FAILED(hr)) goto done;

    hr = graph->AddFilter(grabber_filter, L"SampleGrabber");
    print_hresult(L"AddFilter(SampleGrabber)", hr);
    if (FAILED(hr)) goto done;

    hr = CoCreateInstance(CLSID_NullRendererLocal, nullptr, CLSCTX_INPROC_SERVER, IID_IBaseFilter, reinterpret_cast<void **>(&null_renderer));
    print_hresult(L"CoCreateInstance(NullRenderer)", hr);
    if (FAILED(hr)) goto done;

    hr = graph->AddFilter(null_renderer, L"NullRenderer");
    print_hresult(L"AddFilter(NullRenderer)", hr);
    if (FAILED(hr)) goto done;

    hr = capture_graph->RenderStream(&PIN_CATEGORY_CAPTURE, &MEDIATYPE_Video, source, grabber_filter, null_renderer);
    print_hresult(L"RenderStream(capture -> grabber -> null)", hr);
    if (FAILED(hr)) goto done;

    hr = graph->QueryInterface(IID_IMediaControl, reinterpret_cast<void **>(&control));
    print_hresult(L"QueryInterface(IMediaControl)", hr);
    if (FAILED(hr)) goto done;

    hr = control->Run();
    print_hresult(L"MediaControl Run", hr);
    if (FAILED(hr)) goto done;

    std::wcout << L"Capturing for " << seconds << L" seconds...\n";
    std::this_thread::sleep_for(std::chrono::seconds(seconds));
    control->Stop();

    std::wcout << L"Frames: " << counter.frames()
               << L", wall_fps=" << std::fixed << std::setprecision(2) << counter.wall_fps()
               << L", sample_fps=" << counter.sample_fps() << L"\n";

done:
    if (control) control->Stop();
    safe_release(&control);
    safe_release(&grabber);
    safe_release(&null_renderer);
    safe_release(&grabber_filter);
    safe_release(&source);
    safe_release(&capture_graph);
    safe_release(&graph);
    CoUninitialize();
    return 0;
}
