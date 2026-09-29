// SPDX-License-Identifier: GPL-2.0-or-later
// Pictures and files an answer points at (docs/88). Codex answers in Markdown and points at
// files on this phone by path: ![说明](</home/…/a.png>) for a picture, [名字](/home/…/b.blend)
// for a file. A text view cannot load a bare path (it resolves against the app's own qrc base),
// so the pictures come out of the text and are shown as Thumbnails, and local links get file://
// URLs that open. parse(text, home) → { text, images: [{url, name}], files: [{url, name}] };
// `home` is the home folder as a file:// URL (for ~/ paths).
.pragma library

var PICTURE = /\.(png|jpe?g|webp|gif|bmp|svg)$/i
// A link destination: <anything on one line> or a run without spaces and parentheses; an
// optional "title" after it.
var DEST = '(<[^>\\n]+>|[^\\s()]+)(?:\\s+"[^"]*")?'

// The file:// URL of a local target, or "" for anything else (web links stay as they are).
function localUrl(target, home) {
    var path = target.trim()
    if (path.charAt(0) === "<" && path.charAt(path.length - 1) === ">")
        path = path.slice(1, -1).trim()
    if (path.indexOf("file://") === 0)
        path = decodeURIComponent(path.slice(7))
    else if (path.indexOf("~/") === 0 && home)
        path = decodeURIComponent(String(home).replace(/^file:\/\//, "")) + path.slice(1)
    if (path.charAt(0) !== "/")
        return ""
    return "file://" + path.split("/").map(encodeURIComponent).join("/")
}

function baseName(url) {
    var parts = url.split("/")
    return decodeURIComponent(parts[parts.length - 1])
}

function parse(text, home) {
    var images = [], files = [], seen = {}
    function add(list, url) {
        if (seen[url])
            return
        seen[url] = true
        list.push({ url: url, name: baseName(url) })
    }
    var body = String(text || "")
    body = body.replace(new RegExp("!\\[([^\\]]*)\\]\\(\\s*" + DEST + "\\s*\\)", "g"), function (whole, alt, target) {
        var url = localUrl(target, home)
        if (!url)
            return whole
        add(PICTURE.test(url) ? images : files, url)
        return ""
    })
    body = body.replace(new RegExp("\\[([^\\]]*)\\]\\(\\s*" + DEST + "\\s*\\)", "g"), function (whole, label, target) {
        var url = localUrl(target, home)
        if (!url)
            return whole
        add(PICTURE.test(url) ? images : files, url)
        return "[" + label + "](" + url + ")"
    })
    body = body.replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim()
    return { text: body, images: images, files: files }
}
