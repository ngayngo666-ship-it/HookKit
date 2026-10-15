#import "VCamOverlayController.h"

#import <UIKit/UIKit.h>
#import <objc/message.h>

static NSString *const VCamOverlayReadyPath = @"/var/mobile/Library/Application Support/VCam/overlay-ready";

static BOOL VCamIsDeviceUILocked(void) {
    Class managerClass = NSClassFromString(@"SBLockScreenManager");
    SEL sharedSelector = NSSelectorFromString(@"sharedInstance");
    if (managerClass && [managerClass respondsToSelector:sharedSelector]) {
        id manager = ((id (*)(id, SEL))objc_msgSend)(managerClass, sharedSelector);
        for (NSString *selectorName in @[@"isUILocked", @"isLocked"]) {
            SEL selector = NSSelectorFromString(selectorName);
            if ([manager respondsToSelector:selector]) {
                return ((BOOL (*)(id, SEL))objc_msgSend)(manager, selector);
            }
        }
    }
    return !UIApplication.sharedApplication.isProtectedDataAvailable;
}

static UIImage *VCamBrandImage(void) {
    for (NSString *path in @[
        @"/var/jb/Library/Application Support/team247meta/BubbleIcon.jpg",
        @"/Library/Application Support/team247meta/BubbleIcon.jpg"
    ]) {
        UIImage *image = [UIImage imageWithContentsOfFile:path];
        if (image) return [image imageWithRenderingMode:UIImageRenderingModeAlwaysOriginal];
    }
    return [UIImage systemImageNamed:@"camera.aperture"];
}

@interface VCamPassthroughWindow : UIWindow
@end

@interface VCamOverlayRootViewController : UIViewController
@property (nonatomic, weak) id overlayController;
@end

@interface VCamOverlayController () <UIGestureRecognizerDelegate>
@property (nonatomic, strong) VCamPassthroughWindow *window;
@property (nonatomic, strong) UIButton *floatingButton;
@property (nonatomic, strong) UIViewController *hostingController;
@property (nonatomic) CGPoint floatingPanOrigin;
@property (nonatomic) CGPoint panelPanOrigin;
@property (nonatomic) BOOL panelPositionCustomized;
@property (nonatomic) NSInteger sceneRetryCount;
@property (nonatomic) BOOL observersRegistered;
- (void)layoutOverlayForBounds:(CGRect)bounds;
- (void)refreshVisibility;
- (void)ensureOverlay;
- (void)buildWindowInScene:(UIWindowScene *)scene;
- (UIWindowScene *)activeWindowScene;
@end

@implementation VCamPassthroughWindow
- (UIView *)hitTest:(CGPoint)point withEvent:(UIEvent *)event {
    UIView *hitView = [super hitTest:point withEvent:event];
    return hitView == self.rootViewController.view ? nil : hitView;
}
@end

@implementation VCamOverlayRootViewController
- (void)viewDidLayoutSubviews {
    [super viewDidLayoutSubviews];
    [(VCamOverlayController *)self.overlayController layoutOverlayForBounds:self.view.bounds];
}
- (BOOL)shouldAutorotate { return YES; }
- (UIInterfaceOrientationMask)supportedInterfaceOrientations { return UIInterfaceOrientationMaskAll; }
@end

static void VCamLockStateChanged(
    CFNotificationCenterRef center,
    void *observer,
    CFNotificationName name,
    const void *object,
    CFDictionaryRef userInfo
) {
    dispatch_async(dispatch_get_main_queue(), ^{
        // Repair (rebuild/re-host) as well as re-evaluate visibility: an unlock may follow a
        // SpringBoard relaunch that happened while the device was locked.
        [[VCamOverlayController sharedController] ensureOverlay];
    });
}

@implementation VCamOverlayController

+ (instancetype)sharedController {
    static VCamOverlayController *controller;
    static dispatch_once_t onceToken;
    dispatch_once(&onceToken, ^{ controller = [[self alloc] init]; });
    return controller;
}

- (void)start {
    // Register observers exactly once, independent of whether the window exists yet.
    if (!self.observersRegistered) {
        self.observersRegistered = YES;
        [[NSNotificationCenter defaultCenter] addObserver:self selector:@selector(hidePanel) name:@"Team247OverlayDismiss" object:nil];
        [[NSNotificationCenter defaultCenter] addObserver:self selector:@selector(protectedDataChanged:) name:UIApplicationProtectedDataDidBecomeAvailable object:nil];
        [[NSNotificationCenter defaultCenter] addObserver:self selector:@selector(protectedDataChanged:) name:UIApplicationProtectedDataWillBecomeUnavailable object:nil];
        // Self-heal when SpringBoard rebuilds its scene (e.g. after a jetsam relaunch or unlock).
        [[NSNotificationCenter defaultCenter] addObserver:self selector:@selector(sceneDidActivate:) name:UISceneDidActivateNotification object:nil];
        [[NSNotificationCenter defaultCenter] addObserver:self selector:@selector(sceneDidDisconnect:) name:UISceneDidDisconnectNotification object:nil];
        CFNotificationCenterAddObserver(CFNotificationCenterGetDarwinNotifyCenter(), NULL, VCamLockStateChanged, CFSTR("com.apple.springboard.lockstate"), NULL, CFNotificationSuspensionBehaviorDeliverImmediately);
        CFNotificationCenterAddObserver(CFNotificationCenterGetDarwinNotifyCenter(), NULL, VCamLockStateChanged, CFSTR("com.apple.springboard.lockcomplete"), NULL, CFNotificationSuspensionBehaviorDeliverImmediately);
    }
    [self ensureOverlay];
}

- (UIWindowScene *)activeWindowScene {
    UIWindowScene *inactiveFallback = nil;
    for (UIScene *scene in UIApplication.sharedApplication.connectedScenes) {
        if (![scene isKindOfClass:UIWindowScene.class]) continue;
        UIWindowScene *windowScene = (UIWindowScene *)scene;
        if (windowScene.activationState == UISceneActivationStateForegroundActive) return windowScene;
        if (windowScene.activationState == UISceneActivationStateForegroundInactive && !inactiveFallback) {
            inactiveFallback = windowScene;
        }
    }
    return inactiveFallback;
}

// Idempotent: builds the overlay window if missing, or re-hosts it onto the current
// foreground scene if the previous host scene went away. Safe to call repeatedly.
- (void)ensureOverlay {
    UIWindowScene *scene = [self activeWindowScene];

    // Existing window whose host scene changed or was torn down: move it, don't rebuild.
    if (self.window && scene && self.window.windowScene != scene) {
        self.window.windowScene = scene;
        self.window.frame = UIScreen.mainScreen.bounds;
        [self layoutOverlayForBounds:self.window.bounds];
    }

    if (!self.window) {
        if (!scene) {
            // No usable scene yet (early boot / mid-respring). Keep retrying briefly.
            if (self.sceneRetryCount < 30) {
                self.sceneRetryCount += 1;
                dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.5 * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{ [self ensureOverlay]; });
            }
            return;
        }
        self.sceneRetryCount = 0;
        [self buildWindowInScene:scene];
    }

    [self refreshVisibility];
}

- (void)buildWindowInScene:(UIWindowScene *)scene {
    self.window = scene
        ? [[VCamPassthroughWindow alloc] initWithWindowScene:scene]
        : [[VCamPassthroughWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    self.window.frame = UIScreen.mainScreen.bounds;
    self.window.windowLevel = UIWindowLevelAlert + 1000;
    self.window.backgroundColor = UIColor.clearColor;

    VCamOverlayRootViewController *root = [[VCamOverlayRootViewController alloc] init];
    root.overlayController = self;
    root.view.backgroundColor = UIColor.clearColor;
    self.window.rootViewController = root;

    self.panelPositionCustomized = NO;
    [self buildFloatingButtonInView:root.view];
    [self buildSwiftUIPanelInView:root.view];
    [self layoutOverlayForBounds:self.window.bounds];
    self.hostingController.view.hidden = YES;

    [@"ready" writeToFile:VCamOverlayReadyPath atomically:YES encoding:NSUTF8StringEncoding error:nil];
}

- (void)sceneDidActivate:(NSNotification *)notification {
    self.sceneRetryCount = 0;
    [self ensureOverlay];
}

- (void)sceneDidDisconnect:(NSNotification *)notification {
    // Our host scene is gone; drop the stale window so the next active scene rebuilds cleanly.
    if (self.window && self.window.windowScene == notification.object) {
        self.window.hidden = YES;
        self.window.rootViewController = nil;
        self.window = nil;
        self.floatingButton = nil;
        self.hostingController = nil;
    }
}

- (void)buildFloatingButtonInView:(UIView *)rootView {
    UIButton *button = [UIButton buttonWithType:UIButtonTypeCustom];
    button.backgroundColor = UIColor.blackColor;
    button.layer.cornerRadius = 29;
    button.layer.borderWidth = 2;
    button.layer.borderColor = [UIColor colorWithRed:0.86 green:0.66 blue:0.22 alpha:1].CGColor;
    button.layer.shadowColor = UIColor.blackColor.CGColor;
    button.layer.shadowOpacity = 0.4;
    button.layer.shadowRadius = 8;
    button.layer.shadowOffset = CGSizeMake(0, 4);
    [button setImage:VCamBrandImage() forState:UIControlStateNormal];
    button.imageView.contentMode = UIViewContentModeScaleAspectFill;
    button.clipsToBounds = YES;
    button.accessibilityLabel = @"Open team247meta controls";
    [button addTarget:self action:@selector(showPanel) forControlEvents:UIControlEventTouchUpInside];
    [button addGestureRecognizer:[[UIPanGestureRecognizer alloc] initWithTarget:self action:@selector(handleFloatingPan:)]];
    [rootView addSubview:button];
    self.floatingButton = button;
}

- (void)buildSwiftUIPanelInView:(UIView *)rootView {
    Class factoryClass = NSClassFromString(@"Team247HostingFactory");
    SEL selector = NSSelectorFromString(@"makeViewController");
    if (!factoryClass || ![factoryClass respondsToSelector:selector]) return;
    UIViewController *controller = ((UIViewController *(*)(id, SEL))objc_msgSend)(factoryClass, selector);
    if (!controller) return;
    [self.window.rootViewController addChildViewController:controller];
    controller.view.backgroundColor = UIColor.clearColor;
    UIPanGestureRecognizer *panelPan = [[UIPanGestureRecognizer alloc] initWithTarget:self action:@selector(handlePanelPan:)];
    panelPan.cancelsTouchesInView = NO;
    panelPan.delegate = self;
    [controller.view addGestureRecognizer:panelPan];
    [rootView addSubview:controller.view];
    [controller didMoveToParentViewController:self.window.rootViewController];
    self.hostingController = controller;
}

- (void)layoutOverlayForBounds:(CGRect)bounds {
    if (CGRectIsEmpty(bounds)) return;
    UIEdgeInsets insets = self.window.safeAreaInsets;
    CGFloat availableWidth = CGRectGetWidth(bounds) - insets.left - insets.right;
    CGFloat availableHeight = CGRectGetHeight(bounds) - insets.top - insets.bottom;
    CGFloat size = availableHeight < 500 ? 50 : 58;
    self.floatingButton.frame = CGRectMake(CGRectGetWidth(bounds) - insets.right - size - 10,
                                           insets.top + MAX(10, (availableHeight - size) * 0.68), size, size);
    self.floatingButton.layer.cornerRadius = size / 2;

    CGFloat scale = MIN(1, MIN((availableWidth - 16) / 252.0, (availableHeight - 16) / 318.0));
    scale = MAX(0.68, scale);
    UIView *panel = self.hostingController.view;
    panel.bounds = CGRectMake(0, 0, 252, 318);
    panel.transform = CGAffineTransformMakeScale(scale, scale);
    CGFloat panelWidth = 252 * scale;
    CGFloat panelHeight = 318 * scale;
    if (!self.panelPositionCustomized) {
        panel.center = CGPointMake(
            CGRectGetWidth(bounds) - insets.right - panelWidth / 2 - 10,
            CGRectGetHeight(bounds) - insets.bottom - panelHeight / 2 - 10
        );
    } else {
        panel.center = CGPointMake(
            MAX(insets.left + panelWidth / 2 + 5, MIN(CGRectGetWidth(bounds) - insets.right - panelWidth / 2 - 5, panel.center.x)),
            MAX(insets.top + panelHeight / 2 + 5, MIN(CGRectGetHeight(bounds) - insets.bottom - panelHeight / 2 - 5, panel.center.y))
        );
    }
}

- (void)showPanel {
    if (!self.hostingController) return;
    self.hostingController.view.hidden = NO;
    self.floatingButton.hidden = YES;
}

- (void)hidePanel {
    self.hostingController.view.hidden = YES;
    self.floatingButton.hidden = NO;
}

- (void)refreshVisibility {
    BOOL locked = VCamIsDeviceUILocked();
    self.window.hidden = locked;
    if (locked) [self hidePanel];
}

- (void)protectedDataChanged:(NSNotification *)notification { [self ensureOverlay]; }

- (void)handleFloatingPan:(UIPanGestureRecognizer *)gesture {
    UIView *view = self.floatingButton;
    UIView *container = view.superview;
    if (gesture.state == UIGestureRecognizerStateBegan) self.floatingPanOrigin = view.center;
    CGPoint translation = [gesture translationInView:container];
    CGPoint center = CGPointMake(self.floatingPanOrigin.x + translation.x, self.floatingPanOrigin.y + translation.y);
    UIEdgeInsets insets = container.safeAreaInsets;
    CGFloat half = CGRectGetWidth(view.bounds) / 2;
    center.x = MAX(insets.left + half + 6, MIN(CGRectGetWidth(container.bounds) - insets.right - half - 6, center.x));
    center.y = MAX(insets.top + half + 6, MIN(CGRectGetHeight(container.bounds) - insets.bottom - half - 6, center.y));
    view.center = center;
}

- (void)handlePanelPan:(UIPanGestureRecognizer *)gesture {
    UIView *view = self.hostingController.view;
    UIView *container = view.superview;
    if (gesture.state == UIGestureRecognizerStateBegan) {
        self.panelPanOrigin = view.center;
        self.panelPositionCustomized = YES;
    }
    CGPoint translation = [gesture translationInView:container];
    CGPoint center = CGPointMake(self.panelPanOrigin.x + translation.x, self.panelPanOrigin.y + translation.y);
    UIEdgeInsets insets = container.safeAreaInsets;
    CGFloat halfWidth = CGRectGetWidth(view.frame) / 2;
    CGFloat halfHeight = CGRectGetHeight(view.frame) / 2;
    center.x = MAX(insets.left + halfWidth + 5, MIN(CGRectGetWidth(container.bounds) - insets.right - halfWidth - 5, center.x));
    center.y = MAX(insets.top + halfHeight + 5, MIN(CGRectGetHeight(container.bounds) - insets.bottom - halfHeight - 5, center.y));
    view.center = center;
}

- (BOOL)gestureRecognizer:(UIGestureRecognizer *)gestureRecognizer shouldReceiveTouch:(UITouch *)touch {
    if (gestureRecognizer.view == self.hostingController.view) {
        CGPoint point = [touch locationInView:self.hostingController.view];
        return point.y <= 58;
    }
    return YES;
}

@end
