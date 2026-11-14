package com.v2ray.ang.shield

import android.app.Application
import androidx.lifecycle.AndroidViewModel

/**
 * Keeps the controller (and therefore an in-flight failover) alive across
 * configuration changes such as screen rotation.
 */
class ShieldViewModel(application: Application) : AndroidViewModel(application) {

    private val controller = ShieldVpnController(application.applicationContext)

    val state = controller.state

    init {
        controller.attach()
    }

    fun connect(preferredGuid: String?) = controller.connect(preferredGuid)

    fun disconnect() = controller.disconnect()

    fun refreshSubscription() = controller.refreshSubscription()

    fun setAutoConnect(enabled: Boolean) = controller.setAutoConnect(enabled)

    fun reportPermissionDenied() = controller.reportPermissionDenied()

    override fun onCleared() {
        controller.detach()
        super.onCleared()
    }
}
