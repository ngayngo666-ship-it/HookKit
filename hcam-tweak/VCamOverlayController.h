#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// Owns the floating bubble and the control panel that live on top of SpringBoard. The
/// implementation builds a pass-through window, self-heals across resprings/unlocks, and hosts
/// the SwiftUI panel supplied by Team247HostingFactory.
@interface VCamOverlayController : NSObject
+ (instancetype)sharedController;
/// Register observers (once) and build/show the overlay. Safe to call repeatedly.
- (void)start;
@end

NS_ASSUME_NONNULL_END
