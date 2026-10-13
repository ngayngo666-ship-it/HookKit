#import "VCamPreviewController.h"
#import "VCamConfiguration.h"
#import "VCamFrameProcessor.h"
#import <CoreImage/CoreImage.h>
#import <UIKit/UIKit.h>

@interface VCamPreviewController ()
@property (nonatomic, weak) AVCaptureVideoPreviewLayer *previewLayer;
@property (nonatomic, strong) CALayer *displayLayer;
@property (nonatomic, strong, nullable) CADisplayLink *displayLink;
@property (nonatomic, copy, nullable) NSString *bundleIdentifier;
@property (nonatomic, strong) CIContext *context;
@end

@implementation VCamPreviewController

- (instancetype)initWithPreviewLayer:(AVCaptureVideoPreviewLayer *)previewLayer
                              bundle:(NSString *)bundleIdentifier {
    if ((self = [super init])) {
        _previewLayer = previewLayer;
        _bundleIdentifier = [bundleIdentifier copy];
        _context = [CIContext context];
        _displayLayer = [CALayer layer];
        _displayLayer.contentsGravity = kCAGravityResizeAspectFill;
        _displayLayer.masksToBounds = YES;
        [previewLayer addSublayer:_displayLayer];

        _displayLink = [CADisplayLink displayLinkWithTarget:self selector:@selector(tick)];
        _displayLink.preferredFramesPerSecond = 30;
        [_displayLink addToRunLoop:NSRunLoop.mainRunLoop forMode:NSRunLoopCommonModes];

        __weak typeof(self) weakSelf = self;
        [VCamConfiguration.sharedConfiguration addChangeObserver:self block:^{ [weakSelf tick]; }];
    }
    return self;
}

- (void)tick {
    AVCaptureVideoPreviewLayer *preview = self.previewLayer;
    if (!preview) { [self invalidate]; return; }

    BOOL active = [VCamConfiguration.sharedConfiguration isActiveForBundleIdentifier:self.bundleIdentifier]
               && VCamFrameProcessor.sharedProcessor.hasSource;
    self.displayLayer.hidden = !active;
    if (!active) { return; }

    CGRect bounds = preview.bounds;
    if (CGRectIsEmpty(bounds)) { return; }
    self.displayLayer.frame = bounds;

    CGFloat scale = preview.contentsScale > 0 ? preview.contentsScale : UIScreen.mainScreen.scale;
    CGSize pixelSize = CGSizeMake(bounds.size.width * scale, bounds.size.height * scale);
    CVPixelBufferRef buffer = [VCamFrameProcessor.sharedProcessor createPixelBufferForSize:pixelSize];
    if (!buffer) { return; }

    CIImage *image = [CIImage imageWithCVPixelBuffer:buffer];
    CGImageRef cgImage = [self.context createCGImage:image fromRect:image.extent];
    if (cgImage) {
        self.displayLayer.contents = (__bridge_transfer id)cgImage;
    }
    CVPixelBufferRelease(buffer);
}

- (void)invalidate {
    [self.displayLink invalidate];
    self.displayLink = nil;
    [self.displayLayer removeFromSuperlayer];
    [VCamConfiguration.sharedConfiguration removeChangeObserver:self];
}

- (void)dealloc {
    [self invalidate];
}

@end
