#import "VCamFrameProcessor.h"
#import "VCamConfiguration.h"
#import <AVFoundation/AVFoundation.h>
#import <CoreImage/CoreImage.h>
#import <ImageIO/ImageIO.h>

@interface VCamFrameProcessor ()
@property (nonatomic, strong) CIContext *context;
@property (nonatomic, strong, nullable) CIImage *staticImage;      // image source
@property (nonatomic, strong, nullable) AVAssetReader *reader;     // video source
@property (nonatomic, strong, nullable) AVAssetReaderTrackOutput *readerOutput;
@property (nonatomic, strong, nullable) NSString *loadedSourcePath;
@property (nonatomic) VCamSourceType loadedSourceType;
@property (nonatomic, strong, nullable) CIImage *lastVideoImage;
@property (nonatomic) dispatch_queue_t queue;
@end

@implementation VCamFrameProcessor

+ (instancetype)sharedProcessor {
    static VCamFrameProcessor *shared;
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{ shared = [[self alloc] init]; });
    return shared;
}

- (instancetype)init {
    if ((self = [super init])) {
        _context = [CIContext contextWithOptions:@{ kCIContextWorkingColorSpace: [NSNull null] }];
        _queue = dispatch_queue_create("com.aech.vcam.frame-processor", DISPATCH_QUEUE_SERIAL);
        __weak typeof(self) weakSelf = self;
        [[VCamConfiguration sharedConfiguration] addChangeObserver:self block:^{ [weakSelf prepareSource]; }];
        [self prepareSource];
    }
    return self;
}

- (BOOL)hasSource {
    VCamConfiguration *config = VCamConfiguration.sharedConfiguration;
    if (config.sourceType == VCamSourceTypeImage) { return self.staticImage != nil; }
    if (config.sourceType == VCamSourceTypeVideo) { return self.reader != nil || self.lastVideoImage != nil; }
    return NO;
}

#pragma mark - Source loading

- (void)prepareSource {
    dispatch_async(self.queue, ^{
        VCamConfiguration *config = VCamConfiguration.sharedConfiguration;
        NSString *path = config.sourceType == VCamSourceTypeImage ? config.selectedImagePath : config.selectedVideoPath;

        if (config.sourceType == VCamSourceTypeRealCamera || path.length == 0) {
            [self tearDownVideo];
            self.staticImage = nil;
            self.loadedSourcePath = nil;
            return;
        }
        if ([path isEqualToString:self.loadedSourcePath] && config.sourceType == self.loadedSourceType) {
            return; // already loaded
        }

        self.loadedSourcePath = path;
        self.loadedSourceType = config.sourceType;
        [self tearDownVideo];
        self.staticImage = nil;

        if (config.sourceType == VCamSourceTypeImage) {
            self.staticImage = [CIImage imageWithContentsOfURL:[NSURL fileURLWithPath:path]];
        } else {
            [self openVideoAtPath:path];
        }
    });
}

- (void)openVideoAtPath:(NSString *)path {
    AVURLAsset *asset = [AVURLAsset URLAssetWithURL:[NSURL fileURLWithPath:path] options:nil];
    AVAssetTrack *track = [asset tracksWithMediaType:AVMediaTypeVideo].firstObject;
    if (!track) { return; }

    NSError *error = nil;
    AVAssetReader *reader = [AVAssetReader assetReaderWithAsset:asset error:&error];
    if (!reader) { return; }

    NSDictionary *settings = @{ (id)kCVPixelBufferPixelFormatTypeKey: @(kCVPixelFormatType_32BGRA) };
    AVAssetReaderTrackOutput *output = [AVAssetReaderTrackOutput assetReaderTrackOutputWithTrack:track outputSettings:settings];
    output.alwaysCopiesSampleData = NO;
    if (![reader canAddOutput:output]) { return; }
    [reader addOutput:output];
    [reader startReading];

    self.reader = reader;
    self.readerOutput = output;
}

- (void)tearDownVideo {
    if (self.reader.status == AVAssetReaderStatusReading) { [self.reader cancelReading]; }
    self.reader = nil;
    self.readerOutput = nil;
}

- (CIImage *)nextVideoImage {
    VCamConfiguration *config = VCamConfiguration.sharedConfiguration;
    if (config.isPaused && self.lastVideoImage) { return self.lastVideoImage; }

    CMSampleBufferRef sample = self.readerOutput ? [self.readerOutput copyNextSampleBuffer] : NULL;
    if (!sample && self.reader) {
        // End of file: loop when enabled, otherwise hold the last frame.
        if (config.isLoopEnabled && self.loadedSourcePath) {
            [self openVideoAtPath:self.loadedSourcePath];
            sample = self.readerOutput ? [self.readerOutput copyNextSampleBuffer] : NULL;
        }
    }
    if (!sample) { return self.lastVideoImage; }

    CVImageBufferRef pixelBuffer = CMSampleBufferGetImageBuffer(sample);
    CIImage *image = pixelBuffer ? [CIImage imageWithCVPixelBuffer:pixelBuffer] : nil;
    if (image) { self.lastVideoImage = image; }
    CFRelease(sample);
    return self.lastVideoImage;
}

#pragma mark - Rendering

- (CIImage *)sourceImage {
    VCamConfiguration *config = VCamConfiguration.sharedConfiguration;
    if (config.sourceType == VCamSourceTypeImage) { return self.staticImage; }
    if (config.sourceType == VCamSourceTypeVideo) { return [self nextVideoImage]; }
    return nil;
}

- (CIImage *)processedImageForSize:(CGSize)size {
    VCamConfiguration *config = VCamConfiguration.sharedConfiguration;
    CIImage *image = [self sourceImage];
    if (!image) { return nil; }

    CGRect extent = image.extent;
    if (CGRectIsEmpty(extent) || size.width <= 0 || size.height <= 0) { return nil; }

    // Aspect-fill the source into the target size, then apply zoom.
    CGFloat zoom = MAX(1.0, config.zoom);
    CGFloat baseScale = MAX(size.width / extent.size.width, size.height / extent.size.height);
    CGFloat scale = baseScale * zoom;
    image = [image imageByApplyingTransform:CGAffineTransformMakeScale(scale, scale)];

    // Mirror horizontally when requested.
    if (config.isMirrored) {
        image = [image imageByApplyingTransform:CGAffineTransformMakeScale(-1, 1)];
    }
    // Rotation (degrees, clockwise in UI → counter-clockwise radians in CI space).
    if (config.rotationDegrees != 0) {
        CGFloat radians = -config.rotationDegrees * M_PI / 180.0;
        image = [image imageByApplyingTransform:CGAffineTransformMakeRotation(radians)];
    }

    // Re-center after the transforms, then apply the user offset (-1…1 of the frame).
    CGRect transformed = image.extent;
    CGFloat dx = (size.width - transformed.size.width) / 2.0 - transformed.origin.x + config.offsetX * size.width / 2.0;
    CGFloat dy = (size.height - transformed.size.height) / 2.0 - transformed.origin.y - config.offsetY * size.height / 2.0;
    image = [image imageByApplyingTransform:CGAffineTransformMakeTranslation(dx, dy)];

    // Optional soft face light (gentle exposure lift).
    if (config.lightEnabled && config.lightIntensity > 0) {
        CIFilter *exposure = [CIFilter filterWithName:@"CIExposureAdjust"];
        [exposure setValue:image forKey:kCIInputImageKey];
        [exposure setValue:@(config.lightIntensity * 1.5) forKey:@"inputEV"];
        if (exposure.outputImage) { image = exposure.outputImage; }
    }

    return [image imageByCroppingToRect:CGRectMake(0, 0, size.width, size.height)];
}

- (CVPixelBufferRef)createPixelBufferForSize:(CGSize)size {
    __block CVPixelBufferRef result = NULL;
    dispatch_sync(self.queue, ^{
        CIImage *image = [self processedImageForSize:size];
        if (!image) { return; }

        NSDictionary *attrs = @{
            (id)kCVPixelBufferCGImageCompatibilityKey: @YES,
            (id)kCVPixelBufferCGBitmapContextCompatibilityKey: @YES,
            (id)kCVPixelBufferIOSurfacePropertiesKey: @{},
        };
        CVPixelBufferRef buffer = NULL;
        CVReturn status = CVPixelBufferCreate(kCFAllocatorDefault, (size_t)size.width, (size_t)size.height,
                                              kCVPixelFormatType_32BGRA, (__bridge CFDictionaryRef)attrs, &buffer);
        if (status != kCVReturnSuccess || !buffer) { return; }

        [self.context render:image toCVPixelBuffer:buffer];
        result = buffer; // retained; caller releases
    });
    return result;
}

- (CMSampleBufferRef)createSampleBufferMatching:(CMSampleBufferRef)templateBuffer {
    if (!templateBuffer) { return NULL; }
    CVImageBufferRef templatePixels = CMSampleBufferGetImageBuffer(templateBuffer);
    if (!templatePixels) { return NULL; }

    size_t width = CVPixelBufferGetWidth(templatePixels);
    size_t height = CVPixelBufferGetHeight(templatePixels);
    CVPixelBufferRef replacement = [self createPixelBufferForSize:CGSizeMake(width, height)];
    if (!replacement) { return NULL; }

    CMSampleTimingInfo timing = {0};
    CMSampleBufferGetSampleTimingInfo(templateBuffer, 0, &timing);

    CMVideoFormatDescriptionRef format = NULL;
    CMVideoFormatDescriptionCreateForImageBuffer(kCFAllocatorDefault, replacement, &format);

    CMSampleBufferRef output = NULL;
    if (format) {
        CMSampleBufferCreateReadyWithImageBuffer(kCFAllocatorDefault, replacement, format, &timing, &output);
        CFRelease(format);
    }
    CVPixelBufferRelease(replacement);
    return output;
}

@end
