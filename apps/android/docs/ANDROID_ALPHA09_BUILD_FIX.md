# Android alpha09 build correction

GitHub Actions run `85215872112` reached Kotlin compilation, unit tests, and Android lint. Kotlin compilation and the unit test task passed. Lint stopped on one API 36 predictive-back error in `RoomFlowActivity`: the old `onBackPressed()` override is not invoked for Android 16 back gestures.

Alpha09 uses `OnBackPressedDispatcher` with `OnBackPressedCallback`. Back navigates RoomFlow WebView history when possible and closes RoomFlow otherwise. No lint baseline or suppression is used.
