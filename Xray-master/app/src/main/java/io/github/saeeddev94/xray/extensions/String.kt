package io.github.saeeddev94.xray.extensions

import io.github.saeeddev94.xray.Xray
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject

fun String.decodeToJsonObject(): JsonObject = Xray.Json().decodeFromString<JsonObject>(this)

fun String.decodeToJsonArray(): JsonArray = Xray.Json().decodeFromString<JsonArray>(this)

fun String.formatJsonObject(): String = decodeToJsonObject().encodeToString()

fun String.formatJsonArray(): String = decodeToJsonArray().encodeToString()
