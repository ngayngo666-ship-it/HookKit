#import "VCamOutputProxy.h"
#import "VCamConfiguration.h"
#import "VCamFrameProcessor.h"

@interface VCamOutputProxy ()
@property (nonatomic, weak) id<AVCaptureVideoDataOutputSampleBufferDelegate> realDelegate;
@property (nonatomic, copy, nullable) NSString *bundleIdentifier;
@end

@implementation VCamOutputProxy

- (instancetype)initWithDelegate:(id<AVCaptureVideoDataOutputSampleBufferDelegate>)delegate
                          bundle:(NSString *)bundleIdentifier {
    if ((self = [super init])) {
        _realDelegate = delegate;
        _bundleIdentifier = [bundleIdentifier copy];
    }
    return self;
}

- (void)captureOutput:(AVCaptureOutput *)output
didOutputSampleBuffer:(CMSampleBufferRef)sampleBuffer
       fromConnection:(AVCaptureConnection *)connection {
    id<AVCaptureVideoDataOutputSampleBufferDelegate> delegate = self.realDelegate;
    if (![delegate respondsToSelector:@selector(captureOutput:didOutputSampleBuffer:fromConnection:)]) { return; }

    if ([VCamConfiguration.sharedConfiguration isActiveForBundleIdentifier:self.bundleIdentifier]) {
        CMSampleBufferRef replacement = [VCamFrameProcessor.sharedProcessor createSampleBufferMatching:sampleBuffer];
        if (replacement) {
            [delegate captureOutput:output didOutputSampleBuffer:replacement fromConnection:connection];
            CFRelease(replacement);
            return;
        }
    }
    [delegate captureOutput:output didOutputSampleBuffer:sampleBuffer fromConnection:connection];
}

- (void)captureOutput:(AVCaptureOutput *)output
  didDropSampleBuffer:(CMSampleBufferRef)sampleBuffer
       fromConnection:(AVCaptureConnection *)connection {
    id<AVCaptureVideoDataOutputSampleBufferDelegate> delegate = self.realDelegate;
    if ([delegate respondsToSelector:@selector(captureOutput:didDropSampleBuffer:fromConnection:)]) {
        [delegate captureOutput:output didDropSampleBuffer:sampleBuffer fromConnection:connection];
    }
}

#pragma mark - Transparent forwarding for everything else

- (BOOL)respondsToSelector:(SEL)aSelector {
    if ([super respondsToSelector:aSelector]) { return YES; }
    return [self.realDelegate respondsToSelector:aSelector];
}

- (id)forwardingTargetForSelector:(SEL)aSelector {
    return [self.realDelegate respondsToSelector:aSelector] ? self.realDelegate : nil;
}

@end
