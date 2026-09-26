#include <QGuiApplication>
#include <QQmlApplicationEngine>
int main(int argc, char **argv){QGuiApplication a(argc,argv);QQmlApplicationEngine e;e.loadData(R"(
import QtQuick
import QtQuick.Controls
ApplicationWindow { width:360; height:720; visible:true; title:"输入验收"; color:"#eeeeee"
 Label {text:"输入测试，不会发送到网络"; anchors.top:parent.top; anchors.topMargin:40; anchors.horizontalCenter:parent.horizontalCenter}
 TextField {id:edit; objectName:"testField"; x:20;y:140;width:320;placeholderText:"点击测试中英文输入"; onTextChanged: console.log("RUNGIC_INPUT_LENGTH", text.length, "CHINESE", /[\\u4e00-\\u9fff]/.test(text))}
 Label {x:20;y:210;text:edit.text}
}
)");return a.exec();}
