#import "VCamConfiguration.h"
#import <notify.h>

static NSString *const VCamDarwinNotification = @"com.aech.vcam.configuration-changed";
static NSString *const VCamCompanionBundleIdentifier = @"com.aech.vcam";

// The companion app writes here. A rootless install keeps the same absolute path so
// both the app and the injected tweak agree on where the shared state lives.
static NSString *const VCamPrimaryDirectory = @"/var/mobile/Library/Application Support/VCam";

@interface VCamConfiguration ()
@property (nonatomic, copy) NSString *sharedDirectoryPath;
@property (nonatomic) VCamSourceType sourceType;
@property (nonatomic, copy, nullable) NSString *selectedVideoPath;
@property (nonatomic, copy, nullable) NSString *selectedImagePath;
@property (nonatomic) BOOL isEnabled;
@property (nonatomic) BOOL isPaused;
@property (nonatomic) BOOL isLoopEnabled;
@property (nonatomic) double playbackSpeed;
@property (nonatomic) double rotationDegrees;
@property (nonatomic) BOOL isMirrored;
@property (nonatomic) double zoom;
@property (nonatomic) double offsetX;
@property (nonatomic) double offsetY;
@property (nonatomic) BOOL lightEnabled;
@property (nonatomic) double lightIntensity;
@property (nonatomic, copy) NSArray<NSString *> *enabledApplications;
@property (nonatomic, strong) NSMapTable<id, void (^)(void)> *observers;
@end

static void VCamConfigurationChanged(CFNotificationCenterRef center, void *observer,
                                     CFNotificationName name, const void *object,
                                     CFDictionaryRef userInfo) {
    dispatch_async(dispatch_get_main_queue(), ^{
        [[VCamConfiguration sharedConfiguration] reload];
    });
}

@implementation VCamConfiguration

+ (instancetype)sharedConfiguration {
    static VCamConfiguration *shared;
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{ shared = [[self alloc] init]; });
    return shared;
}

- (instancetype)init {
    if ((self = [super init])) {
        _sharedDirectoryPath = VCamPrimaryDirectory;
        _playbackSpeed = 1.0;
        _isLoopEnabled = YES;
        _zoom = 1.0;
        _lightIntensity = 0.5;
        _enabledApplications = @[];
        _observers = [NSMapTable weakToStrongObjectsMapTable];
        [self reload];
        CFNotificationCenterAddObserver(CFNotificationCenterGetDarwinNotifyCenter(),
                                        (__bridge const void *)self,
                                        VCamConfigurationChanged,
                                        (__bridge CFStringRef)VCamDarwinNotification,
                                        NULL,
                                        CFNotificationSuspensionBehaviorDeliverImmediately);
    }
    return self;
}

- (NSString *)configurationPath {
    return [self.sharedDirectoryPath stringByAppendingPathComponent:@"configuration.json"];
}

- (void)reload {
    NSData *data = [NSData dataWithContentsOfFile:[self configurationPath]];
    if (!data) { return; }

    NSDictionary *root = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
    if (![root isKindOfClass:NSDictionary.class]) { return; }

    self.isEnabled = [root[@"isEnabled"] boolValue];
    self.sourceType = [self sourceTypeFromString:root[@"sourceType"]];
    self.selectedVideoPath = [root[@"selectedVideoPath"] isKindOfClass:NSString.class] ? root[@"selectedVideoPath"] : nil;
    self.selectedImagePath = [root[@"selectedImagePath"] isKindOfClass:NSString.class] ? root[@"selectedImagePath"] : nil;
    self.isPaused = [root[@"isPaused"] boolValue];
    self.isLoopEnabled = root[@"isLoopEnabled"] ? [root[@"isLoopEnabled"] boolValue] : YES;
    self.playbackSpeed = root[@"playbackSpeed"] ? [root[@"playbackSpeed"] doubleValue] : 1.0;
    self.rotationDegrees = [root[@"rotationDegrees"] doubleValue];
    self.isMirrored = [root[@"isMirrored"] boolValue];
    self.zoom = root[@"zoom"] ? [root[@"zoom"] doubleValue] : 1.0;
    self.offsetX = [root[@"offsetX"] doubleValue];
    self.offsetY = [root[@"offsetY"] doubleValue];
    self.lightEnabled = [root[@"lightEnabled"] boolValue];
    self.lightIntensity = root[@"lightIntensity"] ? [root[@"lightIntensity"] doubleValue] : 0.5;

    NSMutableArray<NSString *> *apps = [NSMutableArray array];
    for (id entry in (([root[@"enabledApplications"] isKindOfClass:NSArray.class]) ? root[@"enabledApplications"] : @[])) {
        if ([entry isKindOfClass:NSString.class] && [(NSString *)entry length]) {
            [apps addObject:entry];
        }
    }
    self.enabledApplications = apps;

    [self notifyObservers];
}

- (VCamSourceType)sourceTypeFromString:(id)value {
    if ([value isEqual:@"video"]) { return VCamSourceTypeVideo; }
    if ([value isEqual:@"image"]) { return VCamSourceTypeImage; }
    return VCamSourceTypeRealCamera;
}

- (BOOL)isActiveForBundleIdentifier:(NSString *)bundleIdentifier {
    if (!self.isEnabled) { return NO; }
    if (self.sourceType == VCamSourceTypeRealCamera) { return NO; }
    if ([bundleIdentifier isEqualToString:VCamCompanionBundleIdentifier]) { return NO; }
    if (self.enabledApplications.count == 0) { return YES; }
    return bundleIdentifier != nil && [self.enabledApplications containsObject:bundleIdentifier];
}

- (void)addChangeObserver:(id)owner block:(void (^)(void))block {
    if (!owner || !block) { return; }
    @synchronized (self.observers) { [self.observers setObject:[block copy] forKey:owner]; }
}

- (void)removeChangeObserver:(id)owner {
    if (!owner) { return; }
    @synchronized (self.observers) { [self.observers removeObjectForKey:owner]; }
}

- (void)notifyObservers {
    NSArray<void (^)(void)> *blocks;
    @synchronized (self.observers) { blocks = self.observers.objectEnumerator.allObjects; }
    dispatch_async(dispatch_get_main_queue(), ^{
        for (void (^block)(void) in blocks) { block(); }
    });
}

@end
