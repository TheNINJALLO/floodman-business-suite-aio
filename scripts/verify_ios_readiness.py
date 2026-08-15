#!/usr/bin/env python3
from __future__ import annotations

import json
import plistlib
import struct
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / "apps" / "ios"
APP = IOS / "FloodmanOperations"
PIN = "1f97817a52b916875e50cc6380c0d284072b8ce8"
PROBLEMS: list[str] = []


def require(condition: bool, message: str) -> None:
    if not condition:
        PROBLEMS.append(message)


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def require_tokens(text: str, label: str, tokens: list[str]) -> None:
    for token in tokens:
        require(token in text, f"{label} is missing {token!r}")


require((IOS / "VERSION").read_text(encoding="utf-8").strip() == "0.1.0-alpha03", "iOS VERSION is not 0.1.0-alpha03")

project = read("apps/ios/project.yml")
require_tokens(
    project,
    "project.yml",
    [
        'iOS: "17.0"',
        'SWIFT_VERSION: "5.0"',
        'MARKETING_VERSION: "0.1.0"',
        'CURRENT_PROJECT_VERSION: "3"',
        "PRODUCT_BUNDLE_IDENTIFIER: com.floodman.operations",
        'TARGETED_DEVICE_FAMILY: "1,2"',
        "GENERATE_INFOPLIST_FILE: NO",
        "FloodmanOperations/Resources",
        "FloodmanOperations/Assets.xcassets",
    ],
)
api_setting = next((line.split(":", 1)[1].strip() for line in project.splitlines() if "FLOODMAN_API_BASE_URL:" in line), "")
parsed_api = urlparse(api_setting)
require(
    parsed_api.scheme == "https"
    and bool(parsed_api.hostname)
    and parsed_api.username is None
    and parsed_api.password is None
    and parsed_api.query == ""
    and parsed_api.fragment == ""
    and parsed_api.path.rstrip("/") == "/mobile-api",
    "project.yml FLOODMAN_API_BASE_URL must be HTTPS and end in /mobile-api/",
)

with (APP / "Info.plist").open("rb") as handle:
    info = plistlib.load(handle)
require(info.get("CFBundleDisplayName") == "Floodman Operations", "Info.plist display name changed")
require(info.get("FLOODMAN_API_BASE_URL") == "$(FLOODMAN_API_BASE_URL)", "Info.plist does not consume the API build setting")
ats = info.get("NSAppTransportSecurity") or {}
require(ats.get("NSAllowsArbitraryLoads") is not True, "Info.plist enables arbitrary network loads")
require(ats.get("NSAllowsLocalNetworking") is True, "Info.plist does not allow the loopback RoomFlow server")
for usage in ("NSCameraUsageDescription", "NSMicrophoneUsageDescription", "NSFaceIDUsageDescription"):
    require(bool(info.get(usage)), f"Info.plist is missing {usage}")
require(set(info.get("UISupportedInterfaceOrientations", [])) >= {"UIInterfaceOrientationPortrait", "UIInterfaceOrientationLandscapeLeft", "UIInterfaceOrientationLandscapeRight"}, "iPhone orientations are incomplete")
require(set(info.get("UISupportedInterfaceOrientations~ipad", [])) >= {"UIInterfaceOrientationPortrait", "UIInterfaceOrientationPortraitUpsideDown", "UIInterfaceOrientationLandscapeLeft", "UIInterfaceOrientationLandscapeRight"}, "iPad orientations are incomplete")

icons_root = APP / "Assets.xcassets" / "AppIcon.appiconset"
icons = json.loads((icons_root / "Contents.json").read_text(encoding="utf-8"))
idioms = {str(item.get("idiom")) for item in icons.get("images", [])}
require({"iphone", "ipad", "ios-marketing"} <= idioms, "AppIcon catalog does not cover iPhone, iPad, and App Store marketing")
for item in icons.get("images", []):
    filename = item.get("filename")
    if not filename:
        PROBLEMS.append(f"AppIcon entry has no filename: {item}")
        continue
    path = icons_root / filename
    require(path.is_file(), f"AppIcon file is missing: {filename}")
    if not path.is_file():
        continue
    data = path.read_bytes()
    require(data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24, f"AppIcon is not a valid PNG: {filename}")
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 24:
        continue
    width, height = struct.unpack(">II", data[16:24])
    points = float(str(item.get("size", "0x0")).split("x", 1)[0])
    scale = float(str(item.get("scale", "0x")).removesuffix("x"))
    expected = round(points * scale)
    require((width, height) == (expected, expected), f"AppIcon {filename} is {width}x{height}; expected {expected}x{expected}")

api = read("apps/ios/FloodmanOperations/Networking/APIClient.swift")
require_tokens(
    api,
    "APIClient",
    [
        'private static let appVersion = "0.1.0-alpha03"',
        'candidate.scheme?.lowercased() == "https"',
        'candidate.path.trimmingCharacters(in: CharacterSet(charactersIn: "/")) == "mobile-api"',
        "validateCompatibility()",
        'value["minimum_ios_version"]',
        '"mobile.compatibility.v1"',
        '"roomflow.workspaces.v1"',
        "refreshTask",
        'contentType == "application/pdf"',
        'data.starts(with: Data("%PDF-".utf8))',
        '"app_version":Self.appVersion',
    ],
)
keychain = read("apps/ios/FloodmanOperations/Security/KeychainStore.swift")
require("kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly" in keychain, "Keychain items are not device-bound")
session = read("apps/ios/FloodmanOperations/SessionStore.swift")
require_tokens(session, "SessionStore", ["restoreSession()", "api.validateCompatibility()"])

asset_server = read("apps/ios/FloodmanOperations/RoomFlow/LocalAssetServer.swift")
require_tokens(asset_server, "LocalAssetServer", ['host: "127.0.0.1"', "requiredLocalEndpoint", "standardizedFileURL", "hasPrefix(rootPrefix)", "X-Content-Type-Options: nosniff"])
require_tokens(asset_server, "LocalAssetServer request framing", ["requestData.range", "431 Request Header Fields Too Large"])
roomflow_view = read("apps/ios/FloodmanOperations/RoomFlow/RoomFlowView.swift")
require_tokens(
    roomflow_view,
    "RoomFlowView",
    [
        'accessibilityLabel("Close RoomFlow")',
        "importTask?.cancel()",
        "createTask?.cancel()",
        'Section("Quick start")',
        'LabeledContent("Time zone", value: "Eastern Time (Detroit)")',
        'DisclosureGroup("More company options")',
        'SecureField("Original RoomFlow password", text: $password)',
        "let suppliedPassword = password",
        'password = ""',
        'origin.host == "127.0.0.1" ? .grant : .deny',
        'url.host == "127.0.0.1"',
        "javaScriptCanOpenWindowsAutomatically = false",
        "URLQueryItem(name: \"contact_id\"",
        "URLQueryItem(name: \"workspace_id\"",
    ],
)
require("interactiveDismissDisabled" not in roomflow_view, "RoomFlow sheets can become non-dismissible")

root_view = read("apps/ios/FloodmanOperations/Views/RootView.swift")
require_tokens(
    root_view,
    "iOS app settings",
    [
        'Section("App settings")',
        'LabeledContent("Business time", value: "Eastern Time (Detroit)")',
        'DisclosureGroup("Installer connection details")',
    ],
)

roomflow_bridge = read("apps/ios/FloodmanOperations/Resources/RoomFlow/floodman-ios-bridge.js")
require_tokens(
    roomflow_bridge,
    "iOS RoomFlow bridge",
    [
        "workspaceId: this.activeWorkspace?.id || ''",
        "send('searchCustomers'",
        "send('searchProperties'",
    ],
)

prepare = read("apps/ios/scripts/prepare-roomflow-assets.sh")
require_tokens(prepare, "iOS RoomFlow preparer", ["cost-tests.js", "patch_roomflow_bundle.py", "validate_roomflow_web.py", "floodman-roomflow.json", "-delete"])

simulator = read(".github/workflows/build-ios-simulator.yml")
require_tokens(
    simulator,
    "iOS simulator workflow",
    [
        "macos-26",
        "Xcode_26",
        "xcodegen generate",
        "generic/platform=iOS Simulator",
        "CODE_SIGNING_ALLOWED=NO",
        "verify_ios_readiness.py",
        "validate_roomflow_web.py",
        "SHA256SUMS.txt",
        "if-no-files-found: error",
        "Floodman-Operations-iOS-0.1.0-alpha03-simulator",
    ],
)
testflight = read(".github/workflows/build-ios-testflight.yml")
require_tokens(
    testflight,
    "TestFlight workflow",
    [
        "inputs.confirmation == 'UPLOAD'",
        "Validate required secrets",
        "Require a successful unsigned simulator compile for this commit",
        "CODE_SIGNING_ALLOWED=NO",
        "PROVISIONING_PROFILE_SPECIFIER",
        "--validate-app",
        "--upload-app",
        "Floodman-Operations-iOS-0.1.0-alpha03-TestFlight",
    ],
)

metadata = APP / "Resources" / "RoomFlow" / "floodman-roomflow.json"
if metadata.is_file():
    prepared = json.loads(metadata.read_text(encoding="utf-8"))
    require(prepared.get("base_commit") == PIN, "prepared iOS RoomFlow metadata has the wrong pin")
    require(prepared.get("release") == "4.6.9", "prepared iOS RoomFlow metadata has the wrong Floodman release")
    require(prepared.get("created_by") == "Josh Aldrich", "prepared iOS RoomFlow metadata lost attribution")

if PROBLEMS:
    for problem in PROBLEMS:
        print(f"ERROR: {problem}")
    print(f"iOS readiness failed with {len(PROBLEMS)} problem(s).")
    sys.exit(1)

swift_count = len(list(APP.rglob("*.swift")))
print(f"iOS source readiness verified: {swift_count} Swift files, {len(icons.get('images', []))} icon slots, HTTPS/capability/PDF/keychain/RoomFlow/workflow gates present.")
print("Simulator compilation remains a macOS/Xcode gate.")
