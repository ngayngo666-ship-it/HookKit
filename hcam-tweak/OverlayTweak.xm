#import "VCamOverlayController.h"
#import <UIKit/UIKit.h>

// Loaded only inside SpringBoard (see VCamOverlay.plist). It brings up the floating bubble
// once SpringBoard has finished launching; the controller then keeps the bubble alive across
// resprings, scene changes and lock/unlock on its own.

%hook SpringBoard

- (void)applicationDidFinishLaunching:(id)application {
    %orig;
    dispatch_async(dispatch_get_main_queue(), ^{
        [[VCamOverlayController sharedController] start];
    });
}

%end

%ctor {
    // Fallback for the case where the dylib loads after SpringBoard already launched
    // (e.g. a tweak respring): start on the next main-queue turn. start is idempotent.
    dispatch_async(dispatch_get_main_queue(), ^{
        [[VCamOverlayController sharedController] start];
    });
}
