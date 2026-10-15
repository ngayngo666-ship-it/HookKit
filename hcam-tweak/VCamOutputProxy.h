#import <AVFoundation/AVFoundation.h>

NS_ASSUME_NONNULL_BEGIN

/// Wraps the app's real AVCaptureVideoDataOutput delegate. Every delivered frame is swapped
/// for a rendered replacement while VCam is active; all other delegate calls pass straight
/// through so the host app behaves exactly as before.
@interface VCamOutputProxy : NSObject <AVCaptureVideoDataOutputSampleBufferDelegate>
- (instancetype)initWithDelegate:(id<AVCaptureVideoDataOutputSampleBufferDelegate>)delegate
                           bundle:(nullable NSString *)bundleIdentifier;
@property (nonatomic, weak, readonly, nullable) id<AVCaptureVideoDataOutputSampleBufferDelegate> realDelegate;
@end

NS_ASSUME_NONNULL_END
