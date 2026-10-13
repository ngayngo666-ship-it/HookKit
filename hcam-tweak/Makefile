TARGET := iphone:clang:latest:16.0
ARCHS := arm64 arm64e
THEOS_PACKAGE_SCHEME ?= rootless

include $(THEOS)/makefiles/common.mk

TWEAK_NAME := VCamInjection VCamOverlay
VCamInjection_FILES := Tweak.xm VCamConfiguration.m VCamFrameProcessor.m VCamOutputProxy.m VCamPhotoProxy.m VCamAudioProxy.m VCamPreviewController.m
VCamInjection_CFLAGS := -fobjc-arc
VCamInjection_FRAMEWORKS := AVFoundation AudioToolbox CoreImage CoreMedia CoreVideo Foundation ImageIO QuartzCore UIKit UniformTypeIdentifiers

VCamOverlay_FILES := OverlayTweak.xm VCamOverlayController.m VCamConfiguration.m Team247OverlayView.swift
VCamOverlay_CFLAGS := -fobjc-arc
VCamOverlay_SWIFTFLAGS := -disable-sandbox
VCamOverlay_FRAMEWORKS := Foundation SwiftUI UIKit UniformTypeIdentifiers

include $(THEOS_MAKE_PATH)/tweak.mk

TOOL_NAME := VCamMediaBridge
VCamMediaBridge_FILES := VCamMediaBridge.m
VCamMediaBridge_CFLAGS := -fobjc-arc
VCamMediaBridge_FRAMEWORKS := AVFoundation Foundation ImageIO QuartzCore
VCamMediaBridge_INSTALL_PATH := /usr/libexec

include $(THEOS_MAKE_PATH)/tool.mk

after-install::
	install.exec "killall -9 SpringBoard 2>/dev/null || true"
