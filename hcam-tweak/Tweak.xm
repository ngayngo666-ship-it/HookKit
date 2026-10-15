#import "VCamConfiguration.h"
#import "VCamFrameProcessor.h"
#import "VCamOutputProxy.h"
#import "VCamPhotoProxy.h"
#import "VCamAudioProxy.h"
#import "VCamPreviewController.h"
#import <AVFoundation/AVFoundation.h>
#import <objc/runtime.h>

// This dylib is injected broadly (see VCamInjection.plist) and gates itself at runtime to the
// apps the user picked in the control panel. All it does is wrap the capture delegates so the
// camera feed, still photos, microphone and on-screen preview can be swapped for the chosen
// image/video. When VCam is off or set to the real camera, every hook is a pure pass-through.

static NSString *VCamHostBundleIdentifier(void) {
    static NSString *bundle;
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{ bundle = NSBundle.mainBundle.bundleIdentifier ?: @""; });
    return bundle;
}

%hook AVCaptureVideoDataOutput

- (void)setSampleBufferDelegate:(id<AVCaptureVideoDataOutputSampleBufferDelegate>)delegate
                          queue:(dispatch_queue_t)queue {
    if (delegate && ![delegate isKindOfClass:VCamOutputProxy.class]) {
        VCamOutputProxy *proxy = [[VCamOutputProxy alloc] initWithDelegate:delegate bundle:VCamHostBundleIdentifier()];
        objc_setAssociatedObject(self, _cmd, proxy, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
        %orig(proxy, queue);
        return;
    }
    %orig(delegate, queue);
}

%end

%hook AVCaptureAudioDataOutput

- (void)setSampleBufferDelegate:(id<AVCaptureAudioDataOutputSampleBufferDelegate>)delegate
                          queue:(dispatch_queue_t)queue {
    if (delegate && ![delegate isKindOfClass:VCamAudioProxy.class]) {
        VCamAudioProxy *proxy = [[VCamAudioProxy alloc] initWithDelegate:delegate];
        objc_setAssociatedObject(self, _cmd, proxy, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
        %orig(proxy, queue);
        return;
    }
    %orig(delegate, queue);
}

%end

%hook AVCapturePhotoOutput

- (void)capturePhotoWithSettings:(AVCapturePhotoSettings *)settings
                        delegate:(id<AVCapturePhotoCaptureDelegate>)delegate {
    if (@available(iOS 11.0, *)) {
        if (delegate && ![delegate isKindOfClass:VCamPhotoProxy.class]) {
            VCamPhotoProxy *proxy = [[VCamPhotoProxy alloc] initWithDelegate:delegate bundle:VCamHostBundleIdentifier()];
            objc_setAssociatedObject(settings, "VCamPhotoProxy", proxy, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
            %orig(settings, proxy);
            return;
        }
    }
    %orig(settings, delegate);
}

%end

%hook AVCaptureVideoPreviewLayer

- (void)layoutSublayers {
    %orig;
    if (!objc_getAssociatedObject(self, "VCamPreviewController")) {
        VCamPreviewController *controller = [[VCamPreviewController alloc] initWithPreviewLayer:self
                                                                                        bundle:VCamHostBundleIdentifier()];
        objc_setAssociatedObject(self, "VCamPreviewController", controller, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
    }
}

%end

%ctor {
    NSString *bundle = VCamHostBundleIdentifier();
    if ([bundle isEqualToString:@"com.aech.vcam"]) { return; } // never hook the companion app itself
    // Warm the shared singletons so the first capture frame is ready to be swapped.
    [VCamConfiguration sharedConfiguration];
    [VCamFrameProcessor sharedProcessor];
    %init;
}
