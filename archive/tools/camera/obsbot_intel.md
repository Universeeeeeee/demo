# OBSBOT Tiny SE / Meet SE 逆向情报

## 设备信息

| 项 | Meet SE | Tiny SE |
|----|---------|---------|
| USB VID/PID | `VID_3564&PID_FEFF` | `VID_3564&PID_FEFF`（相同） |
| SDK 识别名 | OBSBOT Meet SE StreamCamera | OBSBOT Tiny SE StreamCamera |
| Tiny SE SN | — | `RMOWCYHA081RCB` |
| Tiny SE 固件 | — | `6.4.3.4` |
| Tiny SE 产品类型枚举值 | — | `12` (ObsbotProdTinySE) |
| USB 描述符路径 | `\\?\USB#VID_3564&PID_FEFF&MI_00#...` | 相同 |
| UVC 扩展单元 | `IKsControl` 可用，`extension_prop success` | 相同 |
| UVC 节点 | IKsControl(2), IID_IVideoProcAmp(1), IID_ICameraControl(0) | 相同 |

## OpenCV 直接抓取结果

| 项 | Meet SE | Tiny SE |
|----|---------|---------|
| 默认分辨率 | 1280×720 | 未成功（卡死） |
| 默认帧率 | ~30fps | 未成功（卡死） |
| `cap.set(FOURCC, MJPG)` | 设置不生效，actual FOURCC 乱码 | **OpenCV 卡死** |
| `cap.set(FOURCC, YUY2)` | 同上 | **OpenCV 卡死** |
| `cap.set(FPS, 100)` | 不生效，实测 ~30fps | 未成功 |
| `cap.set(WIDTH/HEIGHT, 1920/1080)` | 不生效，回落 720p | 未成功 |
| DSHOW 后端 | 能打开但不接受参数协商 | 能打开但设置 FOURCC 就 hang |
| MSMF 后端 | 未测试 | 未测试 |

**结论：OBSBOT 的 UVC 实现不接受标准 `cap.set()` 格式协商。参数控制走私有协议（UVC 扩展单元 / MTP 命令），OpenCV 只能被动接收默认流。**

## SDK 概况

- **名称**: libdev v2.1.0（OBSBOT Device SDK）
- **位置**: `camera/sdk/libdev_v2.1.0_8/windows/win64-release/`
- **核心文件**: `libdev.dll` + `libdev.lib` + `libdev.pdb`
- **依赖**: `w32-pthreads.dll`（同目录）
- **头文件**: `camera/sdk/libdev_v2.1.0_8/include/dev/dev.hpp`（约 5000 行）
- **示例**: `camera/sdk/libdev_v2.1.0_8/OBSBOT_Sample/main.cpp`

### SDK 能力

**SDK 是纯控制 SDK，没有任何帧回调接口。** 搜索了 `onFrame`/`frameCallback`/`getFrame`/`videoCallback` 等全部零命中。

- **能做的**: 设备发现、查询/设置分辨率帧率、机内录制控制、云台/AI/画质参数
- **不能做的**: 提供视频帧、实时预览

正确架构应为：
```
SDK (libdev.dll) → 设分辨率/帧率/格式（走 UVC 扩展单元或 MTP 命令）
OpenCV           → 抓帧 + 显示 + 录制（走标准 UVC 管道）
```

### DLL 导出表

- **总导出数**: 571 个符号
- **类型**: **全部是 C++ mangled names（`?` 前缀）**，无 `extern "C"` 入口
- **0 个仅-ordinal 符号**，全部有名

## ctypes 调用结果

### 已验证可调用的函数

| 函数 | mangled name | 返回 | 参数 | 验证 |
|------|-------------|------|------|------|
| `Devices::get()` | `?get@Devices@@SAAEAV1@XZ` | `Devices&`(指针) | 无 | ✅ 成功，返回有效指针 |
| `Devices::getDevNum()` | `?getDevNum@Devices@@QEAA_KXZ` | `size_t` | `this` only | ✅ 成功，返回 1 |
| `Devices::close()` | `?close@Devices@@QEAAXXZ` | void | `this` only | ✅ 成功 |

**规律：仅 `this` 参数的简单成员函数可调。涉及 STL 类型（`std::string`/`std::shared_ptr`/`std::list`/`std::vector`）的参数或返回值的函数全部失败。**

### 已验证崩溃的函数

| 调用 | crash 地址 | 诊断 |
|------|-----------|------|
| `getDevList(list_buf, devices)` | `0x3188` | 固定的类成员偏移，疑似内部数据结构未初始化或线程竞争 |
| `getDevBySn(devices, sn_str)` | `0x19` / `0x1A` / `0xe06d7363` | C++ 异常！最后一种 crash 是 MSVC 异常码，说明函数抛了 `throw` |
| `getDevBySn` (WINFUNCTYPE) | `0xe06d7363` | 确认是 C++ 异常，`std::string` SSO 布局可能不完全匹配 |

### 核心障碍

1. **无 `extern "C"` 导出** — ctypes 只能调 mangled names，但 C++ ABI 不完全稳定
2. **`std::string` 跨 ABI 传递** — 32 字节 SSO 布局正确构造了，但仍抛异常，说明 MSVC STL 版本不完全匹配
3. **`std::shared_ptr` 返回** — 16 字节，MSVC x64 走 RAX:RDX，ctypes 只读 RAX 拿到 Device* 是可行的，但调不到那一步就崩了
4. **`std::list` 返回** — 24 字节，需要 hidden pointer（RCX），但崩在类内部偏移 `0x3188`

## 关键导出符号速查

### 设备管理 (Devices)
```
?get@Devices@@SAAEAV1@XZ                              → Devices& get()
?getDevNum@Devices@@QEAA_KXZ                           → size_t getDevNum()
?close@Devices@@QEAAXXZ                                → void close()
?getDevList@Devices@@QEAA?AV?$list@V?$shared_ptr@...   → list<shared_ptr<Device>> getDevList()
?getDevBySn@Devices@@QEAA?AV?$shared_ptr@VDevice@...   → shared_ptr<Device> getDevBySn(const string&)
?getDevByName@Devices@@QEAA?AV?$shared_ptr@VDevice@... → shared_ptr<Device> getDevByName(const string&)
?getDevByUuid@Devices@@QEAA?AV?$shared_ptr@VDevice@... → shared_ptr<Device> getDevByUuid(array&)
?containDev@Devices@@QEAA_NAEAV?$array@E$0BI@@std@@@Z  → bool containDev(array&)
?setDevChangedCallback@Devices@@QEAAXV?$function@...   → void setDevChangedCallback(function)
```

### 设备信息 (Device)
```
?devSn@Device@@QEAA?AV?$basic_string@...                → string devSn()
?devName@Device@@QEAAAEBV?$basic_string@...             → const string& devName()
?devVersion@Device@@QEAA?AV?$basic_string@...           → string devVersion()
?devMode@Device@@QEAA?AW4DevMode@1@XZ                   → DevMode devMode()
?productType@Device@@QEAA?AW4ObsbotProductType@@XZ      → ObsbotProductType productType()
?videoFormatInfo@Device@@QEAA?AV?$vector@VVideoForm...  → vector<VideoFormatInfo> videoFormatInfo()
?cameraStatus@Device@@QEAA?ATCameraStatus@1@XZ          → CameraStatus cameraStatus()
```

### 录制/编码控制 (Device)
```
?cameraSetRecordEncodeParamR@Device@@QEAAHAEBUDevMed... → int setRecordEncodeParam(DevMediaEncodeParam&, bool night)
?cameraGetRecordEncodeParamR@Device@@QEAAHAEAUDevMed... → int getRecordEncodeParam(DevMediaEncodeParam&, bool night)
?cameraSetRecordResolutionR@Device@@QEAAHW4DevVideoR... → int setRecordResolution(DevVideoResType)
?cameraSetVideoRecordR@Device@@QEAAHII@Z                → int setVideoRecord(uint32_t op, uint32_t param)
?cameraSetMediaOperateParamR@Device@@QEAAHW4DevMedia... → int setMediaOperateParam(stream_id, action)
?cameraGetMediaOperateParamR@Device@@QEAAHW4DevMedia... → int getMediaOperateParam(stream_id, &action)
?cameraGetConfigRange@Device@@QEAAHAEBV?$function@...   → int getConfigRange(callback, param, data, size)
```

### 状态回调 (Device)
```
?setDevStatusCallbackFunc@Device@@QEAAXV?$function@...  → void setDevStatusCallbackFunc(function)
?enableDevStatusCallback@Device@@QEAAX_N@Z              → void enableDevStatusCallback(bool)
```

## 已尝试的路径及结果

| 路径 | 方式 | 结果 |
|------|------|------|
| 纯 ctypes + CFUNCTYPE 调 Devices::get | `ctypes.CFUNCTYPE(c_void_p)(addr)()` | ✅ 成功 |
| 纯 ctypes + CFUNCTYPE 调 getDevNum | `CFUNCTYPE(c_size_t, c_void_p)(addr)(devices)` | ✅ 成功 |
| getattr(dll, name) + 设置 restype/argtypes | `fn.restype=c_void_p; fn.argtypes=[...]` | ❌ "int too long to convert" |
| CFUNCTYPE 调 getDevList | hidden ptr (RCX=retbuf, RDX=this) | ❌ access violation 0x3188 |
| CFUNCTYPE 调 getDevBySn | RAX=Device*, RCX=this, RDX=&string | ❌ C++ exception 0xe06d7363 |
| WINFUNCTYPE 替代 CFUNCTYPE | 同上 | 结果完全一样（x64 无区别） |
| getDevList 不传 hidden ptr | `CFUNCTYPE(c_void_p, c_void_p)(devices)` | ❌ access violation WRITING 0x0 |
| pefile 解析导出表 | fallback after dumpbin | ✅ 571 个符号 |
| OBSBOT_Sample.exe | SDK 自带示例（需交互输入） | 未尝试，可在 cmd 中 pipe 命令 |

## 剩余可能的攻击路径

### 路径 1: C wrapper DLL（最可靠）
写一个极简 C++ DLL，`extern "C"` 桥接：
```c
extern "C" {
    void* obsbot_get_devices();
    int   obsbot_get_device_count(void* mgr);
    void* obsbot_get_device_by_sn(void* mgr, const char* sn);
    int   obsbot_get_video_formats(void* dev, int* widths, int* heights, int* fps, int max);
    int   obsbot_set_fps(void* dev, int fps);
    void  obsbot_release_devices(void* mgr);
}
```
编译：`cl /LD wrapper.cpp /I<include> libdev.lib w32-pthreads.lib`
需要 MSVC Build Tools（`winget install Microsoft.VisualStudio.2022.BuildTools`）

### 路径 2: comtypes 直调 UVC 扩展单元
SDK 日志显示 `IKsControl` + `extension_prop success`。OBSBOT 通过 UVC XU（扩展单元）发私有控制命令。用 Python `comtypes` 直接获取 DirectShow filter 的 `IKsControl` 接口，逆向 XU 命令（GUID、property ID、数据结构）。参考 UVC 规范 + OBSBOT SDK 的 `sendMsgSync` 日志模式。

### 路径 3: MTP 模式
SDK 定义 `DevUSBModeMtp = 4`。如果 100fps 仅在 MTP 模式下可用，需要：
1. SDK 切换到 MTP 模式
2. 使用 Windows MTP API (`IPortableDevice`) 或 libmtp 读取 MTP 流
3. 或直接用 SDK 的 `cameraSetMediaOperateParamR` 控制 MTP 流

### 路径 4: 测试 MSMF 后端
当前只试了 DSHOW。OBSBOT 在 MSMF 后端可能有不同行为（MX Brio 就是用 MSMF 才解锁了 60fps）。值得一试。

## Python 环境

- Python: `D:/conda/envs/dayu/python.exe` (64-bit)
- OpenCV: 可用，DSHOW/MSMF 后端都支持
- ctypes: 可用
- pefile: 已安装
- MSVC 编译器: **无**（`cl` / `g++` / `clang++` 均未找到）

## 已有脚本

| 文件 | 用途 |
|------|------|
| `camera/explore_opencv.py` | OpenCV UVC 勘查（枚举+实测帧率+超时保护） |
| `camera/explore_sdk.py` | SDK 勘查（DLL 加载+导出表+chain 调用+三态判定） |
| `camera/diag_sdk.py` | SDK 诊断（全导出表 dump+关键词搜索） |
| `camera/try_sdk.py` | 直调 Devices::get/getDevNum/getDevList |
| `camera/try_sdk2.py` | 改 RAX:RDX 返回的 getDevBySn |
| `camera/try_sdk3.py` | argtypes 显式声明版 |
