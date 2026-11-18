package com.v2ray.ang.shield

import android.content.Context
import android.os.Build
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

    /**
     * Kills a ciadpi that outlived this app process.
     *
     * Android can recreate the app while the native child keeps running, so the pid
     * is persisted in [ShieldPrefs]. The command line is checked first, otherwise a
     * recycled pid could belong to an unrelated process.
     */
    private fun killOrphan() {
        val pid = ShieldPrefs.byeDpiPid()
        if (pid <= 0) return
        ShieldPrefs.setByeDpiPid(0)
        val commandLine = runCatching { File("/proc/$pid/cmdline").readText() }.getOrNull()
        if (commandLine == null || !commandLine.contains(BINARY_NAME)) return
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            runCatching { android.os.Process.sendSignal(pid, android.os.Process.SIGNAL_KILL) }
                .onFailure { LogUtil.w(TAG, "ByeDPI: cannot stop orphan $pid: ${it.message}") }
        }
    }

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
        if (process?.isAlive == true && isListening()) return true

        // A child started by a previous app process may still be listening. Drop it
        // first so the current arguments (and the tracked pid) take effect.
        if (ShieldPrefs.byeDpiPid() > 0) {
            killOrphan()
            Thread.sleep(120)
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
            ShieldPrefs.setByeDpiPid(pidOf(started))

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
        running?.let {
            runCatching {
                it.destroy()
                if (!it.waitFor(1, java.util.concurrent.TimeUnit.SECONDS)) {
                    it.destroyForcibly()
                }
            }.onFailure { error -> LogUtil.w(TAG, "ByeDPI stop failed: ${error.message}") }
        }
        killOrphan()
    }

    /**
     * Pid of a freshly started child, or 0 when it cannot be read.
     *
     * `java.lang.Process.pid()` is not part of the Android SDK in every compileSdk
     * revision, so the field is read reflectively (it is a plain int on ART).
     */
    private fun pidOf(process: Process): Int = try {
        val field = process.javaClass.getDeclaredField("pid").apply { isAccessible = true }
        field.getInt(process)
    } catch (_: Throwable) {
        runCatching {
            (process.javaClass.getMethod("pid").invoke(process) as Number).toInt()
        }.getOrDefault(0)
    }

    /** Restarts the proxy after the strategy changed. */
    @Synchronized
    fun restart(context: Context): Boolean {
        stop()
        return start(context)
    }
}
