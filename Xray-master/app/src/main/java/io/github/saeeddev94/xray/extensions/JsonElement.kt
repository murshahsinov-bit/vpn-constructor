package io.github.saeeddev94.xray.extensions

import io.github.saeeddev94.xray.Xray
import kotlinx.serialization.json.JsonElement

fun JsonElement.encodeToString(): String = Xray.Json()
    .encodeToString(JsonElement.serializer(), this)
