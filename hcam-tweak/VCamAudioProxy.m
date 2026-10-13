#import "VCamAudioProxy.h"
#import "VCamConfiguration.h"
#import "VCamFrameProcessor.h"

@interface VCamAudioProxy ()
@property (nonatomic, weak) id<AVCaptureAudioDataOutputSampleBufferDelegate> realDelegate;
@end

@implementation VCamAudioProxy

- (instancetype)initWithDelegate:(id<AVCaptureAudioDataOutputSampleBufferDelegate>)delegate {
    if ((self = [super init])) {
        _realDelegate = delegate;
    }
    return self;
}

- (void)captureOutput:(AVCaptureOutput *)output
didOutputSampleBuffer:(CMSampleBufferRef)sampleBuffer
       fromConnection:(AVCaptureConnection *)connection {
    id<AVCaptureAudioDataOutputSampleBufferDelegate> delegate = self.realDelegate;
    if (![delegate respondsToSelector:@selector(captureOutput:didOutputSampleBuffer:fromConnection:)]) { return; }

    // While a photo/video source is injected the live microphone is muted so the host app
    // does not leak real ambient audio over the spoofed footage. Audio is otherwise untouched.
    VCamConfiguration *config = VCamConfiguration.sharedConfiguration;
    BOOL mute = config.isEnabled && config.sourceType != VCamSourceTypeRealCamera;
    if (mute) {
        [self silenceSampleBuffer:sampleBuffer];
    }
    [delegate captureOutput:output didOutputSampleBuffer:sampleBuffer fromConnection:connection];
}

- (void)silenceSampleBuffer:(CMSampleBufferRef)sampleBuffer {
    CMBlockBufferRef blockBuffer = CMSampleBufferGetDataBuffer(sampleBuffer);
    if (!blockBuffer) { return; }
    size_t length = CMBlockBufferGetDataLength(blockBuffer);
    char *zeros = calloc(1, length);
    if (zeros) {
        CMBlockBufferReplaceDataBytes(zeros, blockBuffer, 0, length);
        free(zeros);
    }
}

#pragma mark - Transparent forwarding

- (BOOL)respondsToSelector:(SEL)aSelector {
    if ([super respondsToSelector:aSelector]) { return YES; }
    return [self.realDelegate respondsToSelector:aSelector];
}

- (id)forwardingTargetForSelector:(SEL)aSelector {
    return [self.realDelegate respondsToSelector:aSelector] ? self.realDelegate : nil;
}

@end
