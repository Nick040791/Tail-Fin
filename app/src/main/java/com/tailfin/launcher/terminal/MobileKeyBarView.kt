package com.tailfin.launcher.terminal

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.galaxyrio.gracelauncher.ui.theme.TailFinAmbientRed
import com.galaxyrio.gracelauncher.ui.theme.TailFinMetallicSilver
import com.galaxyrio.gracelauncher.ui.theme.TailFinOrcaBorder
import com.galaxyrio.gracelauncher.ui.theme.TailFinOrcaGray
import com.galaxyrio.gracelauncher.ui.theme.TailFinOrcaSurface
import com.galaxyrio.gracelauncher.ui.theme.TailFinScaleTeal
import com.galaxyrio.gracelauncher.ui.theme.TailFinTextPrimary

enum class AnsiArrowDirection(val label: String, val sequence: String) {
    UP("▲", "\u001B[A"),
    DOWN("▼", "\u001B[B"),
    LEFT("◀", "\u001B[D"),
    RIGHT("▶", "\u001B[C"),
}

enum class TmuxQuickChord(val label: String, val keyChar: Char) {
    DETACH("tmux:d", 'd'),
    CREATE("tmux:c", 'c'),
    NEXT("tmux:n", 'n'),
    PREV("tmux:p", 'p');

    val sequence: String
        get() = "\u0002$keyChar" // Ctrl+B (\u0002) followed by d/c/n/p
}

object MobileTerminalKeyEncoder {
    const val KEY_ESC = "\u001B"
    const val KEY_TAB = "\t"
    const val KEY_CTRL_B = "\u0002"
    const val KEY_CTRL_C = "\u0003"
    const val KEY_CTRL_D = "\u0004"

    /**
     * Applies sticky CTRL and/or ALT modifiers to typed input.
     */
    fun applyModifiers(input: String, ctrlActive: Boolean, altActive: Boolean): String {
        if (input.isEmpty()) return input
        val transformed = if (ctrlActive) {
            val first = input.first().lowercaseChar()
            val ctrlChar = if (first in 'a'..'z') {
                (first.code - 'a'.code + 1).toChar().toString()
            } else {
                input
            }
            ctrlChar + input.drop(1)
        } else {
            input
        }
        return if (altActive) {
            KEY_ESC + transformed
        } else {
            transformed
        }
    }
}

@Composable
fun MobileKeyBarView(
    ctrlSticky: Boolean,
    altSticky: Boolean,
    onToggleCtrl: () -> Unit,
    onToggleAlt: () -> Unit,
    onSendSequence: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val scrollState = rememberScrollState()
    Row(
        modifier = modifier
            .fillMaxWidth()
            .background(TailFinOrcaSurface)
            .padding(horizontal = 8.dp, vertical = 6.dp)
            .horizontalScroll(scrollState)
            .testTag("mobile_key_bar"),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        KeyBarButton(
            label = "ESC",
            tag = "key_esc",
            onClick = { onSendSequence(MobileTerminalKeyEncoder.KEY_ESC) },
        )
        KeyBarButton(
            label = "TAB",
            tag = "key_tab",
            onClick = { onSendSequence(MobileTerminalKeyEncoder.KEY_TAB) },
        )
        KeyBarButton(
            label = "CTRL",
            tag = "key_ctrl",
            active = ctrlSticky,
            activeColor = TailFinAmbientRed,
            onClick = onToggleCtrl,
        )
        KeyBarButton(
            label = "ALT",
            tag = "key_alt",
            active = altSticky,
            activeColor = TailFinScaleTeal,
            onClick = onToggleAlt,
        )
        AnsiArrowDirection.entries.forEach { arrow ->
            KeyBarButton(
                label = arrow.label,
                tag = "key_arrow_${arrow.name.lowercase()}",
                onClick = { onSendSequence(arrow.sequence) },
            )
        }
        TmuxQuickChord.entries.forEach { chord ->
            KeyBarButton(
                label = chord.label,
                tag = "key_tmux_${chord.keyChar}",
                accentBorder = TailFinScaleTeal,
                onClick = { onSendSequence(chord.sequence) },
            )
        }
        KeyBarButton(
            label = "^C",
            tag = "key_ctrl_c",
            accentBorder = TailFinAmbientRed,
            onClick = { onSendSequence(MobileTerminalKeyEncoder.KEY_CTRL_C) },
        )
    }
}

@Composable
private fun KeyBarButton(
    label: String,
    tag: String,
    active: Boolean = false,
    activeColor: Color = TailFinAmbientRed,
    accentBorder: Color = TailFinOrcaBorder,
    onClick: () -> Unit,
) {
    val shape = RoundedCornerShape(6.dp)
    Box(
        modifier = Modifier
            .clip(shape)
            .background(if (active) activeColor else TailFinOrcaGray)
            .border(1.dp, if (active) TailFinMetallicSilver else accentBorder, shape)
            .clickable(onClick = onClick)
            .padding(horizontal = 10.dp, vertical = 6.dp)
            .testTag(tag),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = label,
            color = if (active) TailFinTextPrimary else TailFinMetallicSilver,
            fontFamily = FontFamily.Monospace,
            fontSize = 12.sp,
            fontWeight = FontWeight.Bold,
        )
    }
}
