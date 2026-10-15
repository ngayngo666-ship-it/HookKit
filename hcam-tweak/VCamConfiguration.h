#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>

NS_ASSUME_NONNULL_BEGIN

typedef NS_ENUM(NSInteger, VCamSourceType) {
    VCamSourceTypeRealCamera = 0,
    VCamSourceTypeVideo,
    VCamSourceTypeImage,
};

/// Reads the configuration.json that the companion app (com.aech.vcam) writes to the
/// shared VCam support directory, and keeps itself up to date by listening for the
/// "com.aech.vcam.configuration-changed" Darwin notification. One shared instance is
/// used by every injected copy of the tweak as well as by the SpringBoard overlay.
@interface VCamConfiguration : NSObject

@property (class, nonatomic, readonly) VCamConfiguration *sharedConfiguration;

/// Absolute path of the shared support directory, e.g. the parent of configuration.json.
@property (nonatomic, readonly) NSString *sharedDirectoryPath;

@property (nonatomic, readonly) BOOL isEnabled;
@property (nonatomic, readonly) VCamSourceType sourceType;
@property (nonatomic, readonly, nullable) NSString *selectedVideoPath;
@property (nonatomic, readonly, nullable) NSString *selectedImagePath;
@property (nonatomic, readonly) BOOL isPaused;
@property (nonatomic, readonly) BOOL isLoopEnabled;
@property (nonatomic, readonly) double playbackSpeed;
@property (nonatomic, readonly) double rotationDegrees;
@property (nonatomic, readonly) BOOL isMirrored;
@property (nonatomic, readonly) double zoom;
@property (nonatomic, readonly) double offsetX;
@property (nonatomic, readonly) double offsetY;
@property (nonatomic, readonly) BOOL lightEnabled;
@property (nonatomic, readonly) double lightIntensity;
@property (nonatomic, readonly) NSArray<NSString *> *enabledApplications;

/// YES when VCam is enabled and the given bundle id is in the allow-list (an empty
/// allow-list means "every app"). The companion app itself is never spoofed.
- (BOOL)isActiveForBundleIdentifier:(nullable NSString *)bundleIdentifier;

/// Force an immediate reload from disk (normally driven by the Darwin notification).
- (void)reload;

/// Register a block that runs on the main queue whenever the configuration changes.
- (void)addChangeObserver:(id)owner block:(void (^)(void))block;
- (void)removeChangeObserver:(id)owner;

@end

NS_ASSUME_NONNULL_END
