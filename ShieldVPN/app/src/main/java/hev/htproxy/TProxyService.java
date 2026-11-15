package hev.htproxy;

/**
 * JNI entry points expected by the prebuilt hev-socks5-tunnel library.
 *
 * <p>The official AAR ships {@code libhev-socks5-tunnel.so}, whose
 * {@code JNI_OnLoad()} registers its natives on this exact class
 * ({@code hev/htproxy/TProxyService}). The app's wrapper lives in
 * {@code com.v2ray.ang.service.TProxyService}, so without this shim
 * {@code FindClass()} fails, {@code JNI_OnLoad} returns {@code JNI_ERR} and the
 * {@code :daemon} process dies with {@link UnsatisfiedLinkError} before
 * tun2socks ever starts.
 *
 * <p>Signatures must stay identical to the ones in the AAR's {@code classes.jar}:
 * {@code boolean (String, int)}, {@code boolean ()}, {@code boolean ()},
 * {@code long[] ()}.
 */
@SuppressWarnings("unused")
public final class TProxyService {

    private TProxyService() {
    }

    static {
        System.loadLibrary("hev-socks5-tunnel");
    }

    public static native boolean TProxyStartService(String configPath, int fd);

    public static native boolean TProxyStopService();

    public static native boolean TProxyIsRunning();

    public static native long[] TProxyGetStats();
}
