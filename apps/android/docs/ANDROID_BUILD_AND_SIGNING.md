# Android build and signing

The included GitHub Actions workflow builds:

```text
Debug APK
Release APK
Release Android App Bundle
SHA-256 checksums
Kotlin compile log
Unit-test report
Android lint report
```

## Repository variables

```text
FLOODMAN_API_BASE_URL
SQUARE_APPLICATION_ID
```

Recommended alpha API value:

```text
https://api.oninetwork.com/mobile-api/
```

## Optional release-signing secrets

```text
FLOODMAN_KEYSTORE_BASE64
FLOODMAN_KEYSTORE_PASSWORD
FLOODMAN_KEY_ALIAS
FLOODMAN_KEY_PASSWORD
```

`FLOODMAN_KEYSTORE_BASE64` is the base64-encoded Android keystore. Do not commit the keystore or passwords.

Without all four signing secrets, the workflow still builds the debug APK. Release outputs may be unsigned and are not appropriate for Google Play submission.
