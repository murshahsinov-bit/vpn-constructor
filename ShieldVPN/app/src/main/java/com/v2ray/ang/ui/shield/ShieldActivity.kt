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
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
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
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.credentials.CredentialManager
import androidx.credentials.GetCredentialRequest
import androidx.credentials.exceptions.GetCredentialException
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.lifecycleScope
import com.google.android.libraries.identity.googleid.GetGoogleIdOption
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential
import com.v2ray.ang.R
import com.v2ray.ang.enums.PermissionType
import com.v2ray.ang.handler.SettingsManager
import com.v2ray.ang.shield.ShieldAuth
import com.v2ray.ang.shield.ShieldAuthState
import com.v2ray.ang.shield.ShieldServer
import com.v2ray.ang.shield.ShieldStatus
import com.v2ray.ang.shield.ShieldUiState
import com.v2ray.ang.shield.ShieldViewModel
import com.v2ray.ang.ui.base.HelperBaseComponentActivity
import com.v2ray.ang.ui.settings.SettingsActivity
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

/**
 * The only user-facing screen of ShieldVPN.
 *
 * Flow: account gate -> one big connect button -> server picker ("Авто" by
 * default). The picker shows a flag, the node name and the measured latency, and
 * "Авто" always dials the fastest reachable node.
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

    @Composable
    override fun ScreenContent() {
        val auth by ShieldAuth.state.collectAsStateWithLifecycle()
        val state by viewModel.state.collectAsStateWithLifecycle()

        BackHandler { moveTaskToBack(false) }

        if (!auth.signedIn) {
            ShieldLoginScreen(
                auth = auth,
                onGoogle = ::signInWithGoogle,
                onEmail = { email, password, register ->
                    lifecycleScope.launch { ShieldAuth.signInWithEmail(email, password, register) }
                },
                onDismissError = ShieldAuth::clearError,
            )
            return
        }

        // Connect as soon as the account gate is passed and the daemon has
        // reported whether a tunnel is already up.
        LaunchedEffect(auth.signedIn, state.initialized) {
            if (autoConnectAllowed && auth.signedIn && state.initialized) {
                maybeAutoConnect()
            }
        }

        // Populate the server list from the per-account URL even when the user
        // keeps auto-connect off: otherwise the picker stays empty until connect.
        LaunchedEffect(auth.signedIn) {
            if (auth.signedIn) viewModel.prefetchSubscription()
        }

        ShieldScreen(
            state = state,
            accountEmail = auth.email,
            onToggle = {
                when (state.status) {
                    ShieldStatus.Connected, ShieldStatus.Connecting -> viewModel.disconnect()
                    else -> requestConnect(null)
                }
            },
            onPingAll = viewModel::pingAll,
            onSelectAuto = {
                viewModel.setAutoMode(true)
                requestConnect(null)
            },
            onSelectServer = { guid -> requestConnect(guid) },
            onRefresh = viewModel::refreshSubscription,
            onAutoConnectChange = viewModel::setAutoConnect,
            onByeDpiChange = viewModel::setByeDpiEnabled,
            onOpenAdvanced = {
                startActivity(Intent(this, SettingsActivity::class.java))
            },
            // Signing out must also tear the tunnel down: otherwise the vpn service,
            // the daemon and the local ciadpi keep running for a signed-out user.
            onSignOut = {
                viewModel.disconnect()
                ShieldAuth.signOut()
            },
        )
    }

    // ------------------------------------------------------------------ VPN start

    private fun maybeAutoConnect() {
        if (autoConnectHandled) return
        autoConnectHandled = true
        lifecycleScope.launch {
            val autoConnect = withContext(Dispatchers.IO) { com.v2ray.ang.shield.ShieldPrefs.isAutoConnect() }
            if (!autoConnect) return@launch

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

    // -------------------------------------------------------------------- Google

    private fun signInWithGoogle() {
        if (!ShieldAuth.state.value.firebaseAvailable || ShieldAuth.webClientId().isBlank()) {
            return
        }
        lifecycleScope.launch {
            val request = GetCredentialRequest(
                listOf(
                    GetGoogleIdOption.Builder()
                        .setServerClientId(ShieldAuth.webClientId())
                        .setFilterByAuthorizedAccounts(false)
                        .setAutoSelectEnabled(false)
                        .build(),
                ),
            )
            try {
                val response = CredentialManager.create(this@ShieldActivity)
                    .getCredential(this@ShieldActivity, request)
                val googleCredential = GoogleIdTokenCredential.createFrom(response.credential.data)
                ShieldAuth.signInWithGoogleToken(googleCredential.idToken)
            } catch (e: GetCredentialException) {
                ShieldAuth.reportError(e.message ?: getString(R.string.shield_google_failed))
            } catch (t: Throwable) {
                ShieldAuth.reportError(t.message ?: getString(R.string.shield_google_failed))
            }
        }
    }
}

// ---------------------------------------------------------------------- theme

private val BackgroundTop = Color(0xFF0B1220)
private val BackgroundBottom = Color(0xFF111C33)
private val AccentGreen = Color(0xFF22C55E)
private val AccentGreenDark = Color(0xFF15803D)
private val AccentRed = Color(0xFFEF4444)
private val AccentAmber = Color(0xFFF59E0B)
private val TextMuted = Color(0xFF94A3B8)
private val CardBackground = Color(0xFF16213A)
private val FieldBackground = Color(0xFF0F1829)

// ----------------------------------------------------------------------- gate

@Composable
private fun ShieldLoginScreen(
    auth: ShieldAuthState,
    onGoogle: () -> Unit,
    onEmail: (String, String, Boolean) -> Unit,
    onDismissError: () -> Unit,
) {
    var showEmailForm by rememberSaveable { mutableStateOf(false) }
    var register by rememberSaveable { mutableStateOf(false) }
    var email by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }

    Box(
        Modifier
            .fillMaxSize()
            .background(Brush.verticalGradient(listOf(BackgroundTop, BackgroundBottom))),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .imePadding()
                .padding(horizontal = 28.dp, vertical = 36.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            ShieldMark(modifier = Modifier.size(76.dp), fill = AccentGreen, check = BackgroundTop)

            Text(
                text = stringResource(R.string.app_name),
                color = Color.White,
                fontSize = 28.sp,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.padding(top = 16.dp),
            )
            Text(
                text = stringResource(R.string.shield_login_subtitle),
                color = TextMuted,
                fontSize = 13.sp,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 8.dp),
            )

            Spacer(Modifier.height(32.dp))

            Button(
                onClick = onGoogle,
                enabled = auth.firebaseAvailable && !auth.loading,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(54.dp),
                shape = RoundedCornerShape(16.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = Color.White,
                    contentColor = Color(0xFF0B1220),
                    disabledContainerColor = Color(0xFF243149),
                    disabledContentColor = TextMuted,
                ),
            ) {
                Text(
                    text = stringResource(R.string.shield_login_google),
                    fontSize = 15.sp,
                    fontWeight = FontWeight.SemiBold,
                )
            }

            Spacer(Modifier.height(12.dp))

            Button(
                onClick = { showEmailForm = !showEmailForm },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(54.dp),
                shape = RoundedCornerShape(16.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = CardBackground,
                    contentColor = Color.White,
                ),
            ) {
                Text(
                    text = stringResource(R.string.shield_login_email),
                    fontSize = 15.sp,
                    fontWeight = FontWeight.SemiBold,
                )
            }

            if (showEmailForm) {
                Spacer(Modifier.height(20.dp))

                OutlinedTextField(
                    value = email,
                    onValueChange = { email = it },
                    singleLine = true,
                    label = { Text(stringResource(R.string.shield_email_hint)) },
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(14.dp),
                    colors = fieldColors(),
                )
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = password,
                    onValueChange = { password = it },
                    singleLine = true,
                    label = { Text(stringResource(R.string.shield_password_hint)) },
                    visualTransformation = PasswordVisualTransformation(),
                    modifier = Modifier.fillMaxWidth(),
                    shape = RoundedCornerShape(14.dp),
                    colors = fieldColors(),
                )

                Spacer(Modifier.height(16.dp))

                Button(
                    onClick = { onEmail(email, password, register) },
                    enabled = !auth.loading,
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(54.dp),
                    shape = RoundedCornerShape(16.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = AccentGreen,
                        contentColor = Color.White,
                    ),
                ) {
                    if (auth.loading) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(20.dp),
                            color = Color.White,
                            strokeWidth = 2.dp,
                        )
                    } else {
                        Text(
                            text = stringResource(
                                if (register) R.string.shield_register else R.string.shield_sign_in,
                            ),
                            fontSize = 15.sp,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }

                TextButton(onClick = {
                    register = !register
                    onDismissError()
                }) {
                    Text(
                        text = stringResource(
                            if (register) R.string.shield_have_account else R.string.shield_create_account,
                        ),
                        color = TextMuted,
                        fontSize = 13.sp,
                    )
                }
            }

            auth.error?.let { message ->
                Text(
                    text = message,
                    color = AccentRed,
                    fontSize = 13.sp,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.padding(top = 16.dp),
                )
            }

            auth.info?.let { message ->
                Text(
                    text = message,
                    color = TextMuted,
                    fontSize = 11.sp,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.padding(top = 18.dp),
                )
            }
        }
    }
}

@Composable
private fun fieldColors() = OutlinedTextFieldDefaults.colors(
    focusedTextColor = Color.White,
    unfocusedTextColor = Color.White,
    focusedContainerColor = FieldBackground,
    unfocusedContainerColor = FieldBackground,
    focusedBorderColor = AccentGreen,
    unfocusedBorderColor = Color(0xFF25344F),
    focusedLabelColor = AccentGreen,
    unfocusedLabelColor = TextMuted,
    cursorColor = AccentGreen,
)

// ----------------------------------------------------------------- main screen

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ShieldScreen(
    state: ShieldUiState,
    accountEmail: String?,
    onToggle: () -> Unit,
    onPingAll: () -> Unit,
    onSelectAuto: () -> Unit,
    onSelectServer: (String) -> Unit,
    onRefresh: () -> Unit,
    onAutoConnectChange: (Boolean) -> Unit,
    onByeDpiChange: (Boolean) -> Unit,
    onOpenAdvanced: () -> Unit,
    onSignOut: () -> Unit,
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

    val selected = state.servers.firstOrNull { it.guid == state.selectedGuid }
    val best = state.servers.minByOrNull { state.pings[it.guid] ?: Long.MAX_VALUE }
    val active = if (state.autoMode) best else selected
    val activePing = state.pings[active?.guid]

    Box(
        Modifier
            .fillMaxSize()
            .background(Brush.verticalGradient(listOf(BackgroundTop, BackgroundBottom))),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 24.dp, vertical = 28.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = stringResource(R.string.app_name),
                        color = Color.White,
                        fontSize = 26.sp,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        text = accountEmail ?: stringResource(R.string.shield_tagline),
                        color = TextMuted,
                        fontSize = 12.sp,
                    )
                }
                TextButton(onClick = onSignOut) {
                    Text(
                        text = stringResource(R.string.shield_logout),
                        color = TextMuted,
                        fontSize = 12.sp,
                    )
                }
            }

            Spacer(Modifier.weight(1f))

            ConnectButton(
                label = buttonLabel,
                accent = accent,
                accentDark = accentDark,
                pulsing = state.status == ShieldStatus.Connecting,
                enabled = state.status != ShieldStatus.Disconnecting,
                onClick = onToggle,
            )

            Spacer(Modifier.height(20.dp))

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
                    fontSize = 12.sp,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.padding(top = 8.dp),
                )
            }

            Spacer(Modifier.height(20.dp))

            ServerCard(
                autoMode = state.autoMode,
                flag = active?.flag ?: "🌐",
                title = active?.title ?: stringResource(R.string.shield_auto_best),
                pingMs = activePing,
                pinging = state.pinging,
                byeDpiRunning = state.byeDpiRunning && state.byeDpiEnabled,
                onClick = { showServerPicker = true },
            )

            Spacer(Modifier.weight(1f))

            ToggleRow(
                title = stringResource(R.string.shield_byedpi),
                subtitle = stringResource(R.string.shield_byedpi_hint),
                checked = state.byeDpiEnabled,
                onCheckedChange = onByeDpiChange,
            )
            ToggleRow(
                title = stringResource(R.string.shield_auto_connect),
                subtitle = null,
                checked = state.autoConnect,
                onCheckedChange = onAutoConnectChange,
            )

            // Two short actions share a row; the long "advanced settings" label gets
            // its own full-width row, otherwise it is squeezed into a vertical stack.
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.CenterHorizontally),
            ) {
                TextButton(onClick = onPingAll) {
                    Text(
                        text = stringResource(R.string.shield_ping_all),
                        color = TextMuted,
                        fontSize = 13.sp,
                    )
                }
                TextButton(onClick = onRefresh) {
                    Text(
                        text = stringResource(R.string.shield_refresh),
                        color = TextMuted,
                        fontSize = 13.sp,
                    )
                }
            }
            TextButton(
                onClick = onOpenAdvanced,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    text = stringResource(R.string.shield_advanced),
                    color = TextMuted,
                    fontSize = 13.sp,
                )
            }
        }
    }

    if (showServerPicker) {
        ServerPickerSheet(
            servers = state.servers,
            pings = state.pings,
            selectedGuid = state.selectedGuid,
            autoMode = state.autoMode,
            pinging = state.pinging,
            onDismiss = { showServerPicker = false },
            onSelectAuto = {
                showServerPicker = false
                onSelectAuto()
            },
            onSelect = { guid ->
                showServerPicker = false
                onSelectServer(guid)
            },
        )
    }
}

@Composable
private fun ToggleRow(
    title: String,
    subtitle: String?,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(text = title, color = Color.White, fontSize = 13.sp)
            subtitle?.let {
                Text(text = it, color = TextMuted, fontSize = 11.sp)
            }
        }
        Switch(
            checked = checked,
            onCheckedChange = onCheckedChange,
            colors = SwitchDefaults.colors(
                checkedThumbColor = Color.White,
                checkedTrackColor = AccentGreen,
            ),
        )
    }
}

// ---------------------------------------------------------------------- widgets

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
            .clickable(
                enabled = enabled,
                role = Role.Button,
                onClick = onClick,
            ),
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
private fun ServerCard(
    autoMode: Boolean,
    flag: String,
    title: String,
    pingMs: Long?,
    pinging: Boolean,
    byeDpiRunning: Boolean,
    onClick: () -> Unit,
) {
    Surface(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(20.dp))
            .clickable(role = Role.Button, onClick = onClick),
        shape = RoundedCornerShape(20.dp),
        color = CardBackground,
    ) {
        Column(modifier = Modifier.padding(horizontal = 18.dp, vertical = 14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(text = flag, fontSize = 24.sp)
                Column(
                    modifier = Modifier
                        .weight(1f)
                        .padding(start = 12.dp),
                ) {
                    Text(
                        text = if (autoMode) {
                            stringResource(R.string.shield_mode_auto)
                        } else {
                            stringResource(R.string.shield_mode_manual)
                        },
                        color = AccentGreen,
                        fontSize = 10.sp,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        text = title,
                        color = Color.White,
                        fontSize = 15.sp,
                        fontWeight = FontWeight.SemiBold,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                PingLabel(pingMs = pingMs, pinging = pinging)
            }
            Spacer(Modifier.height(6.dp))
            Text(
                text = if (byeDpiRunning) {
                    stringResource(R.string.shield_byedpi_active)
                } else {
                    stringResource(R.string.shield_change_server)
                },
                color = TextMuted,
                fontSize = 11.sp,
            )
        }
    }
}

@Composable
private fun PingLabel(pingMs: Long?, pinging: Boolean) {
    if (pinging && pingMs == null) {
        CircularProgressIndicator(
            modifier = Modifier.size(14.dp),
            color = AccentAmber,
            strokeWidth = 2.dp,
        )
        return
    }
    val text = when {
        pingMs == null -> stringResource(R.string.shield_ping_unknown)
        pingMs == Long.MAX_VALUE -> stringResource(R.string.shield_ping_offline)
        else -> stringResource(R.string.shield_ping_value, pingMs)
    }
    Text(
        text = text,
        color = pingColor(pingMs),
        fontSize = 12.sp,
        fontWeight = FontWeight.SemiBold,
    )
}

private fun pingColor(pingMs: Long?): Color = when {
    pingMs == null -> TextMuted
    pingMs == Long.MAX_VALUE -> AccentRed
    pingMs < 180 -> AccentGreen
    pingMs < 450 -> AccentAmber
    else -> AccentRed
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ServerPickerSheet(
    servers: List<ShieldServer>,
    pings: Map<String, Long>,
    selectedGuid: String?,
    autoMode: Boolean,
    pinging: Boolean,
    onDismiss: () -> Unit,
    onSelectAuto: () -> Unit,
    onSelect: (String) -> Unit,
) {
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        containerColor = CardBackground,
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 24.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = stringResource(R.string.shield_servers_title),
                color = Color.White,
                fontSize = 18.sp,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.weight(1f),
            )
            if (pinging) {
                CircularProgressIndicator(
                    modifier = Modifier.size(16.dp),
                    color = AccentGreen,
                    strokeWidth = 2.dp,
                )
            }
        }

        LazyColumn(
            modifier = Modifier
                .heightIn(max = 480.dp)
                .padding(bottom = 24.dp),
        ) {
            item(key = "auto") {
                ServerRow(
                    flag = "⚡",
                    title = stringResource(R.string.shield_auto_best),
                    subtitle = stringResource(R.string.shield_auto_mode_hint),
                    pingMs = servers.minByOrNull { pings[it.guid] ?: Long.MAX_VALUE }
                        ?.let { pings[it.guid] },
                    selected = autoMode,
                    onClick = onSelectAuto,
                )
            }
            items(servers, key = { it.guid }) { server ->
                ServerRow(
                    flag = server.flag,
                    title = server.title,
                    subtitle = server.subtitle,
                    pingMs = pings[server.guid],
                    selected = !autoMode && server.guid == selectedGuid,
                    onClick = { onSelect(server.guid) },
                )
            }
        }
    }
}

@Composable
private fun ServerRow(
    flag: String,
    title: String,
    subtitle: String,
    pingMs: Long?,
    selected: Boolean,
    onClick: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .selectable(selected = selected, role = Role.Button, onClick = onClick)
            .padding(horizontal = 24.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(text = flag, fontSize = 22.sp)
        Column(
            modifier = Modifier
                .weight(1f)
                .padding(start = 12.dp),
        ) {
            Text(
                text = title,
                color = Color.White,
                fontSize = 15.sp,
                fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = subtitle,
                color = TextMuted,
                fontSize = 11.sp,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        Spacer(Modifier.width(12.dp))
        PingLabel(pingMs = pingMs, pinging = false)
        if (selected) {
            Spacer(Modifier.width(8.dp))
            Box(
                modifier = Modifier
                    .size(10.dp)
                    .clip(CircleShape)
                    .background(AccentGreen),
            )
        }
    }
}
