#pragma once
#include <cstdint>

namespace deskclock {
enum class Language : uint8_t { English, TraditionalChinese, Japanese };

inline Language next_language(Language language) {
  switch (language) {
    case Language::English: return Language::TraditionalChinese;
    case Language::TraditionalChinese: return Language::Japanese;
    default: return Language::English;
  }
}

inline const char *language_name(Language language) {
  switch (language) {
    case Language::TraditionalChinese: return "繁體中文";
    case Language::Japanese: return "日本語";
    default: return "English";
  }
}

enum class Text {
  SetTime, DailyAlarm, UsbPair, Display, Language, Menu, AlarmRinging,
  StopQuestion, KeepRinging, ConfirmStop, StopRing, ChooseKeys, ChangeKeys, AdjustKeys,
  BackMenu, UsbConnect, UsbRun, Year, Month, Day, Hour,
  MinuteTens, MinuteOnes, Adjust, AlarmTime, SetAlarmTime, Resume, SkipNext,
  SkippedThis, Waiting, DisableAlarm, AlarmSwitch, AlarmOn, AlarmOff, Am,
  Pm, ClimateFormat, Enabled, Disabled, RemoteChanged, Skipped, OpenMenu,
  Alarm, Cancel, Confirm, Time, Date, AlarmStatus, Reminders,
  Calendar, Battery, Environment, Hours24, Hours12, FullDate, ShortDate,
  Shown, Hidden,
};

inline const char *translate(Language language, Text text) {
  auto pick = [language](const char *en, const char *zh, const char *ja) {
    switch (language) {
      case Language::TraditionalChinese: return zh;
      case Language::Japanese: return ja;
      default: return en;
    }
  };
  switch (text) {
    case Text::SetTime: return pick("Set time", "設定時間", "時刻設定");
    case Text::DailyAlarm: return pick("Daily alarm", "每日鬧鐘", "毎日のアラーム");
    case Text::UsbPair: return pick("USB pairing", "USB 配對", "USB ペアリング");
    case Text::Display: return pick("Display settings", "顯示設定", "表示設定");
    case Text::Language: return pick("Language", "語言", "言語");
    case Text::Menu: return pick("Menu", "選單", "メニュー");
    case Text::AlarmRinging: return pick("Alarm ringing", "鬧鐘響鈴", "アラーム鳴動中");
    case Text::StopQuestion: return pick("Stop this alarm?", "停止這次響鈴？", "今回のアラームを止めますか？");
    case Text::KeepRinging: return pick("Keep ringing", "繼續響鈴", "鳴らし続ける");
    case Text::ConfirmStop: return pick("Stop alarm", "確認停止", "停止する");
    case Text::StopRing: return pick("● Stop alarm", "● 停止響鈴", "● アラーム停止");
    case Text::ChooseKeys: return pick("＋ Select   ● OK   × Back", "＋ 選擇   ● 確定   × 返回", "＋ 選択   ● 決定   × 戻る");
    case Text::ChangeKeys: return pick("＋ Select   ● Change   × Back", "＋ 選擇   ● 切換   × 返回", "＋ 選択   ● 切替   × 戻る");
    case Text::AdjustKeys: return pick("＋ Adjust   ● OK   × Cancel", "＋ 調整   ● 確定   × 取消", "＋ 調整   ● 決定   × 取消");
    case Text::BackMenu: return pick("× Back to menu", "× 返回選單", "× メニューに戻る");
    case Text::UsbConnect: return pick("Connect a USB data cable", "用資料線連接電腦", "USB ケーブルでパソコンに接続");
    case Text::UsbRun: return pick("Run the pairing tool on your PC", "在電腦執行配對工具", "パソコンでペアリングツールを実行");
    case Text::Year: return pick("Year", "年份", "年");
    case Text::Month: return pick("Month", "月份", "月");
    case Text::Day: return pick("Day", "日期", "日");
    case Text::Hour: return pick("Hour", "小時", "時");
    case Text::MinuteTens: return pick("Minutes (tens)", "分鐘十位", "分（十の位）");
    case Text::MinuteOnes: return pick("Minutes (ones)", "分鐘個位", "分（一の位）");
    case Text::Adjust: return pick("Adjust", "調整", "調整");
    case Text::AlarmTime: return pick("Alarm time", "響鈴時間", "アラーム時刻");
    case Text::SetAlarmTime: return pick("Set alarm time", "設定鬧鐘時間", "アラーム時刻を設定");
    case Text::Resume: return pick("Restore alarm", "恢復響鈴", "スキップ解除");
    case Text::SkipNext: return pick("Skip next", "跳過下一次", "次回スキップ");
    case Text::SkippedThis: return pick("Already skipped", "本次已跳過", "今回はスキップ済み");
    case Text::Waiting: return pick("Waiting for time", "等待校時", "時刻合わせ待ち");
    case Text::DisableAlarm: return pick("Disable alarm", "取消鬧鈴", "アラームを無効にする");
    case Text::AlarmSwitch: return pick("Alarm on/off", "鬧鐘開關", "アラームのオン／オフ");
    case Text::AlarmOn: return pick("Alarm on", "鬧鐘已啟用", "アラーム有効");
    case Text::AlarmOff: return pick("Alarm off", "鬧鐘已停用", "アラーム無効");
    case Text::Am: return pick("AM", "上午", "午前");
    case Text::Pm: return pick("PM", "下午", "午後");
    case Text::ClimateFormat: return pick("Temp %s°C   Humidity %s%%", "溫度 %s°C   濕度 %s%%", "温度 %s°C   湿度 %s%%");
    case Text::Enabled: return pick("On", "已啟用", "有効");
    case Text::Disabled: return pick("Off", "已停用", "無効");
    case Text::RemoteChanged: return pick("Remote alarm changed or removed", "遠端已刪除或變更規則", "サーバーでアラーム変更・削除");
    case Text::Skipped: return pick("Skipped", "已跳過", "スキップ済み");
    case Text::OpenMenu: return pick("● Open menu", "● 進入選單", "● メニューを開く");
    case Text::Alarm: return pick("Alarm", "鬧鐘", "アラーム");
    case Text::Cancel: return pick("Cancel", "取消", "取消");
    case Text::Confirm: return pick("Confirm", "確認", "確認");
    case Text::Time: return pick("Time", "時間", "時刻");
    case Text::Date: return pick("Date", "日期", "日付");
    case Text::AlarmStatus: return pick("Alarm status", "鬧鐘狀態", "アラーム状態");
    case Text::Reminders: return pick("Reminders", "文字提醒", "リマインダー");
    case Text::Calendar: return pick("Calendar", "行事曆", "カレンダー");
    case Text::Battery: return pick("Battery voltage", "電池電壓", "電池電圧");
    case Text::Environment: return pick("Temp / humidity", "溫濕度", "温湿度");
    case Text::Hours24: return pick("24-hour", "24 小時", "24時間");
    case Text::Hours12: return pick("12-hour", "12 小時", "12時間");
    case Text::FullDate: return pick("Y/M/D", "年月日", "年月日");
    case Text::ShortDate: return pick("M/D", "月日", "月日");
    case Text::Shown: return pick("Shown", "顯示", "表示");
    case Text::Hidden: return pick("Hidden", "隱藏", "非表示");
  }
  return "";
}
}  // namespace deskclock
