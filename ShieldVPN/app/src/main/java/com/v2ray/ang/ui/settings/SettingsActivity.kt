package com.v2ray.ang.ui.settings

import android.content.Intent
import android.os.Bundle
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.lifecycleScope
import com.v2ray.ang.AppConfig
import com.v2ray.ang.BuildConfig
import com.v2ray.ang.R
import com.v2ray.ang.handler.MmkvManager.rememberMmkvString
import com.v2ray.ang.ui.base.BaseComponentActivity
import com.v2ray.ang.ui.compose.AppTopBar
import com.v2ray.ang.ui.compose.NavigationBarsSpacer
import com.v2ray.ang.ui.compose.PreferenceGroupHeader
import com.v2ray.ang.ui.compose.SelectListDialog
import com.v2ray.ang.ui.compose.SettingsMenuItem
import com.v2ray.ang.ui.compose.ThemeManager
import com.v2ray.ang.ui.compose.verticalScrollbar
import com.v2ray.ang.ui.routing.RoutingSettingActivity
import kotlinx.coroutines.launch
import java.text.DateFormat
import java.util.Date

/**
 * The only settings screen of the branded client.
 *
 * Everything that used to live in the v2rayNG settings — Telegram channels,
 * certificate management, third-party licences, GitHub links, transport knobs —
 * is deliberately gone. A user can change the theme, refresh the per-account
 * subscription, open the routing rules and read the app version.
 */
class SettingsActivity : BaseComponentActivity() {

    private val viewModel: SettingsViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        lifecycleScope.launch { viewModel.loadSubscriptionState() }
    }

    @Composable
    override fun ScreenContent() {
        ShieldSettingsScreen(
            viewModel = viewModel,
            onBackClick = { finish() },
            onRoutingClick = { startActivity(Intent(this, RoutingSettingActivity::class.java)) },
        )
    }
}

/** Theme modes stored in [AppConfig.PREF_UI_MODE_NIGHT]: follow system, light, dark. */
private val THEME_MODES = listOf("0", "1", "2")

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ShieldSettingsScreen(
    viewModel: SettingsViewModel,
    onBackClick: () -> Unit,
    onRoutingClick: () -> Unit,
) {
    val scrollState = rememberScrollState()
    val isLoading by viewModel.isLoading.collectAsStateWithLifecycle()
    val lastUpdated by viewModel.lastUpdated.collectAsStateWithLifecycle()

    var themeMode by rememberMmkvString(AppConfig.PREF_UI_MODE_NIGHT, "0")
    var themeDialogVisible by remember { mutableStateOf(false) }

    val themeSummary = when (themeMode) {
        "2" -> stringResource(R.string.shield_settings_theme_dark)
        "1" -> stringResource(R.string.shield_settings_theme_light)
        else -> stringResource(R.string.shield_settings_theme_system)
    }

    val updatedSummary = remember(lastUpdated) {
        if (lastUpdated <= 0L) {
            null
        } else {
            DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT)
                .format(Date(lastUpdated))
        }
    }

    Scaffold(
        contentWindowInsets = WindowInsets(0),
        topBar = {
            AppTopBar(
                title = stringResource(R.string.shield_settings_title),
                onBackClick = onBackClick,
                isLoading = isLoading,
            )
        },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .verticalScrollbar(scrollState)
                .verticalScroll(scrollState),
        ) {
            PreferenceGroupHeader(stringResource(R.string.shield_settings_appearance))
            SettingsMenuItem(
                title = stringResource(R.string.shield_settings_theme),
                subtitle = themeSummary,
                onClick = { themeDialogVisible = true },
            )
            if (themeDialogVisible) {
                SelectListDialog(
                    title = stringResource(R.string.shield_settings_theme),
                    options = THEME_MODES,
                    optionText = { mode ->
                        when (mode) {
                            "2" -> stringResource(R.string.shield_settings_theme_option_dark)
                            "1" -> stringResource(R.string.shield_settings_theme_option_light)
                            else -> stringResource(R.string.shield_settings_theme_option_system)
                        }
                    },
                    selectedOption = themeMode,
                    showRadio = true,
                    onSelected = { mode ->
                        themeMode = mode
                        ThemeManager.setThemeMode(mode)
                        themeDialogVisible = false
                    },
                    onDismiss = { themeDialogVisible = false },
                )
            }

            PreferenceGroupHeader(stringResource(R.string.shield_settings_subscription))
            SettingsMenuItem(
                title = stringResource(R.string.shield_refresh),
                subtitle = updatedSummary?.let {
                    stringResource(R.string.shield_settings_updated_at, it)
                } ?: stringResource(R.string.shield_settings_updated_never),
                onClick = viewModel::refreshSubscription,
            )

            PreferenceGroupHeader(stringResource(R.string.shield_settings_routing))
            SettingsMenuItem(
                title = stringResource(R.string.shield_settings_routing),
                subtitle = stringResource(R.string.shield_settings_routing_hint),
                onClick = onRoutingClick,
            )

            PreferenceGroupHeader(stringResource(R.string.shield_settings_about))
            VersionRow()

            Spacer(modifier = Modifier.height(24.dp))

            Text(
                text = stringResource(R.string.shield_settings_footer),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
                textAlign = TextAlign.Center,
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp),
            )

            Spacer(modifier = Modifier.height(24.dp))
            NavigationBarsSpacer()
        }
    }
}

@Composable
private fun VersionRow() {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.fillMaxWidth()) {
            Text(
                text = stringResource(R.string.shield_settings_version),
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = "ShieldVPN ${BuildConfig.VERSION_NAME}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
    }
}
