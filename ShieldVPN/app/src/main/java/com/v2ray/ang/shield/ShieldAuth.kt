package com.v2ray.ang.shield

import android.content.Context
import com.google.android.gms.tasks.Task
import com.google.firebase.FirebaseApp
import com.google.firebase.auth.FirebaseAuth
import com.google.firebase.auth.FirebaseUser
import com.google.firebase.auth.GoogleAuthProvider
import com.google.firebase.firestore.FirebaseFirestore
import com.v2ray.ang.BuildConfig
import com.v2ray.ang.util.LogUtil
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.suspendCancellableCoroutine
import java.security.MessageDigest
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

data class ShieldAuthState(
    val signedIn: Boolean = false,
    val email: String? = null,
    val name: String? = null,
    /** Firebase UID; null in local (non-Firebase) mode. */
    val uid: String? = null,
    val loading: Boolean = false,
    val error: String? = null,
    /** Non-fatal hint, for example "Firebase не настроен — включён локальный режим". */
    val info: String? = null,
    /** True when the build contains Firebase credentials and the SDK is usable. */
    val firebaseAvailable: Boolean = false,
)

/**
 * Account gate for ShieldVPN.
 *
 * With Firebase configured (`FIREBASE_API_KEY` / `FIREBASE_APP_ID` /
 * `FIREBASE_PROJECT_ID` Gradle properties) the screen performs real
 * Email/Password and Google sign-in, and mirrors the subscription token into
 * Firestore under `users/{uid}` so the same account can restore its access.
 *
 * Without credentials — a plain local build, CI without secrets, or F-Droid —
 * the same screen keeps working in local mode: the first sign-in creates a
 * SHA-256 password hash in MMKV and the following ones verify it. That keeps the
 * "VPN only after sign-in" product rule testable without a Google project.
 */
object ShieldAuth {

    private const val TAG = "ShieldVPN"
    private const val MIN_PASSWORD = 6

    private val _state = MutableStateFlow(ShieldAuthState())
    val state: StateFlow<ShieldAuthState> = _state.asStateFlow()

    private var appContext: Context? = null

    /** Reads the current session and attaches the Firebase listener when possible. */
    fun initialize(context: Context) {
        appContext = context.applicationContext
        val firebase = firebaseEnabled(context)
        _state.value = ShieldAuthState(
            signedIn = ShieldPrefs.isSignedIn(),
            email = ShieldPrefs.authEmail(),
            name = ShieldPrefs.authName(),
            uid = ShieldPrefs.authUid(),
            firebaseAvailable = firebase,
            info = if (firebase) null else LOCAL_HINT,
        )
        if (!firebase) return
        runCatching {
            FirebaseAuth.getInstance().addAuthStateListener { auth ->
                val user = auth.currentUser
                if (user == null && _state.value.signedIn && _state.value.email == null) {
                    _state.value = _state.value.copy(signedIn = false, uid = null)
                } else if (user != null) {
                    persistSession(user.email ?: user.displayName, user.displayName, user.uid)
                    _state.value = _state.value.copy(
                        signedIn = true,
                        email = user.email ?: _state.value.email,
                        name = user.displayName ?: _state.value.name,
                        uid = user.uid,
                    )
                }
            }
        }.onFailure { LogUtil.w(TAG, "Firebase auth listener failed: ${it.message}") }
    }

    fun clearError() {
        _state.value = _state.value.copy(error = null)
    }

    /** Surfaces an error produced outside the repository (e.g. Credential Manager). */
    fun reportError(message: String) {
        _state.value = _state.value.copy(loading = false, error = message)
    }

    /**
     * Email + password entry point.
     *
     * @param register true when the user pressed "Создать аккаунт".
     */
    suspend fun signInWithEmail(email: String, password: String, register: Boolean = false) {
        val normalized = email.trim().lowercase()
        _state.value = _state.value.copy(loading = true, error = null, info = _state.value.info)
        try {
            validate(normalized, password)
            if (firebaseEnabled(appContext)) {
                firebaseEmail(normalized, password, register)
            } else {
                localEmail(normalized, password)
            }
            _state.value = _state.value.copy(
                loading = false,
                signedIn = true,
                email = normalized,
                uid = ShieldPrefs.authUid(),
                error = null,
            )
            syncSubscriptionIdentity()
        } catch (t: Throwable) {
            _state.value = _state.value.copy(
                loading = false,
                error = t.message ?: "Не удалось войти",
            )
        }
    }

    /** Completes Google sign-in once the Activity received an ID token. */
    suspend fun signInWithGoogleToken(idToken: String) {
        _state.value = _state.value.copy(loading = true, error = null)
        try {
            if (!firebaseEnabled(appContext)) error("Google-вход недоступен: Firebase не настроен")
            val credential = GoogleAuthProvider.getCredential(idToken, null)
            val result = FirebaseAuth.getInstance().signInWithCredential(credential).await()
            val user = result.user ?: error("Google-вход не вернул пользователя")
            persistSession(user.email ?: user.displayName, user.displayName, user.uid)
            _state.value = _state.value.copy(
                loading = false,
                signedIn = true,
                email = user.email,
                name = user.displayName,
                uid = user.uid,
                error = null,
            )
            syncSubscriptionIdentity()
        } catch (t: Throwable) {
            _state.value = _state.value.copy(
                loading = false,
                error = t.message ?: "Google-вход не удался",
            )
        }
    }

    fun signOut() {
        runCatching { FirebaseAuth.getInstance().signOut() }
        ShieldPrefs.setSignedIn(false)
        ShieldPrefs.setAuthEmail(null)
        ShieldPrefs.setAuthName(null)
        ShieldPrefs.setAuthSecret(null)
        ShieldPrefs.setAuthUid(null)
        _state.value = _state.value.copy(
            signedIn = false,
            email = null,
            name = null,
            uid = null,
            error = null,
        )
    }

    /** Firebase web client id used by Credential Manager. Empty when not configured. */
    fun webClientId(): String = BuildConfig.FIREBASE_WEB_CLIENT_ID

    // ------------------------------------------------------------------ internals

    private fun firebaseEnabled(context: Context?): Boolean {
        if (!BuildConfig.FIREBASE_ENABLED || context == null) return false
        return runCatching { FirebaseApp.getApps(context).isNotEmpty() }.getOrDefault(false)
    }

    private suspend fun firebaseEmail(email: String, password: String, register: Boolean) {
        val auth = FirebaseAuth.getInstance()
        val result = if (register) {
            auth.createUserWithEmailAndPassword(email, password).await()
        } else {
            auth.signInWithEmailAndPassword(email, password).await()
        }
        val user = result.user ?: error("Firebase не вернул пользователя")
        persistSession(user.email ?: email, user.displayName, user.uid)
    }

    private fun localEmail(email: String, password: String) {
        val secret = sha256(password)
        val stored = ShieldPrefs.authSecret()
        if (stored == null) {
            ShieldPrefs.setAuthSecret(secret)
        } else if (stored != secret) {
            error("Неверный пароль для $email")
        }
        // Local mode has no Firebase UID: the panel is asked with the e-mail.
        persistSession(email, email.substringBefore('@'), null)
    }

    private fun persistSession(email: String?, name: String?, uid: String?) {
        ShieldPrefs.setAuthEmail(email)
        ShieldPrefs.setAuthName(name)
        ShieldPrefs.setAuthUid(uid)
        ShieldPrefs.setSignedIn(true)
    }

    private fun validate(email: String, password: String) {
        if (!EMAIL.matches(email)) error("Введите корректный e-mail")
        if (password.length < MIN_PASSWORD) {
            error("Пароль должен быть не короче $MIN_PASSWORD символов")
        }
    }

    /**
     * Mirrors the per-account subscription identity into Firestore so the same
     * account can restore access on a new device. No shared token is stored any
     * more: the panel URL is derived from the UID on every launch.
     */
    private fun syncSubscriptionIdentity() {
        if (!firebaseEnabled(appContext)) return
        val user = runCatching { FirebaseAuth.getInstance().currentUser }.getOrNull() ?: return
        runCatching {
            val data = mapOf(
                "email" to (user.email ?: ""),
                "subscriptionUser" to user.uid,
                "subscriptionUrl" to ShieldConfig.subscriptionUrl(user.uid),
                "updatedAt" to System.currentTimeMillis(),
            )
            FirebaseFirestore.getInstance()
                .collection("users")
                .document(user.uid)
                .set(data)
        }.onFailure { LogUtil.w(TAG, "Firestore subscription sync failed: ${it.message}") }
    }

    private fun sha256(value: String): String = MessageDigest.getInstance("SHA-256")
        .digest(value.toByteArray())
        .joinToString("") { "%02x".format(it) }

    private val EMAIL = Regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$")

    private val LOCAL_HINT =
        "Firebase не настроен: включён локальный режим входа (пароль хранится только на устройстве)."

    private suspend fun <T> Task<T>.await(): T = suspendCancellableCoroutine { continuation ->
        addOnCompleteListener { task ->
            if (task.isSuccessful) {
                continuation.resume(task.result)
            } else {
                continuation.resumeWithException(
                    task.exception ?: IllegalStateException("Ошибка Firebase"),
                )
            }
        }
    }
}
