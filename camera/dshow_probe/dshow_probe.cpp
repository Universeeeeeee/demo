#define NOMINMAX

#include <dshow.h>
#include <dvdmedia.h>
#include <ks.h>
#include <ksmedia.h>
#include <windows.h>

#include <algorithm>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>

template <class T>
void safe_release(T **ptr)
{
    if (ptr && *ptr) {
        (*ptr)->Release();
        *ptr = nullptr;
    }
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

std::wstring guid_to_string(const GUID &guid)
{
    LPOLESTR raw = nullptr;
    if (FAILED(StringFromCLSID(guid, &raw)) || raw == nullptr) {
        return L"";
    }
    std::wstring text(raw);
    CoTaskMemFree(raw);
    return text;
}

std::wstring subtype_name(const GUID &subtype)
{
    if (subtype == MEDIASUBTYPE_MJPG) return L"MJPG";
    if (subtype == MEDIASUBTYPE_YUY2) return L"YUY2";
    if (subtype == MEDIASUBTYPE_NV12) return L"NV12";
    if (subtype == MEDIASUBTYPE_RGB24) return L"RGB24";
    if (subtype == MEDIASUBTYPE_RGB32) return L"RGB32";
    return guid_to_string(subtype);
}

double fps_from_avg_time(LONGLONG avg_time)
{
    if (avg_time <= 0) {
        return 0.0;
    }
    return 10000000.0 / static_cast<double>(avg_time);
}

void print_hresult(const wchar_t *label, HRESULT hr)
{
    std::wcout << L"  " << label << L": hr=0x" << std::hex << std::setw(8)
               << std::setfill(L'0') << static_cast<unsigned long>(hr)
               << std::dec << std::setfill(L' ') << L"\n";
}

struct FormatInfo {
    int width = 0;
    int height = 0;
    LONGLONG avg_time = 0;
};

bool get_format_info(AM_MEDIA_TYPE *mt, FormatInfo *out)
{
    if (!mt || !out || !mt->pbFormat) {
        return false;
    }
    if (mt->formattype == FORMAT_VideoInfo) {
        auto *vih = reinterpret_cast<VIDEOINFOHEADER *>(mt->pbFormat);
        out->width = vih->bmiHeader.biWidth;
        out->height = std::abs(vih->bmiHeader.biHeight);
        out->avg_time = vih->AvgTimePerFrame;
        return true;
    }
    if (mt->formattype == FORMAT_VideoInfo2) {
        auto *vih = reinterpret_cast<VIDEOINFOHEADER2 *>(mt->pbFormat);
        out->width = vih->bmiHeader.biWidth;
        out->height = std::abs(vih->bmiHeader.biHeight);
        out->avg_time = vih->AvgTimePerFrame;
        return true;
    }
    return false;
}

bool set_format_avg_time(AM_MEDIA_TYPE *mt, LONGLONG avg_time)
{
    if (!mt || !mt->pbFormat) {
        return false;
    }
    if (mt->formattype == FORMAT_VideoInfo) {
        auto *vih = reinterpret_cast<VIDEOINFOHEADER *>(mt->pbFormat);
        vih->AvgTimePerFrame = avg_time;
        return true;
    }
    if (mt->formattype == FORMAT_VideoInfo2) {
        auto *vih = reinterpret_cast<VIDEOINFOHEADER2 *>(mt->pbFormat);
        vih->AvgTimePerFrame = avg_time;
        return true;
    }
    return false;
}

AM_MEDIA_TYPE *clone_media_type(const AM_MEDIA_TYPE *src)
{
    if (!src) {
        return nullptr;
    }
    auto *dst = reinterpret_cast<AM_MEDIA_TYPE *>(CoTaskMemAlloc(sizeof(AM_MEDIA_TYPE)));
    if (!dst) {
        return nullptr;
    }
    *dst = *src;
    if (src->cbFormat > 0 && src->pbFormat) {
        dst->pbFormat = reinterpret_cast<BYTE *>(CoTaskMemAlloc(src->cbFormat));
        if (!dst->pbFormat) {
            CoTaskMemFree(dst);
            return nullptr;
        }
        std::memcpy(dst->pbFormat, src->pbFormat, src->cbFormat);
    }
    if (dst->pUnk) {
        dst->pUnk->AddRef();
    }
    return dst;
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

void probe_filter(IBaseFilter *filter)
{
    IAMStreamConfig *config = find_stream_config(filter);
    if (!config) {
        std::wcout << L"  no IAMStreamConfig output pin\n";
        return;
    }

    int count = 0;
    int cap_size = 0;
    HRESULT hr = config->GetNumberOfCapabilities(&count, &cap_size);
    print_hresult(L"GetNumberOfCapabilities", hr);
    std::wcout << L"  count=" << count << L" cap_size=" << cap_size << L"\n";
    if (FAILED(hr) || count <= 0 || cap_size <= 0) {
        safe_release(&config);
        return;
    }

    std::vector<unsigned char> caps(static_cast<size_t>(cap_size));
    AM_MEDIA_TYPE *target = nullptr;
    AM_MEDIA_TYPE *base_1080_mjpg = nullptr;
    for (int i = 0; i < count; ++i) {
        AM_MEDIA_TYPE *mt = nullptr;
        std::fill(caps.begin(), caps.end(), 0);
        hr = config->GetStreamCaps(i, &mt, reinterpret_cast<BYTE *>(caps.data()));
        if (FAILED(hr) || !mt) {
            continue;
        }

        FormatInfo info;
        if (get_format_info(mt, &info)) {
            const int width = info.width;
            const int height = info.height;
            const double fps = fps_from_avg_time(info.avg_time);
            std::wcout << L"  [" << std::setw(2) << i << L"] " << width << L"x" << height
                       << L" @ " << std::fixed << std::setprecision(2) << fps
                       << L"fps subtype=" << subtype_name(mt->subtype)
                       << L" formattype="
                       << (mt->formattype == FORMAT_VideoInfo2 ? L"VideoInfo2" : L"VideoInfo")
                       << L" avg_time=" << info.avg_time << L"\n";

            if (cap_size >= static_cast<int>(sizeof(VIDEO_STREAM_CONFIG_CAPS))) {
                auto *vcaps = reinterpret_cast<VIDEO_STREAM_CONFIG_CAPS *>(caps.data());
                std::wcout << L"       caps input=" << vcaps->InputSize.cx << L"x" << vcaps->InputSize.cy
                           << L" min_out=" << vcaps->MinOutputSize.cx << L"x" << vcaps->MinOutputSize.cy
                           << L" max_out=" << vcaps->MaxOutputSize.cx << L"x" << vcaps->MaxOutputSize.cy
                           << L" min_interval=" << vcaps->MinFrameInterval
                           << L" (" << std::fixed << std::setprecision(2)
                           << fps_from_avg_time(vcaps->MinFrameInterval) << L"fps max)"
                           << L" max_interval=" << vcaps->MaxFrameInterval
                           << L" (" << fps_from_avg_time(vcaps->MaxFrameInterval) << L"fps min)"
                           << L"\n";
            }

            if (!base_1080_mjpg && width == 1920 && height == 1080 && mt->subtype == MEDIASUBTYPE_MJPG) {
                base_1080_mjpg = clone_media_type(mt);
            }

            if (!target && width == 1920 && height == 1080 && mt->subtype == MEDIASUBTYPE_MJPG
                && fps >= 95.0 && fps <= 105.0) {
                target = mt;
                continue;
            }
        }

        free_media_type(mt);
        CoTaskMemFree(mt);
    }

    AM_MEDIA_TYPE *forced_100 = target ? clone_media_type(target) : clone_media_type(base_1080_mjpg);
    if (forced_100) {
        set_format_avg_time(forced_100, 100000);  // 10,000,000 / 100fps
        std::wcout << L"\n  trying forced SetFormat for 1920x1080 MJPG @ 100fps (AvgTimePerFrame=100000)\n";
        hr = config->SetFormat(forced_100);
        print_hresult(L"SetFormat", hr);

        AM_MEDIA_TYPE *current = nullptr;
        hr = config->GetFormat(&current);
        print_hresult(L"GetFormat(after SetFormat)", hr);
        FormatInfo info;
        if (SUCCEEDED(hr) && get_format_info(current, &info)) {
            std::wcout << L"  current=" << info.width << L"x"
                       << info.height << L" @ "
                       << std::fixed << std::setprecision(2)
                       << fps_from_avg_time(info.avg_time)
                       << L"fps subtype=" << subtype_name(current->subtype) << L"\n";
        }
        if (current) {
            free_media_type(current);
            CoTaskMemFree(current);
        }
        free_media_type(forced_100);
        CoTaskMemFree(forced_100);
    } else {
        std::wcout << L"\n  no 1920x1080 MJPG base media type available for forced SetFormat\n";
    }

    if (target) {
        free_media_type(target);
        CoTaskMemFree(target);
    }
    if (base_1080_mjpg) {
        free_media_type(base_1080_mjpg);
        CoTaskMemFree(base_1080_mjpg);
    }

    safe_release(&config);
}

int wmain(int argc, wchar_t **argv)
{
    std::wstring needle = argc > 1 ? argv[1] : L"OBSBOT Tiny SE";

    HRESULT hr = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(hr)) {
        print_hresult(L"CoInitializeEx", hr);
        return 1;
    }

    ICreateDevEnum *dev_enum = nullptr;
    hr = CoCreateInstance(
        CLSID_SystemDeviceEnum, nullptr, CLSCTX_INPROC_SERVER,
        IID_ICreateDevEnum, reinterpret_cast<void **>(&dev_enum));
    if (FAILED(hr) || !dev_enum) {
        print_hresult(L"CoCreateInstance(SystemDeviceEnum)", hr);
        CoUninitialize();
        return 1;
    }

    IEnumMoniker *enum_moniker = nullptr;
    hr = dev_enum->CreateClassEnumerator(CLSID_VideoInputDeviceCategory, &enum_moniker, 0);
    if (hr != S_OK || !enum_moniker) {
        print_hresult(L"CreateClassEnumerator(VideoInputDeviceCategory)", hr);
        safe_release(&dev_enum);
        CoUninitialize();
        return 1;
    }

    int index = 0;
    IMoniker *moniker = nullptr;
    while (enum_moniker->Next(1, &moniker, nullptr) == S_OK) {
        IPropertyBag *bag = nullptr;
        std::wstring friendly;
        std::wstring path;
        if (SUCCEEDED(moniker->BindToStorage(nullptr, nullptr, IID_IPropertyBag, reinterpret_cast<void **>(&bag)))) {
            friendly = read_bstr_property(bag, L"FriendlyName");
            path = read_bstr_property(bag, L"DevicePath");
            safe_release(&bag);
        }

        ++index;
        if (friendly.find(needle) != std::wstring::npos || path.find(needle) != std::wstring::npos) {
            std::wcout << L"\nMatched device: " << friendly << L"\n";
            std::wcout << L"  path=" << path << L"\n";
            IBaseFilter *filter = nullptr;
            hr = moniker->BindToObject(nullptr, nullptr, IID_IBaseFilter, reinterpret_cast<void **>(&filter));
            print_hresult(L"BindToObject(IBaseFilter)", hr);
            if (SUCCEEDED(hr) && filter) {
                probe_filter(filter);
                safe_release(&filter);
            }
        }

        safe_release(&moniker);
    }

    safe_release(&enum_moniker);
    safe_release(&dev_enum);
    CoUninitialize();
    return 0;
}
