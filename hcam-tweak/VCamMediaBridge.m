#import <Foundation/Foundation.h>
#import <AVFoundation/AVFoundation.h>
#import <notify.h>

// Lightweight helper launched on demand. It reports health to helper-status.json (read by the
// companion app's Diagnostics view) and, when a video source is selected, validates that the
// file is decodable so the app can warn the user early. It intentionally stays small: the real
// frame work happens in-process inside each hooked app via VCamFrameProcessor.

static NSString *const kDirectory = @"/var/mobile/Library/Application Support/VCam";
static NSString *const kDarwinNotification = @"com.aech.vcam.configuration-changed";

static NSString *ConfigPath(void) { return [kDirectory stringByAppendingPathComponent:@"configuration.json"]; }
static NSString *StatusPath(void) { return [kDirectory stringByAppendingPathComponent:@"helper-status.json"]; }

static void WriteStatus(NSString *state, NSString *detail) {
    NSDictionary *status = @{ @"state": state ?: @"unknown",
                              @"detail": detail ?: @"",
                              @"updatedAt": @([[NSDate date] timeIntervalSince1970]) };
    NSData *data = [NSJSONSerialization dataWithJSONObject:status options:0 error:nil];
    [[NSFileManager defaultManager] createDirectoryAtPath:kDirectory withIntermediateDirectories:YES
                                               attributes:@{ NSFilePosixPermissions: @(0755) } error:nil];
    [data writeToFile:StatusPath() atomically:YES];
}

static void ValidateAndReport(void) {
    NSData *data = [NSData dataWithContentsOfFile:ConfigPath()];
    if (!data) { WriteStatus(@"idle", @"No configuration yet"); return; }

    NSDictionary *config = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
    if (![config isKindOfClass:NSDictionary.class]) { WriteStatus(@"error", @"Configuration unreadable"); return; }

    NSString *type = config[@"sourceType"];
    if (![config[@"isEnabled"] boolValue] || [type isEqual:@"realCamera"]) {
        WriteStatus(@"ready", @"Pass-through (real camera)");
        return;
    }
    if ([type isEqual:@"image"]) {
        NSString *path = config[@"selectedImagePath"];
        BOOL ok = path.length && [[NSFileManager defaultManager] fileExistsAtPath:path];
        WriteStatus(ok ? @"ready" : @"error", ok ? @"Image source ready" : @"Image file missing");
        return;
    }
    if ([type isEqual:@"video"]) {
        NSString *path = config[@"selectedVideoPath"];
        if (!path.length || ![[NSFileManager defaultManager] fileExistsAtPath:path]) {
            WriteStatus(@"error", @"Video file missing");
            return;
        }
        AVURLAsset *asset = [AVURLAsset URLAssetWithURL:[NSURL fileURLWithPath:path] options:nil];
        BOOL decodable = [asset tracksWithMediaType:AVMediaTypeVideo].count > 0;
        WriteStatus(decodable ? @"ready" : @"error", decodable ? @"Video source ready" : @"Video has no decodable track");
        return;
    }
    WriteStatus(@"ready", @"Active");
}

int main(int argc, char *argv[]) {
    @autoreleasepool {
        ValidateAndReport();

        int token = 0;
        notify_register_dispatch(kDarwinNotification.UTF8String, &token, dispatch_get_main_queue(), ^(int t) {
            ValidateAndReport();
        });
        // Heartbeat so the app can tell the helper is alive (status is "stale" after 10s).
        dispatch_source_t timer = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0, dispatch_get_main_queue());
        dispatch_source_set_timer(timer, dispatch_time(DISPATCH_TIME_NOW, 0), 5 * NSEC_PER_SEC, NSEC_PER_SEC);
        dispatch_source_set_event_handler(timer, ^{ ValidateAndReport(); });
        dispatch_resume(timer);

        [[NSRunLoop currentRunLoop] run];
    }
    return 0;
}
