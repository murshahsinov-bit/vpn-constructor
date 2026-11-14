package io.github.saeeddev94.xray.helper

import io.github.saeeddev94.xray.Settings
import io.github.saeeddev94.xray.database.Config
import io.github.saeeddev94.xray.extensions.encodeToString
import io.github.saeeddev94.xray.extensions.putValue
import io.github.saeeddev94.xray.extensions.remove
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.jsonPrimitive

class ConfigHelper(
    settings: Settings,
    config: Config,
    base: String,
) {
    private var base: JsonObject = JsonHelper.makeObject(base)

    init {
        process("log", config.log, config.logMode)
        process("dns", config.dns, config.dnsMode)
        process("inbounds", config.inbounds, config.inboundsMode)
        process("outbounds", config.outbounds, config.outboundsMode)
        process("routing", config.routing, config.routingMode)

        if (settings.tproxyHotspot || settings.tproxyTethering) {
            sharedInbounds()
        }
    }

    override fun toString(): String = base.encodeToString()

    fun script(): String? {
        val key = "script"
        val value: String? = base[key]?.jsonPrimitive?.content
        base = base.remove(key)
        return value
    }

    private fun process(
        key: String,
        config: String,
        mode: Config.Mode,
    ) {
        if (mode == Config.Mode.Disable) return
        when (key == "inbounds" || key == "outbounds") {
            true -> processArray(key, config, mode)
            false -> processObject(key, config, mode)
        }
    }

    private fun processObject(
        key: String,
        config: String,
        mode: Config.Mode,
    ) {
        val oldValue = JsonHelper.getObject(base, key)
        val newValue = JsonHelper.makeObject(config)
        base = when (mode == Config.Mode.Replace) {
            true -> newValue
            false -> JsonHelper.mergeObjects(oldValue, newValue)
        }.let { base.putValue(key, it) }
    }

    private fun processArray(
        key: String,
        config: String,
        mode: Config.Mode,
    ) {
        val oldValue = JsonHelper.getArray(base, key)
        val newValue = JsonHelper.makeArray(config)
        base = when (mode == Config.Mode.Replace) {
            true -> newValue
            false -> JsonHelper.mergeArrays(oldValue, newValue, "protocol")
        }.let { base.putValue(key, it) }
    }

    private fun sharedInbounds() {
        val inbounds = JsonHelper.getArray(base, "inbounds")
        base = buildJsonArray {
            for (inbound in inbounds) {
                if (inbound is JsonObject) {
                    add(inbound.remove("listen"))
                }
            }
        }.let { base.putValue("inbounds", it) }
    }
}
