#import "VCamPhotoProxy.h"
#import "VCamConfiguration.h"
#import "VCamFrameProcessor.h"
#import <CoreImage/CoreImage.h>
#import <ImageIO/ImageIO.h>
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>

@interface VCamPhotoProxy ()
@property (nonatomic, weak) id<AVCapturePhotoCaptureDelegate> realDelegate;
@property (nonatomic, copy, nullable) NSString *bundleIdentifier;
@end

@implementation VCamPhotoProxy

- (instancetype)initWithDelegate:(id<AVCapturePhotoCaptureDelegate>)delegate
                          bundle:(NSString *)bundleIdentifier {
    if ((self = [super init])) {
        _realDelegate = delegate;
        _bundleIdentifier = [bundleIdentifier copy];
    }
    return self;
}

- (BOOL)shouldReplace {
    return [VCamConfiguration.sharedConfiguration isActiveForBundleIdentifier:self.bundleIdentifier]
        && VCamFrameProcessor.sharedProcessor.hasSource;
}

// Render the current source at a typical still size; most apps re-encode from this.
- (nullable CGImageRef)replacementCGImage CF_RETURNS_RETAINED {
    CVPixelBufferRef buffer = [VCamFrameProcessor.sharedProcessor createPixelBufferForSize:CGSizeMake(1080, 1920)];
    if (!buffer) { return NULL; }
    CIImage *image = [CIImage imageWithCVPixelBuffer:buffer];
    CIContext *context = [CIContext context];
    CGImageRef cgImage = [context createCGImage:image fromRect:image.extent];
    CVPixelBufferRelease(buffer);
    return cgImage;
}

- (nullable NSData *)replacementJPEGData {
    CGImageRef cgImage = [self replacementCGImage];
    if (!cgImage) { return nil; }

    NSMutableData *data = [NSMutableData data];
    CGImageDestinationRef destination = CGImageDestinationCreateWithData((__bridge CFMutableDataRef)data,
                                                                         (__bridge CFStringRef)UTTypeJPEG.identifier, 1, NULL);
    NSData *result = nil;
    if (destination) {
        CGImageDestinationAddImage(destination, cgImage, (__bridge CFDictionaryRef)@{ (id)kCGImageDestinationLossyCompressionQuality: @0.92 });
        if (CGImageDestinationFinalize(destination)) { result = [data copy]; }
        CFRelease(destination);
    }
    CGImageRelease(cgImage);
    return result;
}

- (void)captureOutput:(AVCapturePhotoOutput *)output
didFinishProcessingPhoto:(AVCapturePhoto *)photo
                error:(NSError *)error API_AVAILABLE(ios(11.0)) {
    id<AVCapturePhotoCaptureDelegate> delegate = self.realDelegate;
    if (![delegate respondsToSelector:_cmd]) { return; }

    if (!error && [self shouldReplace]) {
        NSData *jpeg = [self replacementJPEGData];
        if (jpeg) {
            // Re-wrap our JPEG as an AVCapturePhoto so the app's pipeline stays intact.
            SEL sel = NSSelectorFromString(@"photoWithData:");
            if ([AVCapturePhoto respondsToSelector:sel]) {
                AVCapturePhoto *(*maker)(id, SEL, NSData *) = (void *)[AVCapturePhoto methodForSelector:sel];
                AVCapturePhoto *replacement = maker ? maker(AVCapturePhoto.class, sel, jpeg) : nil;
                if (replacement) { photo = replacement; }
            }
        }
    }
    [delegate captureOutput:output didFinishProcessingPhoto:photo error:error];
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
