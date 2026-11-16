package com.v2ray.ang.shield

import android.content.Context
import com.v2ray.ang.util.LogUtil
import java.io.File
import java.net.InetSocketAddress
import java.net.Socket

/**
 * Runs the ByeDPI bypass proxy (`ciadpi`) as a plain userspace process.
 *
 * Why a separate process instead of a JNI library: ciadpi is a self-contained
 * static binary, so a `ProcessBuilder` gives us the exact behaviour of the
 * upstream CLI (strategies, auto mode, logging) with zero JNI glue. The binary is
 * shipped as `libciadpi.so` so that Android extracts it into `nativeLibraryDir`,
 * the only app-owned directory that is mounted executable.
 *
 * ByeDPI never touches the system VPN: it only listens on 127.0.0.1:1080 and Xray
 * routes the YouTube domains there. Everything else keeps using the VLESS tunnel.
 */
object ShieldByeDpi {

    private const val TAG = "ShieldVPN"
    private const val BINARY_NAME = "libciadpi.so"
    private const val START_ATTEMPTS = 25
    private const val START_DELAY_MS = 100L

    @Volatile
    private var process: Process? = null

    @Volatile
    private var logFile: File? = null

    /** Absolute path of the extracted ciadpi binary, or null when the ABI is not bundled. */
    fun binary(context: Context): File? {
        val file = File(context.applicationInfo.nativeLibraryDir, BINARY_NAME)
        return file.takeIf { it.isFile && it.canExecute() }
    }

    fun isListening(): Boolean = try {
        Socket().use { socket ->
            socket.connect(
                InetSocketAddress(ShieldConfig.BYEDPI_HOST, ShieldConfig.BYEDPI_PORT),
                250,
            )
        }
        true
    } catch (_: Exception) {
        false
    }

    fun isRunning(): Boolean = process?.isAlive == true && isListening()

    /** Last lines of the ciadpi log, for the diagnostics screen. */
    fun lastLogLines(context: Context, limit: Int = 40): String {
        val file = logFile ?: File(context.cacheDir, "byedpi.log")
        return runCatching {
            file.readLines().takeLast(limit).joinToString("\n")
        }.getOrDefault("")
    }

    /**
     * Starts the proxy if it is enabled and not running yet.
     *
     * @return true when the SOCKS5 listener is ready.
     */
    @Synchronized
    fun start(context: Context): Boolean {
        if (!ShieldPrefs.isByeDpiEnabled()) {
            stop()
            return false
        }
        if (isListening()) return true

        val binary = binary(context)
        if (binary == null) {
            LogUtil.w(TAG, "ByeDPI: $BINARY_NAME is missing for this ABI")
            return false
        }

        val args = mutableListOf(
            binary.absolutePath,
            "-i", ShieldConfig.BYEDPI_HOST,
            "-p", ShieldConfig.BYEDPI_PORT.toString(),
        )
        args += ShieldPrefs.byeDpiArgs()
            .split(Regex("\\s+"))
            .filter { it.isNotBlank() }

        return try {
            val log = File(context.cacheDir, "byedpi.log").apply {
                parentFile?.mkdirs()
                writeText("starting: ${args.joinToString(" ")}\n")
            }
            val builder = ProcessBuilder(args)
                .redirectErrorStream(true)
                .redirectOutput(ProcessBuilder.Redirect.appendTo(log))
            val started = builder.start()
            process = started
            logFile = log

            repeat(START_ATTEMPTS) { attempt ->
                if (isListening()) {
                    LogUtil.i(TAG, "ByeDPI listening on ${ShieldConfig.BYEDPI_HOST}:${ShieldConfig.BYEDPI_PORT}")
                    return true
                }
                if (!started.isAlive) {
                    LogUtil.e(TAG, "ByeDPI exited: ${lastLogLines(context, 10)}")
                    return false
                }
                if (attempt < START_ATTEMPTS - 1) Thread.sleep(START_DELAY_MS)
            }
            LogUtil.w(TAG, "ByeDPI did not open the port in time")
            stop()
            false
        } catch (t: Throwable) {
            LogUtil.e(TAG, "ByeDPI start failed: ${t.message}", t)
            process = null
            false
        }
    }

    @Synchronized
    fun stop() {
        val running = process
        process = null
        if (running == null) return
        runCatching {
            running.destroy()
            if (!running.waitFor(1, java.util.concurrent.TimeUnit.SECONDS)) {
                running.destroyForcibly()
            }
        }.onFailure { LogUtil.w(TAG, "ByeDPI stop failed: ${it.message}") }
    }

    /** Restarts the proxy after the strategy changed. */
    @Synchronized
    fun restart(context: Context): Boolean {
        stop()
        return start(context)
    }
}
