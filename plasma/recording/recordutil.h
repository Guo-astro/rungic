// SPDX-License-Identifier: GPL-2.0-or-later
// Backend of the recording quick setting (com.rungic.quicksetting.record, docs/73).
#pragma once
#include <QObject>
#include <QProcess>
#include <qqmlregistration.h>
class RecordUtil : public QObject {
 Q_OBJECT
 QML_ELEMENT
 QML_SINGLETON
 Q_PROPERTY(QString quickSettingText READ quickSettingText NOTIFY quickSettingTextChanged)
 Q_PROPERTY(QString quickSettingStatus READ quickSettingStatus NOTIFY quickSettingStatusChanged)
 Q_PROPERTY(bool isRecording READ isRecording NOTIFY isRecordingChanged)
public:
 explicit RecordUtil(QObject *parent=nullptr);
 Q_INVOKABLE bool startRecording(int nodeId);
 // [{node: int, label: string}], the phone first; one file per screen.
 Q_INVOKABLE bool startRecordingScreens(const QVariantList &screens);
 Q_INVOKABLE void stopRecording();
 QString quickSettingText() const;
 QString quickSettingStatus() const;
 bool isRecording() const {return m_running;}
signals:
 void quickSettingTextChanged(); void quickSettingStatusChanged(); void isRecordingChanged();
private:
 void changed();
 QProcess m_process;
 QStringList m_outputs;
 QString m_error;
 QByteArray m_pending;
 bool m_running=false,m_stopping=false;
};
