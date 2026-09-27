package com.rungic.plasma;

import android.os.SystemClock;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * Versions of the Android state the Linux side follows, bumped by Android's own callbacks, so the
 * Linux services wait for a change (platform bridge op "watch") instead of polling for it
 * (docs/49: polling for these cost a few % of a core at idle, on both sides).
 *
 * Topics: network (connectivity, Wi-Fi state and identity), telephony (service, signal level,
 * data), bluetooth (adapter, links, bonds, discovery), capture (desktop in front, permissions),
 * clipboard (Android's clipboard changed, or the desktop got the focus it needs to read it).
 * The epoch changes with every start of the app, so a watcher that saw an older one refreshes.
 */
final class HostEvents {
    static final String NETWORK="network", TELEPHONY="telephony", BLUETOOTH="bluetooth", CAPTURE="capture",
        CLIPBOARD="clipboard";
    static final String EPOCH=UUID.randomUUID().toString();
    private static final Map<String,Long> versions=new HashMap<>();

    private HostEvents() {}

    static void bump(String topic) {
        synchronized(versions) {
            versions.merge(topic,1L,Long::sum);
            versions.notifyAll();
        }
    }

    /** The versions of `seen`'s topics as soon as one differs from what the caller has seen (or the
     * epoch does), else after `timeoutMs`: {"epoch":…, "versions":{topic:n}, "changed":bool}. */
    static JSONObject await(JSONObject request,long timeoutMs) throws JSONException, InterruptedException {
        JSONObject seen=request.optJSONObject("seen");
        JSONArray topics=request.getJSONArray("topics");
        boolean sameEpoch=EPOCH.equals(request.optString("epoch"));
        long deadline=SystemClock.uptimeMillis()+timeoutMs;
        synchronized(versions) {
            while(true) {
                boolean changed=!sameEpoch || seen==null;
                JSONObject now=new JSONObject();
                for(int i=0;i<topics.length();i++) {
                    String topic=topics.getString(i);
                    long version=versions.getOrDefault(topic,0L);
                    now.put(topic,version);
                    if(seen!=null && seen.optLong(topic,-1)!=version)changed=true;
                }
                long left=deadline-SystemClock.uptimeMillis();
                if(changed || left<=0)return new JSONObject().put("epoch",EPOCH).put("versions",now).put("changed",changed);
                versions.wait(left);
            }
        }
    }
}
