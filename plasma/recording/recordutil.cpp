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
  n->setText(ok?m_output:(m_error.isEmpty()?QStringLiteral("录制未完成，请检查可用空间及硬件桥接。"):m_error));
  if(ok)n->setUrls({QUrl::fromLocalFile(m_output)});
  n->sendEvent();
 });
}
void RecordUtil::changed(){emit quickSettingTextChanged();emit quickSettingStatusChanged();emit isRecordingChanged();}
QString RecordUtil::quickSettingText() const{return m_stopping?QStringLiteral("正在保存…"):(m_running?QStringLiteral("正在录屏…"):QStringLiteral("录屏"));}
QString RecordUtil::quickSettingStatus() const{return m_stopping?QStringLiteral("请等待文件写入"):m_running?QStringLiteral("点击结束录屏"):QStringLiteral("点击录制 · 长按设置画质与声音");}
bool RecordUtil::startRecording(int nodeId){
 if(m_running || nodeId<=0)return false;
 const auto dir=QStandardPaths::writableLocation(QStandardPaths::MoviesLocation);
 if(!QDir().mkpath(dir))return false;
 const QString name=QStringLiteral("screen-recording.mp4");
 m_output=dir+'/'+name;
 for(int n=1;QFile::exists(m_output)||QFile::exists(m_output.chopped(4)+QStringLiteral(".partial.mp4"));++n)
  m_output=dir+QStringLiteral("/screen-recording (%1).mp4").arg(n);
 m_error.clear();m_pending.clear();
 m_process.start(QStringLiteral("/usr/local/bin/moto-screen-recorder"),{QString::number(nodeId),m_output});
 if(!m_process.waitForStarted(1000))return false;
 m_running=true;m_stopping=false;changed();return true;
}
void RecordUtil::stopRecording(){
 if(!m_running||m_stopping)return;
 m_stopping=true;changed();m_process.terminate();
 QTimer::singleShot(16000,this,[this]{if(m_stopping&&m_running){m_error=QStringLiteral("保存录屏超时，保留临时文件供恢复。");m_process.kill();}});
}
