package com.v2ray.ang.ui.shield

import android.content.Intent
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import androidx.activity.compose.BackHandler
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.lifecycleScope
import com.v2ray.ang.R
import com.v2ray.ang.enums.PermissionType
import com.v2ray.ang.handler.SettingsManager
import com.v2ray.ang.shield.ShieldPrefs
import com.v2ray.ang.shield.ShieldServer
import com.v2ray.ang.shield.ShieldStatus
import com.v2ray.ang.shield.ShieldUiState
import com.v2ray.ang.shield.ShieldViewModel
import com.v2ray.ang.ui.base.HelperBaseComponentActivity
import com.v2ray.ang.ui.main.MainActivity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

/**
 * The single user-facing screen of ShieldVPN: one big connect button, the current
 * state, and an optional server picker.
 */
class ShieldActivity : HelperBaseComponentActivity() {

    private val viewModel: ShieldViewModel by viewModels()

    private var pendingGuid: String? = null
    private var autoConnectHandled = false
    private var autoConnectAllowed = true

    private val vpnPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            if (result.resultCode == RESULT_OK) {
                startConnect(pendingGuid)
            } else {
                viewModel.reportPermissionDenied()
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Only auto-connect on a cold start, not after a rotation.
        autoConnectAllowed = savedInstanceState == null
        checkAndRequestPermission(PermissionType.POST_NOTIFICATIONS) {}
    }

    override fun onStart() {
        super.onStart()
        if (autoConnectAllowed) maybeAutoConnect()
    }

    @Composable
    override fun ScreenContent() {
        val state by viewModel.state.collectAsStateWithLifecycle()

        BackHandler { moveTaskToBack(false) }

        ShieldScreen(
            state = state,
            onToggle = {
                when (state.status) {
                    ShieldStatus.Connected, ShieldStatus.Connecting -> viewModel.disconnect()
                    else -> requestConnect(null)
                }
            },
            onSelectServer = { guid -> requestConnect(guid) },
            onRefresh = viewModel::refreshSubscription,
            onAutoConnectChange = viewModel::setAutoConnect,
            onOpenAdvanced = {
                startActivity(Intent(this, MainActivity::class.java))
            },
        )
    }

    // ------------------------------------------------------------------ VPN start

    private fun maybeAutoConnect() {
        if (autoConnectHandled) return
        autoConnectHandled = true
        lifecycleScope.launch {
            val autoConnect = withContext(Dispatchers.IO) { ShieldPrefs.isAutoConnect() }
            if (!autoConnect) return@launch

            // Wait until the controller knows whether the tunnel is already up.
            val ready = withTimeoutOrNull(2_500) { viewModel.state.first { it.initialized } }
                ?: viewModel.state.value
            if (ready.status == ShieldStatus.Connected || ready.status == ShieldStatus.Connecting) {
                return@launch
            }
            requestConnect(null)
        }
    }

    private fun requestConnect(preferredGuid: String?) {
        pendingGuid = preferredGuid
        val consent = if (SettingsManager.isVpnMode()) VpnService.prepare(this) else null
        if (consent != null) {
            vpnPermissionLauncher.launch(consent)
            return
        }
        startConnect(preferredGuid)
    }

    private fun startConnect(preferredGuid: String?) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.CINNAMON_BUN) {
            checkAndRequestPermission(PermissionType.ACCESS_LOCAL_NETWORK) {
                viewModel.connect(preferredGuid)
            }
            return
        }
        viewModel.connect(preferredGuid)
    }
}

// ---------------------------------------------------------------------- UI

private val BackgroundTop = Color(0xFF0B1220)
private val BackgroundBottom = Color(0xFF111C33)
private val AccentGreen = Color(0xFF22C55E)
private val AccentGreenDark = Color(0xFF15803D)
private val AccentRed = Color(0xFFEF4444)
private val AccentAmber = Color(0xFFF59E0B)
private val TextMuted = Color(0xFF94A3B8)
private val CardBackground = Color(0xFF16213A)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ShieldScreen(
    state: ShieldUiState,
    onToggle: () -> Unit,
    onSelectServer: (String) -> Unit,
    onRefresh: () -> Unit,
    onAutoConnectChange: (Boolean) -> Unit,
    onOpenAdvanced: () -> Unit,
) {
    var showServerPicker by remember { mutableStateOf(false) }

    val accent = when (state.status) {
        ShieldStatus.Connected -> AccentGreen
        ShieldStatus.Error -> AccentRed
        ShieldStatus.Connecting, ShieldStatus.Disconnecting -> AccentAmber
        ShieldStatus.Idle -> AccentGreen
    }
    val accentDark = when (state.status) {
        ShieldStatus.Connected -> AccentGreenDark
        ShieldStatus.Error -> Color(0xFF991B1B)
        ShieldStatus.Connecting, ShieldStatus.Disconnecting -> Color(0xFFB45309)
        ShieldStatus.Idle -> Color(0xFF166534)
    }

    val buttonLabel = when (state.status) {
        ShieldStatus.Connected -> stringResource(R.string.shield_disconnect)
        ShieldStatus.Connecting, ShieldStatus.Disconnecting -> stringResource(R.string.shield_status_connecting)
        else -> stringResource(R.string.shield_connect)
    }
    val statusText = when (state.status) {
        ShieldStatus.Idle -> stringResource(R.string.shield_status_idle)
        ShieldStatus.Connecting -> stringResource(R.string.shield_status_connecting)
        ShieldStatus.Connected -> stringResource(R.string.shield_status_connected)
        ShieldStatus.Disconnecting -> stringResource(R.string.shield_status_disconnecting)
        ShieldStatus.Error -> stringResource(R.string.shield_status_error)
    }

    Box(
        Modifier
            .fillMaxSize()
            .background(Brush.verticalGradient(listOf(BackgroundTop, BackgroundBottom))),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 24.dp, vertical = 32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                text = stringResource(R.string.app_name),
                color = Color.White,
                fontSize = 28.sp,
                fontWeight = FontWeight.Bold,
            )
            Text(
                text = stringResource(R.string.shield_tagline),
                color = TextMuted,
                fontSize = 13.sp,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 6.dp),
            )

            Spacer(Modifier.weight(1f))

            ConnectButton(
                label = buttonLabel,
                accent = accent,
                accentDark = accentDark,
                pulsing = state.status == ShieldStatus.Connecting,
                enabled = state.status != ShieldStatus.Disconnecting,
                onClick = onToggle,
            )

            Spacer(Modifier.height(24.dp))

            Text(
                text = statusText,
                color = if (state.status == ShieldStatus.Error) AccentRed else Color.White,
                fontSize = 18.sp,
                fontWeight = FontWeight.SemiBold,
            )

            if (state.status == ShieldStatus.Connecting && state.totalAttempts > 0) {
                Text(
                    text = stringResource(
                        R.string.shield_attempt,
                        state.attempt,
                        state.totalAttempts,
                    ),
                    color = TextMuted,
                    fontSize = 13.sp,
                    modifier = Modifier.padding(top = 4.dp),
                )
            }

            state.message?.let { message ->
                Text(
                    text = message,
                    color = TextMuted,
                    fontSize = 13.sp,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.padding(top = 8.dp),
                )
            }

            Spacer(Modifier.height(28.dp))

            ServerCard(
                title = state.selectedTitle,
                onChange = { showServerPicker = true },
            )

            Spacer(Modifier.weight(1f))

            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = stringResource(R.string.shield_auto_connect),
                    color = TextMuted,
                    fontSize = 13.sp,
                    modifier = Modifier.weight(1f),
                )
                Switch(
                    checked = state.autoConnect,
                    onCheckedChange = onAutoConnectChange,
                    colors = SwitchDefaults.colors(
                        checkedThumbColor = Color.White,
                        checkedTrackColor = AccentGreen,
                    ),
                )
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                TextButton(onClick = onRefresh) {
                    Text(stringResource(R.string.shield_refresh), color = TextMuted, fontSize = 13.sp)
                }
                TextButton(onClick = onOpenAdvanced) {
                    Text(stringResource(R.string.shield_advanced), color = TextMuted, fontSize = 13.sp)
                }
            }
        }
    }

    if (showServerPicker) {
        ServerPickerSheet(
            servers = state.servers,
            selectedGuid = state.selectedGuid,
            onDismiss = { showServerPicker = false },
            onSelect = { guid ->
                showServerPicker = false
                onSelectServer(guid)
            },
        )
    }
}

@Composable
private fun ConnectButton(
    label: String,
    accent: Color,
    accentDark: Color,
    pulsing: Boolean,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    val transition = rememberInfiniteTransition(label = "pulse")
    val animatedAlpha by transition.animateFloat(
        initialValue = 0.25f,
        targetValue = 0.6f,
        animationSpec = infiniteRepeatable(
            animation = tween(durationMillis = 1_100),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "pulseAlpha",
    )
    val haloAlpha = if (pulsing) animatedAlpha else 0.25f

    Box(
        modifier = Modifier
            .size(240.dp)
            .clip(CircleShape)
            .background(
                Brush.radialGradient(
                    listOf(accent.copy(alpha = haloAlpha), Color.Transparent),
                ),
            )
            .clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier
                .size(184.dp)
                .clip(CircleShape)
                .background(Brush.verticalGradient(listOf(accent, accentDark))),
            contentAlignment = Alignment.Center,
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                ShieldMark(
                    modifier = Modifier.size(64.dp),
                    fill = Color.White,
                    check = accentDark,
                )
                Spacer(Modifier.height(10.dp))
                Text(
                    text = label,
                    color = Color.White,
                    fontSize = 15.sp,
                    fontWeight = FontWeight.Bold,
                )
            }
        }
    }
}

@Composable
private fun ShieldMark(modifier: Modifier, fill: Color, check: Color) {
    Canvas(modifier = modifier) {
        val w = size.width
        val h = size.height
        val shield = Path().apply {
            moveTo(w * 0.5f, h * 0.05f)
            lineTo(w * 0.9f, h * 0.22f)
            lineTo(w * 0.9f, h * 0.5f)
            cubicTo(w * 0.9f, h * 0.76f, w * 0.73f, h * 0.9f, w * 0.5f, h * 0.97f)
            cubicTo(w * 0.27f, h * 0.9f, w * 0.1f, h * 0.76f, w * 0.1f, h * 0.5f)
            lineTo(w * 0.1f, h * 0.22f)
            close()
        }
        drawPath(shield, color = fill)

        val strokeWidth = w * 0.1f
        drawLine(
            color = check,
            start = Offset(w * 0.32f, h * 0.5f),
            end = Offset(w * 0.45f, h * 0.64f),
            strokeWidth = strokeWidth,
            cap = StrokeCap.Round,
        )
        drawLine(
            color = check,
            start = Offset(w * 0.45f, h * 0.64f),
            end = Offset(w * 0.7f, h * 0.37f),
            strokeWidth = strokeWidth,
            cap = StrokeCap.Round,
        )
    }
}

@Composable
private fun ServerCard(title: String?, onChange: () -> Unit) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(20.dp),
        color = CardBackground,
    ) {
        Row(
            modifier = Modifier.padding(start = 20.dp, end = 8.dp, top = 14.dp, bottom = 14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = stringResource(R.string.shield_server_title).uppercase(),
                    color = TextMuted,
                    fontSize = 10.sp,
                    letterSpacing = 1.sp,
                )
                Text(
                    text = title ?: "—",
                    color = Color.White,
                    fontSize = 16.sp,
                    fontWeight = FontWeight.SemiBold,
                )
            }
            TextButton(onClick = onChange) {
                Text(stringResource(R.string.shield_change_server), color = AccentGreen, fontSize = 14.sp)
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ServerPickerSheet(
    servers: List<ShieldServer>,
    selectedGuid: String?,
    onDismiss: () -> Unit,
    onSelect: (String) -> Unit,
) {
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        containerColor = CardBackground,
    ) {
        Text(
            text = stringResource(R.string.shield_servers_title),
            color = Color.White,
            fontSize = 18.sp,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp),
        )
        if (servers.isEmpty()) {
            Text(
                text = stringResource(R.string.shield_no_servers),
                color = TextMuted,
                fontSize = 14.sp,
                modifier = Modifier.padding(24.dp),
            )
        } else {
            LazyColumn(
                modifier = Modifier
                    .heightIn(max = 460.dp)
                    .padding(bottom = 24.dp),
            ) {
                items(servers, key = { it.guid }) { server ->
                    val selected = server.guid == selectedGuid
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { onSelect(server.guid) }
                            .padding(horizontal = 24.dp, vertical = 14.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Box(
                            modifier = Modifier
                                .size(10.dp)
                                .clip(CircleShape)
                                .background(if (selected) AccentGreen else Color(0xFF334155)),
                        )
                        Column(modifier = Modifier
                            .weight(1f)
                            .padding(start = 14.dp)) {
                            Text(
                                text = server.title,
                                color = Color.White,
                                fontSize = 15.sp,
                                fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
                            )
                            Text(
                                text = server.subtitle,
                                color = TextMuted,
                                fontSize = 12.sp,
                            )
                        }
                    }
                }
            }
        }
    }
}
