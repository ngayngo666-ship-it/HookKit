#import <AVFoundation/AVFoundation.h>

NS_ASSUME_NONNULL_BEGIN

@interface VCamAudioProxy : NSObject <AVCaptureAudioDataOutputSampleBufferDelegate>
- (instancetype)initWithDelegate:(id<AVCaptureAudioDataOutputSampleBufferDelegate>)delegate;
@property (nonatomic, weak, readonly, nullable) id<AVCaptureAudioDataOutputSampleBufferDelegate> realDelegate;
@end

NS_ASSUME_NONNULL_END
