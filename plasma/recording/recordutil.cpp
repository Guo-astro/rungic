// SPDX-License-Identifier: GPL-2.0-or-later
#include "recordutil.h"
#include <QDir>
#include <QStandardPaths>
#include <QTimer>
#include <KFileUtils>
#include <KNotification>
#include <KLocalizedString>

RecordUtil::RecordUtil(QObject *parent):QObject(parent){
 m_process.setProcessChannelMode(QProcess::MergedChannels);
 connect(&m_process,&QProcess::readyReadStandardOutput,this,[this]{
  m_pending+=m_process.readAllStandardOutput();
  while(m_pending.contains('\n')){auto line=m_pending.left(m_pending.indexOf('\n'));m_pending.remove(0,line.size()+1);
   qInfo().noquote()<<"Screen recording:"<<line;
   if(line.startsWith("ERROR ")){m_error=QString::fromUtf8(line.mid(6));}
  }
 });
 connect(&m_process,qOverload<int,QProcess::ExitStatus>(&QProcess::finished),this,[this](int code,QProcess::ExitStatus status){
  const bool ok=code==0 && status==QProcess::NormalExit;
  m_running=false;m_stopping=false;changed();
  auto *n=new KNotification(QStringLiteral("captured"));
  n->setComponentName(QStringLiteral("plasma_mobile_quicksetting_record"));
  n->setTitle(ok?QStringLiteral("录屏已保存"):QStringLiteral("录屏失败"));
  n->setText(ok?m_outputs.join(QLatin1Char('\n')):(m_error.isEmpty()?QStringLiteral("录制未完成，请检查可用空间及硬件桥接。"):m_error));
  if(ok){QList<QUrl> urls;for(const auto &o:m_outputs)urls<<QUrl::fromLocalFile(o);n->setUrls(urls);}
  n->sendEvent();
 });
}
void RecordUtil::changed(){emit quickSettingTextChanged();emit quickSettingStatusChanged();emit isRecordingChanged();}
QString RecordUtil::quickSettingText() const{return m_stopping?QStringLiteral("正在保存…"):(m_running?QStringLiteral("正在录屏…"):QStringLiteral("录屏"));}
QString RecordUtil::quickSettingStatus() const{return m_stopping?QStringLiteral("请等待文件写入"):m_running?QStringLiteral("点击结束录屏"):QStringLiteral("点击录制 · 长按设置画质与声音");}
bool RecordUtil::startRecording(int nodeId){
 return startRecordingScreens({QVariantMap{{QStringLiteral("node"),nodeId},{QStringLiteral("label"),QString()}}});
}
bool RecordUtil::startRecordingScreens(const QVariantList &screens){
 if(m_running || screens.isEmpty())return false;
 const auto dir=QStandardPaths::writableLocation(QStandardPaths::MoviesLocation);
 if(!QDir().mkpath(dir))return false;
 // One screen keeps the old name; several screens share a numbered base name
 // with the screen as suffix, e.g. "screen-recording (2) - 外屏.mp4".
 auto names=[&](int n){
  const QString base=n?QStringLiteral("screen-recording (%1)").arg(n):QStringLiteral("screen-recording");
  QStringList out;
  for(const auto &s:screens){
   const QString label=s.toMap().value(QStringLiteral("label")).toString();
   out<<dir+'/'+base+(screens.size()>1&&!label.isEmpty()?QStringLiteral(" - ")+label:QString())+QStringLiteral(".mp4");
  }
  return out;
 };
 auto taken=[](const QStringList &paths){
  for(const auto &p:paths)if(QFile::exists(p)||QFile::exists(p.chopped(4)+QStringLiteral(".partial.mp4")))return true;
  return false;
 };
 int n=0;
 while(taken(names(n)))++n;
 m_outputs=names(n);
 QStringList args;
 for(int i=0;i<screens.size();++i){
  const int node=screens.at(i).toMap().value(QStringLiteral("node")).toInt();
  if(node<=0)return false;
  args<<QString::number(node)<<m_outputs.at(i);
 }
 m_error.clear();m_pending.clear();
 m_process.start(QStringLiteral("/usr/bin/moto-screen-recorder"),args);
 if(!m_process.waitForStarted(1000))return false;
 m_running=true;m_stopping=false;changed();return true;
}
void RecordUtil::stopRecording(){
 if(!m_running||m_stopping)return;
 m_stopping=true;changed();m_process.terminate();
 QTimer::singleShot(16000,this,[this]{if(m_stopping&&m_running){m_error=QStringLiteral("保存录屏超时，保留临时文件供恢复。");m_process.kill();}});
}
