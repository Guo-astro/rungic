// SPDX-License-Identifier: MIT
package com.rungic.plasma;

import java.io.File;

/** The app's reading of the install state (FirstBootState), for tools/tests/test_contract_host_controller.py:
 *  com.rungic.plasma.ContractFirstBootDriver SOURCE SEED STATUS prints what the startup screen would do, as one JSON line. */
final class ContractFirstBootDriver {
    public static void main(String[] args) {
        FirstBootState state=FirstBootState.readSource(new File(args[0]),new File(args[1]),new File(args[2]));
        System.out.println("{\"ready\":"+state.ready+",\"failed\":"+state.failed+",\"attention\":"+state.attention
            +",\"message\":\""+state.message+"\",\"reason\":"+(state.reason==null?"null":"\""+state.reason+"\"")
            +",\"phase\":\""+state.phase+"\",\"code\":\""+state.code+"\"}");
    }
}
