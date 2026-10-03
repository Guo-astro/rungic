// SPDX-License-Identifier: MIT
// Test driver of Settings -> Services (tools/system/tests/services_page.py): loads the built KCM
// plugin as System Settings does (KQuickConfigModuleLoader), shows its page offscreen and prints, as
// one JSON object, what the page's backend reports and what its controls show.
//   show-page PLUGIN.so                 the page as it is
//   show-page PLUGIN.so cancel GROUP    then turns GROUP on and cancels the confirmation
#include <KPluginMetaData>
#include <KQuickConfigModule>
#include <KQuickConfigModuleLoader>

#include <QGuiApplication>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QQmlEngine>
#include <QQuickItem>
#include <QQuickWindow>
#include <QTimer>
#include <cstdio>

using namespace Qt::StringLiterals;

static void settle(int ms = 300)
{
    QEventLoop loop;
    QTimer::singleShot(ms, &loop, &QEventLoop::quit);
    loop.exec();
}

// Every control below `item` with the words it shows.
static void controls(QQuickItem *item, QJsonArray &out)
{
    const auto text = item->property("text"), description = item->property("description");
    if ((text.isValid() && !text.toString().isEmpty()) || (description.isValid() && !description.toString().isEmpty())) {
        QJsonObject control{{u"class"_s, QString::fromLatin1(item->metaObject()->className())},
                            {u"text"_s, text.toString()},
                            {u"description"_s, description.toString()},
                            {u"visible"_s, item->isVisible()},
                            {u"enabled"_s, item->isEnabled()}};
        if (item->metaObject()->indexOfProperty("checkable") >= 0 && item->property("checkable").toBool())
            control.insert(u"checked"_s, item->property("checked").toBool());
        out.append(control);
    }
    for (QQuickItem *child : item->childItems())
        controls(child, out);
}

static QQuickItem *findSwitch(QQuickItem *item, const QString &text)
{
    if (item->property("text").toString() == text && item->property("checkable").toBool())
        return item;
    for (QQuickItem *child : item->childItems())
        if (QQuickItem *found = findSwitch(child, text))
            return found;
    return nullptr;
}

int main(int argc, char **argv)
{
    QGuiApplication app(argc, argv);
    const QStringList args = app.arguments();
    auto engine = std::make_shared<QQmlEngine>();
    const auto loaded = KQuickConfigModuleLoader::loadModule(KPluginMetaData(args.value(1)), nullptr, {}, engine);
    if (!loaded) {
        std::fprintf(stderr, "cannot load %s: %s\n", qPrintable(args.value(1)), qPrintable(loaded.errorString));
        return 1;
    }
    KQuickConfigModule *kcm = loaded.plugin;
    QQuickItem *page = kcm->mainUi();
    if (!page) {
        std::fprintf(stderr, "no page: %s\n", qPrintable(kcm->errorString()));
        return 1;
    }
    QQuickWindow window;
    window.resize(400, 3000);
    page->setParentItem(window.contentItem());
    page->setSize(QSizeF(400, 3000));
    window.show();
    settle();

    QJsonObject result;
    if (args.value(2) == u"cancel") {
        // As a finger does it: the switch flips, then its clicked handler asks first (main.qml toggle()).
        const QString group = args.value(3);
        QString name;
        for (const auto &value : kcm->property("groups").toList())
            if (value.toMap().value(u"id"_s) == group)
                name = value.toMap().value(u"name"_s).toString();
        QQuickItem *toggle = findSwitch(page, name);
        if (!toggle) {
            std::fprintf(stderr, "no switch for %s\n", qPrintable(group));
            return 1;
        }
        QMetaObject::invokeMethod(toggle, "toggle");
        QMetaObject::invokeMethod(toggle, "clicked");
        settle();
        QObject *dialog = nullptr;
        for (QObject *object : page->findChildren<QObject *>())
            if (QString::fromLatin1(object->metaObject()->className()).contains(u"PromptDialog"_s))
                dialog = object;
        result.insert(u"confirmOpened"_s, dialog && dialog->property("opened").toBool());
        result.insert(u"confirmTitle"_s, dialog ? dialog->property("title").toString() : QString());
        result.insert(u"confirmText"_s, dialog ? dialog->property("subtitle").toString() : QString());
        if (dialog)
            QMetaObject::invokeMethod(dialog, "reject");
        settle(800);
        result.insert(u"busy"_s, kcm->property("busy").toBool());
        result.insert(u"switchChecked"_s, toggle->property("checked").toBool());
    }

    QJsonArray shown;
    controls(page, shown);
    result.insert(u"controls"_s, shown);
    result.insert(u"groups"_s, QJsonArray::fromVariantList(kcm->property("groups").toList()));
    result.insert(u"distributionMasks"_s, QJsonArray::fromStringList(kcm->property("distributionMasks").toStringList()));
    result.insert(u"otherMasks"_s, QJsonArray::fromVariantList(kcm->property("otherMasks").toList()));
    result.insert(u"addresses"_s, QJsonArray::fromStringList(kcm->property("addresses").toStringList()));
    result.insert(u"userName"_s, kcm->property("userName").toString());
    result.insert(u"hostKey"_s, kcm->property("hostKey").toString());
    result.insert(u"error"_s, kcm->property("error").toString());
    std::puts(QJsonDocument(result).toJson(QJsonDocument::Compact).constData());
    return 0;
}
