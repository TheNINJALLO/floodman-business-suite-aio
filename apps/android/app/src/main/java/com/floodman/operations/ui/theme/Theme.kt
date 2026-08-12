package com.floodman.operations.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val FloodmanNavy = Color(0xFF12354A)
val FloodmanCyan = Color(0xFF24A9D8)
val FloodmanGreen = Color(0xFF72B944)
val FloodmanMagenta = Color(0xFFC40078)
val FloodmanBackground = Color(0xFFF4F8FA)

private val LightColors = lightColorScheme(
    primary = FloodmanNavy,
    onPrimary = Color.White,
    secondary = FloodmanCyan,
    tertiary = FloodmanGreen,
    error = FloodmanMagenta,
    background = FloodmanBackground,
    surface = Color.White,
    surfaceVariant = Color(0xFFEAF2F6),
    onSurface = Color(0xFF183040),
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFF7DD8F4),
    onPrimary = Color(0xFF002F42),
    secondary = Color(0xFF5EC6EB),
    tertiary = Color(0xFFA5D879),
    error = Color(0xFFFF75B5),
    background = Color(0xFF0C171F),
    surface = Color(0xFF12232E),
    surfaceVariant = Color(0xFF1B3442),
    onSurface = Color(0xFFE2F2FA),
)

@Composable
fun FloodmanTheme(mode: String = "SYSTEM", content: @Composable () -> Unit) {
    val dark = when (mode.uppercase()) {
        "DARK" -> true
        "LIGHT" -> false
        else -> isSystemInDarkTheme()
    }
    MaterialTheme(colorScheme = if (dark) DarkColors else LightColors, content = content)
}
