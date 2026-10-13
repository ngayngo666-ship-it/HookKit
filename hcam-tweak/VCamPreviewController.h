#import <AVFoundation/AVFoundation.h>
#import <QuartzCore/QuartzCore.h>

NS_ASSUME_NONNULL_BEGIN

/// Drives the on-screen preview so what the user sees matches the spoofed frames. Attaches a
/// display layer on top of the app's AVCaptureVideoPreviewLayer and feeds it rendered frames
/// via a CADisplayLink while VCam is active, removing itself when VCam is off.
@interface VCamPreviewController : NSObject
- (instancetype)initWithPreviewLayer:(AVCaptureVideoPreviewLayer *)previewLayer
                              bundle:(nullable NSString *)bundleIdentifier;
- (void)invalidate;
@end

NS_ASSUME_NONNULL_END
