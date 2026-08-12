# Apple build

The simulator workflow requires only a new GitHub repository and the source ZIP. A physical-device/TestFlight build requires Apple Developer Program membership, an App Store Connect app record for `com.floodman.operations`, Team ID, App Store Connect API key ID, issuer ID, and the `.p8` private key.


## Alpha 02 compiler corrections

- Corrected `LocalAssetServer` optional binding reported by Xcode 26.
- Restricted the bundled RoomFlow HTTP listener to loopback and added path traversal checks.
- Read `UIDevice.current.name` through `MainActor` so the source remains ready for Swift 6 language mode.
- Replaced deprecated localized interpolation of dictionary `Any` values with explicit display strings.
