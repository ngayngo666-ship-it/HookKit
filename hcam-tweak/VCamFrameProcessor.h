#import <Foundation/Foundation.h>
#import <CoreMedia/CoreMedia.h>
#import <CoreVideo/CoreVideo.h>

NS_ASSUME_NONNULL_BEGIN

/// Turns the configured image/video source into pixel buffers that match the real camera
/// feed. One shared processor serves every hooked capture output in the host process.
@interface VCamFrameProcessor : NSObject

@property (class, nonatomic, readonly) VCamFrameProcessor *sharedProcessor;

/// YES when a usable replacement source is loaded for the current configuration.
@property (nonatomic, readonly) BOOL hasSource;

/// Render a replacement frame sized to @c size. Returns a retained pixel buffer the caller
/// must release, or NULL when no source is ready. @c size is normally the real buffer size.
- (nullable CVPixelBufferRef)createPixelBufferForSize:(CGSize)size CF_RETURNS_RETAINED;

/// Build a sample buffer that reuses @c templateBuffer's format and timing but carries a
/// freshly rendered replacement image. Returns NULL when no source is ready.
- (nullable CMSampleBufferRef)createSampleBufferMatching:(CMSampleBufferRef)templateBuffer CF_RETURNS_RETAINED;

@end

NS_ASSUME_NONNULL_END
