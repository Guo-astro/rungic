// SPDX-License-Identifier: MIT
package com.rungic.plasma;

import java.io.IOException;

/** Whether a failed controller call means the root provider has not granted Rungic root, so the
 * app can say where to grant it instead of a generic start failure. KernelSU shows su only to the
 * apps allowed in its manager (starting su fails: no such file); Magisk's su answers a denied
 * request with strerror(EACCES) and exits with it (13; 1 from older clients). Plain Java (tests/RootAccessTest runs without Android). */
final class RootAccess {
    private RootAccess() {}

    enum Provider { MAGISK, KERNELSU, UNKNOWN }

    static boolean denied(Throwable failure) {
        if(failure instanceof ControlException) {
            ControlException error=(ControlException)failure;
            return (error.exitCode==13 || error.exitCode==1) && error.lastLine().equals("Permission denied");
        }
        if(!(failure instanceof IOException))return false;
        String message=String.valueOf(failure.getMessage());
        return message.startsWith("Cannot run program \"") && (message.contains("error=2,") || message.contains("error=13,"));
    }

    /** The provider first boot recorded in the install status (root=, rungic-firstboot.sh). */
    static Provider provider(String recorded) {
        if("kernelsu".equals(recorded))return Provider.KERNELSU;
        if("magisk".equals(recorded))return Provider.MAGISK;
        return Provider.UNKNOWN;
    }
}
