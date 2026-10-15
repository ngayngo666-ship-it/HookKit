#import <AVFoundation/AVFoundation.h>

NS_ASSUME_NONNULL_BEGIN

/// Wraps the app's AVCapturePhotoCaptureDelegate so a still capture returns the rendered
/// replacement image instead of the live sensor frame while VCam is active.
API_AVAILABLE(ios(10.0))
@interface VCamPhotoProxy : NSObject <AVCapturePhotoCaptureDelegate>
- (instancetype)initWithDelegate:(id<AVCapturePhotoCaptureDelegate>)delegate
                          bundle:(nullable NSString *)bundleIdentifier;
@property (nonatomic, weak, readonly, nullable) id<AVCapturePhotoCaptureDelegate> realDelegate;
@end

NS_ASSUME_NONNULL_END
