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

    fun refreshServers() = controller.refreshServers()

    fun pingAll() = controller.pingAll()

    fun setAutoConnect(enabled: Boolean) = controller.setAutoConnect(enabled)

    fun setAutoMode(enabled: Boolean) = controller.setAutoMode(enabled)

    fun setByeDpiEnabled(enabled: Boolean) = controller.setByeDpiEnabled(enabled)

    fun reportPermissionDenied() = controller.reportPermissionDenied()

    override fun onCleared() {
        controller.detach()
        super.onCleared()
    }
}
