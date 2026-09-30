.pragma library
function number(value) { return value === undefined || value === null ? "尚无记录" : Number(value).toLocaleString(Qt.locale("zh_CN"), "f", 0) }
function mode(data) { return ({apiKey: "API Key", chatgpt: "ChatGPT", none: "未登录"})[data.authMode] || "正在连接" }
function windowName(w) {
    const m = w.windowDurationMins
    return !m ? "额度窗口" : m >= 1440 ? (m / 1440) + " 天额度" : m >= 60 ? (m / 60) + " 小时额度" : m + " 分钟额度"
}
function reset(w, now) {
    if (!w.resetsAt) return "未提供重置时间"
    const mins = Math.ceil((w.resetsAt - now) / 60)
    if (mins <= 0) return "重置时间已到，等待更新"
    return (mins >= 60 ? Math.floor(mins / 60) + " 小时 " : "") + (mins % 60) + " 分钟后重置"
}
function token(data) { return data.recordedTokens === undefined || data.recordedTokens === null ? "尚未收到用量记录" : "本机已记录 " + number(data.recordedTokens) + " token" }
