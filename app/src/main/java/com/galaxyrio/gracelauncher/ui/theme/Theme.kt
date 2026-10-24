package com.galaxyrio.gracelauncher.ui.theme

import android.os.Build
import androidx.compose.material3.ExperimentalMaterial3ExpressiveApi
import androidx.compose.material3.MaterialExpressiveTheme
import androidx.compose.material3.LocalTonalElevationEnabled
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.remember
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalResources
import com.materialkolor.PaletteStyle
import com.galaxyrio.gracelauncher.data.FontLibrary
import com.galaxyrio.gracelauncher.data.launcherThemeSeed
import com.galaxyrio.gracelauncher.data.launcherColorScheme

// Core Orca Surfaces
val TailFinVoidBlack = Color(0xFF000000)
val TailFinOrcaSurface = Color(0xFF0D0F12)
val TailFinOrcaGray = Color(0xFF1C2026)
val TailFinOrcaBorder = Color(0xFF2E343E)

// Metallic Silver & Text
val TailFinMetallicSilver = Color(0xFFC5C8CE)
val TailFinTextPrimary = Color(0xFFECEFF4)
val TailFinTextMuted = Color(0xFF7B8390)

// Accents
val TailFinAmbientRed = Color(0xFFD92B38)
val TailFinAmbientRedDim = Color(0xFF4D1015)
val TailFinScaleTeal = Color(0xFF1B4D5C)

// Legacy aliases
val Ink = TailFinOrcaSurface
val DeepTeal = TailFinScaleTeal
val Mint = TailFinMetallicSilver
val MintContainer = TailFinOrcaGray
val Coral = TailFinAmbientRed
val Moon = TailFinTextPrimary
val Mist = TailFinTextMuted

val Paper = Color(0xFFF4FBF8)
val Forest = Color(0xFF1B4D5C)
val PaleMint = Color(0xFFC5C8CE)
val Rose = Color(0xFFD92B38)

private val DarkColorScheme = darkColorScheme(
    primary = TailFinMetallicSilver,
    onPrimary = TailFinVoidBlack,
    primaryContainer = TailFinScaleTeal,
    onPrimaryContainer = TailFinTextPrimary,
    secondary = TailFinAmbientRed,
    onSecondary = TailFinTextPrimary,
    secondaryContainer = TailFinAmbientRedDim,
    onSecondaryContainer = TailFinTextPrimary,
    tertiary = TailFinScaleTeal,
    background = TailFinVoidBlack,
    onBackground = TailFinTextPrimary,
    surface = TailFinOrcaSurface,
    onSurface = TailFinTextPrimary,
    surfaceVariant = TailFinOrcaGray,
    onSurfaceVariant = TailFinTextMuted,
    outline = TailFinOrcaBorder,
)

private val LightColorScheme = lightColorScheme(
    primary = Forest,
    onPrimary = Paper,
    primaryContainer = PaleMint,
    onPrimaryContainer = TailFinVoidBlack,
    secondary = DeepTeal,
    tertiary = Rose,
    background = Paper,
    onBackground = TailFinVoidBlack,
    surface = Paper,
    onSurface = TailFinVoidBlack,
)

@OptIn(ExperimentalMaterial3ExpressiveApi::class)
@Composable
fun GraceLauncherTheme(
    darkTheme: Boolean = true,
    dynamicColor: Boolean = true,
    seedColor: Color? = null,
    fontLibrary: FontLibrary = FontLibrary(),
    amoledMode: Boolean = false,
    paletteStyle: PaletteStyle = PaletteStyle.TonalSpot,
    content: @Composable () -> Unit,
) {
    val colorScheme = if (seedColor != null || (dynamicColor && Build.VERSION.SDK_INT >= 31)) {
        val seed = launcherThemeSeed(LocalResources.current, dynamicColor, seedColor?.toArgb() ?: 0xFFD92B38.toInt())
        remember(seed, darkTheme, paletteStyle) { launcherColorScheme(seed, darkTheme, paletteStyle) }
    } else if (darkTheme) DarkColorScheme else LightColorScheme

    val trueBlack = darkTheme && amoledMode
    // Keep raised cards and accent colors distinct while making page and sheet
    // backgrounds truly black, for both wallpaper-derived and custom palettes.
    val colors = if (trueBlack) colorScheme.copy(
        background = Color.Black,
        surface = Color.Black,
        surfaceDim = Color.Black,
        surfaceContainerLowest = Color.Black,
        surfaceContainerLow = TailFinOrcaSurface,
        surfaceContainer = TailFinOrcaSurface,
    ) else colorScheme

    val family = rememberAppFontFamily(null, fontLibrary)
    val typography = remember(family) { launcherTypography(family) }
    CompositionLocalProvider(
        LocalFontLibrary provides fontLibrary,
        LocalLauncherTypography provides typography,
        // Elevation tint must not turn the black sheets back into tinted gray.
        LocalTonalElevationEnabled provides (LocalTonalElevationEnabled.current && !trueBlack),
    ) {
        MaterialExpressiveTheme(
            colorScheme = colors,
            typography = typography,
            content = content,
        )
    }
}
