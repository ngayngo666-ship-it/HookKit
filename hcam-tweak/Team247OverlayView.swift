import SwiftUI
import UIKit

// MARK: - Shared configuration bridge

/// Reads and writes the same configuration.json the companion app uses, then fires the
/// "com.aech.vcam.configuration-changed" Darwin notification so every injected app reloads
/// immediately. Running inside SpringBoard, this is how the floating panel drives VCam.
final class Team247ConfigStore: ObservableObject {
    enum SourceType: String, Codable { case realCamera, video, image }
    enum MediaKind: String, Codable { case image, video }

    struct MediaSlot: Codable, Identifiable, Equatable {
        let id: Int
        let kind: MediaKind
        let path: String
    }

    private struct Shared: Codable {
        var isEnabled = false
        var sourceType = SourceType.realCamera
        var selectedVideoPath: String?
        var selectedImagePath: String?
        var isPaused = false
        var isLoopEnabled = true
        var playbackSpeed = 1.0
        var rotationDegrees: Double?
        var isMirrored: Bool?
        var zoom: Double?
        var offsetX: Double?
        var offsetY: Double?
        var lightEnabled: Bool?
        var lightIntensity: Double?
        var enabledApplications: [String]?
        var mediaSlots: [MediaSlot]?
    }

    @Published var isEnabled = false
    @Published var sourceType: SourceType = .realCamera
    @Published var isPaused = false
    @Published var zoom = 1.0
    @Published var rotationDegrees = 0.0
    @Published var isMirrored = false
    @Published var offsetX = 0.0
    @Published var offsetY = 0.0
    @Published var lightEnabled = false
    @Published var lightIntensity = 0.5
    @Published var mediaSlots: [MediaSlot] = []
    @Published private(set) var selectedVideoPath: String?
    @Published private(set) var selectedImagePath: String?

    private let directory = URL(fileURLWithPath: "/var/mobile/Library/Application Support/VCam", isDirectory: true)
    private var configURL: URL { directory.appendingPathComponent("configuration.json") }
    private let notificationName = "com.aech.vcam.configuration-changed" as CFString

    init() { load() }

    func load() {
        guard let data = try? Data(contentsOf: configURL),
              let shared = try? JSONDecoder().decode(Shared.self, from: data) else { return }
        isEnabled = shared.isEnabled
        sourceType = shared.sourceType
        isPaused = shared.isPaused
        zoom = shared.zoom ?? 1
        rotationDegrees = shared.rotationDegrees ?? 0
        isMirrored = shared.isMirrored ?? false
        offsetX = shared.offsetX ?? 0
        offsetY = shared.offsetY ?? 0
        lightEnabled = shared.lightEnabled ?? false
        lightIntensity = shared.lightIntensity ?? 0.5
        mediaSlots = (shared.mediaSlots ?? []).filter { FileManager.default.fileExists(atPath: $0.path) }
        selectedVideoPath = shared.selectedVideoPath
        selectedImagePath = shared.selectedImagePath
    }

    func save() {
        var shared = (try? JSONDecoder().decode(Shared.self, from: Data(contentsOf: configURL))) ?? Shared()
        shared.isEnabled = isEnabled
        shared.sourceType = sourceType
        shared.isPaused = isPaused
        shared.zoom = zoom
        shared.rotationDegrees = rotationDegrees
        shared.isMirrored = isMirrored
        shared.offsetX = offsetX
        shared.offsetY = offsetY
        shared.lightEnabled = lightEnabled
        shared.lightIntensity = lightIntensity
        shared.selectedVideoPath = selectedVideoPath
        shared.selectedImagePath = selectedImagePath
        shared.mediaSlots = mediaSlots

        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
                                                    attributes: [.posixPermissions: 0o755])
            let data = try JSONEncoder().encode(shared)
            try data.write(to: configURL, options: .atomic)
            CFNotificationCenterPostNotification(CFNotificationCenterGetDarwinNotifyCenter(),
                                                 CFNotificationName(notificationName), nil, nil, true)
        } catch {
            // The companion app owns the directory; a failed write just leaves the last value.
        }
    }

    func useRealCamera() { sourceType = .realCamera; isPaused = false; save() }

    func useSlot(_ slot: MediaSlot) {
        switch slot.kind {
        case .image: selectedImagePath = slot.path; sourceType = .image
        case .video: selectedVideoPath = slot.path; sourceType = .video
        }
        isPaused = false
        save()
    }
}

// MARK: - Panel UI

struct Team247OverlayView: View {
    @ObservedObject var store: Team247ConfigStore
    @State private var tab = 0

    var body: some View {
        VStack(spacing: 14) {
            header
            Picker("", selection: $tab) {
                Text("Điều khiển").tag(0)
                Text("Nguồn").tag(1)
                Text("Ánh sáng").tag(2)
            }
            .pickerStyle(.segmented)

            switch tab {
            case 1: sourceView
            case 2: lightView
            default: controlView
            }
        }
        .padding(14)
        .frame(width: 252)
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 24))
        .onAppear { store.load() }
    }

    private var header: some View {
        HStack {
            Image(systemName: "camera.aperture").font(.headline)
            Text("team247meta").font(.subheadline.bold())
            Spacer()
            Button { NotificationCenter.default.post(name: Notification.Name("Team247OverlayDismiss"), object: nil) }
                label: { Image(systemName: "xmark.circle.fill").foregroundStyle(.secondary) }
        }
    }

    private var controlView: some View {
        VStack(spacing: 12) {
            Button {
                store.isEnabled.toggle(); store.save()
            } label: {
                Text(store.isEnabled ? "Tắt VCam" : "Bật VCam").frame(maxWidth: .infinity).padding(8)
            }
            .buttonStyle(.borderedProminent)
            .tint(store.isEnabled ? .red : .green)

            HStack {
                Button("↻") { store.rotationDegrees = (store.rotationDegrees + 90).truncatingRemainder(dividingBy: 360); store.save() }
                Button(store.isMirrored ? "↔︎ ✓" : "↔︎") { store.isMirrored.toggle(); store.save() }
            }.buttonStyle(.bordered)

            HStack {
                Button("−") { store.zoom = max(1, store.zoom - 0.1); store.save() }
                Text(String(format: "%.1fx", store.zoom)).frame(width: 64)
                Button("+") { store.zoom = min(8, store.zoom + 0.1); store.save() }
            }.font(.title3)

            Button(store.isPaused ? "▶︎ Tiếp" : "⏸ Dừng") {
                store.isPaused.toggle(); store.save()
            }.buttonStyle(.bordered).disabled(store.sourceType != .video)
        }
    }

    private var sourceView: some View {
        VStack(spacing: 12) {
            Button("Camera thật") { store.useRealCamera() }
                .buttonStyle(.borderedProminent)
                .tint(store.sourceType == .realCamera ? .blue : .gray)
            if store.mediaSlots.isEmpty {
                Text("Chưa có ảnh/video.\nThêm trong app VCam.")
                    .font(.caption).multilineTextAlignment(.center).foregroundStyle(.secondary)
            } else {
                LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 3), spacing: 8) {
                    ForEach(store.mediaSlots) { slot in
                        Button("\(slot.id)") { store.useSlot(slot) }
                            .frame(maxWidth: .infinity).padding(8)
                            .background(.white.opacity(0.12)).clipShape(RoundedRectangle(cornerRadius: 12))
                    }
                }
            }
        }
    }

    private var lightView: some View {
        VStack(alignment: .leading, spacing: 14) {
            Toggle("Đèn khuôn mặt", isOn: Binding(get: { store.lightEnabled },
                                                   set: { store.lightEnabled = $0; store.save() }))
            Text("Cường độ").font(.caption)
            Slider(value: Binding(get: { store.lightIntensity },
                                  set: { store.lightIntensity = $0 }),
                   in: 0...1) { editing in if !editing { store.save() } }
        }
    }
}

// MARK: - ObjC factory used by VCamOverlayController

@objc(Team247HostingFactory)
final class Team247HostingFactory: NSObject {
    @objc static func makeViewController() -> UIViewController {
        let controller = UIHostingController(rootView: Team247OverlayView(store: Team247ConfigStore()))
        controller.view.backgroundColor = .clear
        return controller
    }
}
