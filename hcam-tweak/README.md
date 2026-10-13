# HCAMV2 — virtual camera tweak (rootless)

Bộ mã nguồn Theos hoàn chỉnh cho tweak camera ảo: thay luồng camera / ảnh chụp / preview trong các app được chọn bằng một ảnh hoặc video, điều khiển qua một bong bóng nổi trên SpringBoard. Đây là bản dựng lại đầy đủ cấu trúc còn thiếu của mã nguồn trước đó (trước đây chỉ còn `VCamOverlayController.m` và `VCamAudioProxy.h`).

## Cấu trúc

Ba sản phẩm build ra từ một project (xem `Makefile`):

| Sản phẩm | Nạp vào | Việc |
|---|---|---|
| `VCamInjection.dylib` | mọi app UIKit (lọc runtime theo danh sách app) | thay camera/ảnh/preview/âm thanh |
| `VCamOverlay.dylib` | `com.apple.springboard` | bong bóng nổi + bảng điều khiển |
| `VCamMediaBridge` (tool) | chạy nền qua LaunchDaemon | kiểm tra nguồn, báo trạng thái cho app |

### Phần injection (chạy trong app đích)
- `Tweak.xm` — điểm vào: hook `AVCaptureVideoDataOutput`, `AVCaptureAudioDataOutput`, `AVCapturePhotoOutput`, `AVCaptureVideoPreviewLayer`, bọc delegate bằng proxy, tự bỏ qua chính app `com.aech.vcam`.
- `VCamConfiguration.{h,m}` — đọc `configuration.json` dùng chung, tự nạp lại khi có Darwin notification `com.aech.vcam.configuration-changed`, quyết định có active cho từng bundle id không.
- `VCamFrameProcessor.{h,m}` — biến ảnh/video thành pixel buffer khớp kích thước camera; xử lý zoom, xoay, lật, offset, đèn; video có lặp/tạm dừng.
- `VCamOutputProxy`, `VCamPhotoProxy`, `VCamAudioProxy`, `VCamPreviewController` — proxy từng loại output; không active thì cho đi qua nguyên vẹn.

### Phần overlay (chạy trong SpringBoard)
- `OverlayTweak.xm` — gọi `start` khi SpringBoard khởi động xong và sau respring.
- `VCamOverlayController.{h,m}` — cửa sổ pass-through, bong bóng kéo được, tự hồi phục khi đổi scene / khoá máy.
- `Team247OverlayView.swift` — bảng điều khiển SwiftUI + `Team247HostingFactory` mà controller nạp; ghi thẳng vào `configuration.json` và bắn Darwin notification.

### Đóng gói
- `control` — metadata gói `HCAMV2 0.5.0-1`, rootless, phụ thuộc `ellekit`.
- `VCamInjection.plist`, `VCamOverlay.plist` — filter nạp dylib (đã sửa lỗi bong bóng: overlay chỉ lọc đúng `com.apple.springboard`).
- `layout/` — LaunchDaemon cho helper, chỗ đặt `BubbleIcon.jpg`, script `postinst`/`prerm`.

## Build

Cần [Theos](https://theos.dev) và SDK iOS, biến môi trường `$THEOS` đã trỏ đúng:

```bash
cd hcam-tweak
make package THEOS_PACKAGE_SCHEME=rootless FINALPACKAGE=1
```

File `.deb` nằm trong `packages/`. Cài qua Sileo/Zebra hoặc `make install` khi có SSH.

## Phần cần kiểm chứng trên máy thật

Không build/kiểm thử được trong môi trường này (không có Theos/SDK iOS). Các điểm nên thử trên iPhone:
1. Bong bóng hiện sau khi cài + respring (lỗi cũ "bong bóng không xuất hiện").
2. Quyền đọc `/var/mobile/Library/Application Support/VCam` từ trong app đích theo sandbox rootless; nếu bị chặn, cho helper copy config sang chỗ dùng chung dễ đọc hơn.
3. Bộ lọc injection: mặc định nạp mọi app UIKit rồi lọc runtime; thu hẹp `Bundles` trong `VCamInjection.plist` nếu muốn cố định danh sách app.
