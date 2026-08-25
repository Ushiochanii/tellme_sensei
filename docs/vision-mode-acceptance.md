# Vision Mode acceptance checklist

This checklist is for v0.7.0 manual acceptance on a native supported target.

- [ ] `Ctrl+Shift+Q` captures a text-heavy question and runs OCR → DeepSeek text analysis.
- [ ] `Ctrl+Shift+W` captures a diagram-heavy question without invoking OCR.
- [ ] Vision requests use `deepseek-v4-flash-vision-exp` and the existing DeepSeek API key.
- [ ] The Vision answer appears in the shared AnswerWindow without an empty OCR section.
- [ ] Vision **重新分析** sends the same in-memory screenshot through Vision again.
- [ ] Vision **重新截图** opens another Vision capture.
- [ ] While Text is processing, the Vision shortcut does not start a second job, and vice versa.
- [ ] Text and Vision shortcuts can be changed independently in Settings.
- [ ] Saving identical Text and Vision shortcuts is rejected.
- [ ] Tray actions are distinct; tray double-click remains Text Mode.
- [ ] Closing the app unregisters both global hotkeys.
