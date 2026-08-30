"""Small, application-owned language catalog.

The application deliberately keeps this module lightweight.  Interface copy is
selected once when the application starts, while answer-language metadata is
read by the DeepSeek service for every request.  Keeping those two concerns
separate prevents a Settings edit from partially retranslating already-built
Qt widgets.
"""

from __future__ import annotations

from typing import Mapping


SUPPORTED_LANGUAGES = ("en", "zh-CN")
SUPPORTED_LANGUAGE_CODES = SUPPORTED_LANGUAGES
DEFAULT_INTERFACE_LANGUAGE = "en"
DEFAULT_ANSWER_LANGUAGE = "zh-CN"

LANGUAGE_DISPLAY_NAMES: Mapping[str, str] = {
    "en": "English",
    "zh-CN": "简体中文",
}


# The key set is intentionally shared by both catalogs.  Keeping all product
# owned UI copy here makes catalog parity a deterministic unit-test invariant.
_EN = {
    "settings.window_title": "TellMeSensei Settings",
    "settings.title": "Settings",
    "settings.subtitle": "Configure TellMeSensei for your workflow.",
    "settings.shortcuts_title": "Shortcuts",
    "settings.language_title": "Language",
    "settings.updates_title": "Updates",
    "settings.debug_title": "Debug",
    "settings.interface_language": "Interface language",
    "settings.answer_language": "Answer language",
    "settings.language_description": (
        "Choose the interface language and the language used for new AI answers."
    ),
    "settings.restart_required": (
        "Interface language changes take effect after restarting TellMeSensei."
    ),
    "settings.deepseek_description": "Configure the AI service used for analysis.",
    "settings.shortcuts_description": (
        "Choose the global shortcuts for Text/OCR, Vision, Watch, and Context Watch."
    ),
    "settings.ocr_description": "Select the OCR provider used by Text mode.",
    "settings.local_ocr_description": (
        "Manage the on-device OCR component and its native engine."
    ),
    "settings.local_ocr_summary": "On-device text recognition component.",
    "settings.google_vision_description": (
        "Configure online OCR through Google Cloud Vision."
    ),
    "settings.google_vision_summary": "Online OCR service configuration.",
    "settings.auto_watch_description": (
        "Tune automatic change detection and analysis timing."
    ),
    "settings.updates_description": (
        "Check GitHub Releases and open the newest installer for this device."
    ),
    "settings.debug_description": (
        "Inspect the latest TellMeSensei runtime log for troubleshooting."
    ),
    "settings.api_key_placeholder": "Enter DeepSeek API Key",
    "settings.google_api_key_placeholder": "Enter Google Vision API Key",
    "settings.interface_language_restart": "Restart required for interface language.",
    "settings.language_english": "English",
    "settings.language_simplified_chinese": "简体中文",
    "settings.engine": "Engine",
    "settings.service": "Service",
    "settings.local": "Local",
    "settings.online": "Online",
    "settings.api_key": "API Key",
    "settings.text_model": "Text Model",
    "settings.request_timeout": "Request Timeout",
    "settings.ocr_provider": "OCR Provider",
    "settings.manage": "Manage",
    "settings.download": "Download",
    "settings.cancel": "Cancel",
    "settings.verify": "Verify",
    "settings.remove_local_ocr": "Remove Local OCR",
    "settings.test_google_vision": "Test Google Vision",
    "settings.test_connection": "Test Connection",
    "settings.save": "Save",
    "settings.close": "Cancel",
    "settings.analysis_mode": "Analysis mode",
    "settings.detection_interval": "Detection interval",
    "settings.pixel_delta_threshold": "Pixel delta threshold",
    "settings.new_question_ratio": "New-question ratio",
    "settings.stability_ratio": "Stability ratio",
    "settings.stable_samples_required": "Stable samples required",
    "settings.analysis_delay": "Analysis delay",
    "settings.auto_watch_ratios_help": (
        "Ratios are stored as 0–1 values. Lower thresholds detect smaller changes."
    ),
    "settings.restore_defaults": "Restore Defaults",
    "settings.current_version": "Current version",
    "settings.latest_version": "Latest version",
    "settings.not_checked": "Not checked",
    "settings.update_status": (
        "Check for the newest stable TellMeSensei application release."
    ),
    "settings.check_updates": "Check for Updates",
    "settings.update": "Update",
    "settings.refresh": "Refresh",
    "settings.ready_log": "No runtime log has been written yet.",
    "settings.log_read_error": "Unable to read the runtime log.",
    "settings.log_empty": "Runtime log is empty.",
    "settings.log_lines": "Showing the latest {count} log lines (bounded to {size} KB).",
    "settings.expected_stability": (
        "Expected stable confirmation: {milliseconds} ms "
        "(actual timing also depends on page changes)."
    ),
    "settings.local_ocr_privacy": "Screenshots are processed on this device.",
    "settings.online_ocr_privacy": (
        "Online OCR. Screenshots will be uploaded to Google Cloud Vision for OCR."
    ),
    "settings.local_ocr_unsupported": (
        "Local OCR for macOS is not installed/supported in this build."
    ),
    "settings.local_ocr_no_distribution": (
        "Local OCR is supported on this Mac, but no component distribution is configured yet."
    ),
    "settings.local_ocr_installed": "Installed · v{version}",
    "settings.local_ocr_not_installed": "Not installed",
    "settings.download_size": "Download size: {size:.1f} MB",
    "settings.local_ocr_preparing": "Local OCR is preparing. Please try again in a moment.",
    "settings.local_ocr_in_use": (
        "Local OCR is currently in use. Please wait for recognition to finish."
    ),
    "settings.local_ocr_incomplete": "Local OCR installation is incomplete.",
    "settings.local_ocr_verifying": "Verifying…",
    "settings.local_ocr_smoke_failed": "Local OCR smoke test failed.",
    "settings.local_ocr_verified": "Installed · v{version} · verified",
    "settings.remove_local_ocr_question": "Remove the installed Local OCR component?",
    "settings.error_remove_local_ocr": "Failed to remove Local OCR: {detail}",
    "settings.download_error": "Error: {detail}",
    "settings.download_cancelled": "Download cancelled",
    "settings.cancelling": "Cancelling…",
    "settings.testing": "Testing…",
    "settings.downloading": "Downloading…",
    "settings.verifying": "Verifying…",
    "settings.installing": "Installing…",
    "settings.downloading_version": "Downloading TellMeSensei {version}…",
    "settings.checking": "Checking…",
    "settings.checking_releases": "Checking GitHub Releases…",
    "settings.update_available": "TellMeSensei {version} is available.",
    "settings.up_to_date": "TellMeSensei is up to date.",
    "settings.unavailable": "Unavailable",
    "settings.update_check_cancelled": "Update check cancelled.",
    "settings.update_check_failed": "Unable to check for application updates.",
    "settings.update_error": "Unable to complete the update operation: {detail}",
    "settings.update_download_cancelled": "Update download cancelled.",
    "settings.update_download_failed": "Unable to download or open the application update.",
    "settings.update_package_opened": (
        "Update package opened. Complete the installer to finish updating."
    ),
    "settings.update_to": "Update to {version}",
    "settings.api_key_env_override": (
        "The current API Key is overridden by the DEEPSEEK_API_KEY environment variable. "
        "Saving a new API Key in Settings will not change the key currently in use."
    ),
    "settings.google_api_key_env_override": (
        "Google Vision API Key is currently controlled by the GOOGLE_VISION_API_KEY "
        "environment variable. Saving a different key will not change the key currently in use."
    ),
    "settings.ocr_provider_env_override": (
        "OCR Provider is controlled by the OCR_PROVIDER environment variable."
    ),
    "settings.validation_model_empty": "Model cannot be empty.",
    "settings.validation_timeout": "Request timeout must be positive.",
    "settings.validation_shortcuts": "All shortcuts must be different.",
    "settings.validation_one_shortcut": "A shortcut must contain one key combination.",
    "settings.wait_ocr_before_connection": (
        "Wait for the active OCR operation to finish before testing the connection."
    ),
    "settings.wait_operation_before_google": (
        "Wait for the active operation to finish before testing Google Vision."
    ),
    "settings.enter_api_key": "Enter an API Key before testing the connection.",
    "settings.enter_google_api_key": "Enter a Google Vision API Key first.",
    "settings.connection_testing": "Testing connection…",
    "settings.connection_success": "Connection successful.",
    "settings.connection_internal_error": "An internal error occurred during the connection test.",
    "settings.saved": "Settings saved.",
    "settings.shortcut_registration_failed": (
        "Shortcut registration failed; another application may already be using it."
    ),
    "settings.download_local_ocr_unavailable": (
        "Local OCR is not installed/supported in this build."
    ),
    "settings.download_local_ocr_no_distribution": (
        "Local OCR is supported on this Mac, but no component distribution is configured yet."
    ),
    "settings.download_wait_test": (
        "Wait for the active OCR or connection test to finish before downloading Local OCR."
    ),
    "settings.google_connection_success": "Google Vision connection successful.",
    "settings.google_connection_failed": "Google Vision connection test failed.",
    "controller.settings_tooltip": "Settings",
    "controller.text_description": "Text extraction",
    "controller.vision_description": "Visual analysis",
    "controller.watch_description": "Single region",
    "controller.context_watch_description": "Context + question",
    "controller.text_tooltip": "Capture a question for text extraction",
    "controller.vision_tooltip": "Capture a question for visual analysis",
    "controller.watch_tooltip": "Watch one screen region for new questions",
    "controller.context_watch_tooltip": "Watch a context region and a question region",
    "controller.status_capturing": "●  Capturing…",
    "controller.status_processing": "●  Processing…",
    "controller.status_cancelling": "●  Cancelling…",
    "controller.status_auto_watch_error": "●  {message}",
    "controller.capture_overlay_error": "Unable to start screen capture: {detail}",
    "controller.screen_permission_title": "Screen Recording Permission Required",
    "controller.screen_permission_body": (
        "TellMeSensei needs Screen Recording permission to capture the screen.\n\n"
        "Please enable TellMeSensei in:\n"
        "System Settings / System Preferences\n"
        "→ Privacy & Security\n"
        "→ Screen Recording\n\n"
        "Then restart TellMeSensei."
    ),
    "capture.no_screen": "No display is available.",
    "error.deepseek_empty_ocr": "OCR did not recognize usable text; DeepSeek cannot be requested.",
    "error.deepseek_empty_question_ocr": "Question OCR did not recognize usable text; DeepSeek cannot be requested.",
    "error.deepseek_empty_image": "The screenshot is empty; DeepSeek Vision cannot be requested.",
    "error.deepseek_png_only": "Vision Mode currently supports PNG screenshots only.",
    "error.deepseek_empty_answer": "DeepSeek returned an empty answer.",
    "error.deepseek_missing_api_key": "No DeepSeek API Key is configured. Save one in Settings.",
    "error.deepseek_missing_api_key_env": (
        "No DeepSeek API Key is configured. Save one in Settings or check the .env file."
    ),
    "error.deepseek_missing_openai": "The openai dependency is missing. Run python -m pip install -r requirements.txt.",
    "error.deepseek_401": "The DeepSeek API Key is invalid (401). Check the API Key in Settings.",
    "error.deepseek_403": "DeepSeek API access was denied (403). Check account permissions or the API Key.",
    "error.deepseek_429": "DeepSeek API requests are too frequent (429). Please try again later.",
    "error.deepseek_5xx": "DeepSeek is temporarily unavailable ({status_code}). Please try again later.",
    "error.deepseek_timeout": "The DeepSeek API request timed out. Check the network and try again.",
    "error.deepseek_connection": "Could not connect to the DeepSeek API. Check the network connection.",
    "error.deepseek_generic": "DeepSeek API request failed. Check the network, API Key, and model configuration.",
    "answer.title_text": "Text / OCR Analysis",
    "answer.title_vision": "Vision Analysis",
    "answer.status_ready": "●  Ready",
    "answer.status_recognizing": "◌  Recognizing text…",
    "answer.status_analyzing": "◌  Analyzing…",
    "answer.status_analyzing_image": "◌  Analyzing image…",
    "answer.status_cancelling": "◌  Cancelling…",
    "answer.status_cancelled": "■  Cancelled",
    "answer.status_completed": "✓  Analysis completed",
    "answer.status_copied": "✓  Copied",
    "answer.status_failed": "!  Analysis failed",
    "answer.recognized_question": "Recognized Question",
    "answer.recognized_text_placeholder": "Recognized text will appear here.",
    "answer.recognized_context_placeholder": "Recognized context will appear here.",
    "answer.recognized_question_placeholder": "Recognized question will appear here.",
    "answer.analysis_placeholder": "The analysis will appear here.",
    "answer.copy": "Copy",
    "answer.retry": "Retry",
    "answer.stop": "Stop",
    "answer.recapture": "Recapture",
    "answer.close": "Close",
    "answer.auto_watch_analyzing": "Auto Watch · Analyzing…",
    "answer.new_question_analyzing": "New question detected · Analyzing…",
    "answer.completed": "Completed",
    "answer.analysis_cancelled": "Analysis cancelled",
    "answer.cancelled_body": "Cancelled; no AI answer was generated.",
    "answer.failure_body": "AI analysis failed.\n{message}",
    "tray.text_capture": "Text / OCR Capture",
    "tray.vision_capture": "Vision Capture",
    "tray.show_controller": "Show Controller",
    "tray.settings": "Settings",
    "tray.quit": "Quit",
    "watch.status_arming": "Arming",
    "watch.status_watching": "Watching",
    "watch.status_paused": "Paused",
    "watch.status_changing": "Changing",
    "watch.status_stopped": "Stopped",
    "watch.analysis_ready": "Ready for changes",
    "watch.analysis_waiting": "Waiting to analyze",
    "watch.analysis_analyzing": "Analyzing…",
    "watch.analysis_context": "Recognizing Context…",
    "watch.analysis_question": "Recognizing Question…",
    "watch.analysis_completed": "Last analysis completed",
    "watch.analysis_cancelled": "Analysis cancelled",
    "watch.analysis_failed": "Analysis failed",
    "watch.analyze_now": "Analyze Now",
    "watch.pause": "Pause",
    "watch.resume": "Resume",
    "watch.stop": "Stop",
    "watch.error_screen_changed": "The screen is unavailable or the display configuration changed.",
    "watch.error_empty_capture": "The screen capture is empty.",
    "watch.error_invalid_context": "Context selection is no longer available.",
    "watch.error_select_context": "Please select the Context region first.",
    "watch.error_same_screen": (
        "Context and Question must be on the same display. Please select the Question region again."
    ),
    "watch.error_start": "Unable to start Auto Watch.",
    "watch.error_empty_pair_capture": "The Context and Question capture is empty.",
    "watch.generation_pair": "Pair {generation}",
}

_ZH_CN = {
    "settings.window_title": "TellMeSensei 设置",
    "settings.title": "设置",
    "settings.subtitle": "根据你的使用习惯配置 TellMeSensei。",
    "settings.shortcuts_title": "快捷键",
    "settings.language_title": "语言",
    "settings.updates_title": "更新",
    "settings.debug_title": "调试",
    "settings.interface_language": "界面语言",
    "settings.answer_language": "回答语言",
    "settings.language_description": "选择界面语言，以及新 AI 回答使用的语言。",
    "settings.restart_required": "界面语言修改将在重启 TellMeSensei 后生效。",
    "settings.deepseek_description": "配置用于分析的 AI 服务。",
    "settings.shortcuts_description": "选择 Text/OCR、Vision、Watch 和 Context Watch 的全局快捷键。",
    "settings.ocr_description": "选择 Text 模式使用的 OCR 服务。",
    "settings.local_ocr_description": "管理本机 OCR 组件及其原生引擎。",
    "settings.local_ocr_summary": "本机文字识别组件。",
    "settings.google_vision_description": "配置通过 Google Cloud Vision 使用的在线 OCR。",
    "settings.google_vision_summary": "在线 OCR 服务配置。",
    "settings.auto_watch_description": "调整自动变化检测和分析时序。",
    "settings.updates_description": "检查 GitHub Releases，并打开适用于本设备的最新安装包。",
    "settings.debug_description": "查看最近的 TellMeSensei 运行日志以排查问题。",
    "settings.api_key_placeholder": "输入 DeepSeek API Key",
    "settings.google_api_key_placeholder": "输入 Google Vision API Key",
    "settings.interface_language_restart": "修改界面语言需要重启应用。",
    "settings.language_english": "English",
    "settings.language_simplified_chinese": "简体中文",
    "settings.engine": "引擎",
    "settings.service": "服务",
    "settings.local": "本机",
    "settings.online": "在线",
    "settings.api_key": "API Key",
    "settings.text_model": "Text Model",
    "settings.request_timeout": "Request Timeout",
    "settings.ocr_provider": "OCR Provider",
    "settings.manage": "管理",
    "settings.download": "下载",
    "settings.cancel": "取消",
    "settings.verify": "验证",
    "settings.remove_local_ocr": "移除 Local OCR",
    "settings.test_google_vision": "测试 Google Vision",
    "settings.test_connection": "测试连接",
    "settings.save": "保存",
    "settings.close": "取消",
    "settings.analysis_mode": "分析模式",
    "settings.detection_interval": "检测间隔",
    "settings.pixel_delta_threshold": "像素变化阈值",
    "settings.new_question_ratio": "新题比例",
    "settings.stability_ratio": "稳定比例",
    "settings.stable_samples_required": "所需稳定采样数",
    "settings.analysis_delay": "分析延迟",
    "settings.auto_watch_ratios_help": "比例按 0–1 存储。更低的阈值会检测到更小的变化。",
    "settings.restore_defaults": "恢复默认值",
    "settings.current_version": "当前版本",
    "settings.latest_version": "最新版本",
    "settings.not_checked": "尚未检查",
    "settings.update_status": "检查最新的稳定版 TellMeSensei 应用。",
    "settings.check_updates": "检查更新",
    "settings.update": "更新",
    "settings.refresh": "刷新",
    "settings.ready_log": "尚未写入运行日志。",
    "settings.log_read_error": "无法读取运行日志。",
    "settings.log_empty": "运行日志为空。",
    "settings.log_lines": "显示最近 {count} 行日志（上限 {size} KB）。",
    "settings.expected_stability": "预计稳定确认：{milliseconds} ms（实际时序还取决于页面变化）。",
    "settings.local_ocr_privacy": "截图会在本机处理。",
    "settings.online_ocr_privacy": "在线 OCR。截图会上传到 Google Cloud Vision 进行 OCR。",
    "settings.local_ocr_unsupported": "此构建未安装/不支持 macOS Local OCR。",
    "settings.local_ocr_no_distribution": "此 Mac 支持 Local OCR，但尚未配置组件分发源。",
    "settings.local_ocr_installed": "已安装 · v{version}",
    "settings.local_ocr_not_installed": "未安装",
    "settings.download_size": "下载大小：{size:.1f} MB",
    "settings.local_ocr_preparing": "Local OCR 正在准备，请稍后重试。",
    "settings.local_ocr_in_use": "Local OCR 正在使用中，请等待识别完成。",
    "settings.local_ocr_incomplete": "Local OCR 安装不完整。",
    "settings.local_ocr_verifying": "验证中…",
    "settings.local_ocr_smoke_failed": "Local OCR smoke test 失败。",
    "settings.local_ocr_verified": "已安装 · v{version} · 已验证",
    "settings.remove_local_ocr_question": "移除已安装的 Local OCR 组件？",
    "settings.error_remove_local_ocr": "移除 Local OCR 失败：{detail}",
    "settings.download_error": "错误：{detail}",
    "settings.download_cancelled": "下载已取消",
    "settings.cancelling": "取消中…",
    "settings.testing": "测试中…",
    "settings.downloading": "下载中…",
    "settings.verifying": "验证中…",
    "settings.installing": "安装中…",
    "settings.downloading_version": "正在下载 TellMeSensei {version}…",
    "settings.checking": "检查中…",
    "settings.checking_releases": "正在检查 GitHub Releases…",
    "settings.update_available": "TellMeSensei {version} 可用。",
    "settings.up_to_date": "TellMeSensei 已是最新版本。",
    "settings.unavailable": "不可用",
    "settings.update_check_cancelled": "更新检查已取消。",
    "settings.update_check_failed": "无法检查应用更新。",
    "settings.update_error": "无法完成更新操作：{detail}",
    "settings.update_download_cancelled": "更新下载已取消。",
    "settings.update_download_failed": "无法下载或打开应用更新。",
    "settings.update_package_opened": "更新安装包已打开，请完成安装以结束更新。",
    "settings.update_to": "更新到 {version}",
    "settings.api_key_env_override": (
        "当前 API Key 由 DEEPSEEK_API_KEY 环境变量覆盖。在设置中保存新的 API Key 不会改变当前实际使用的 Key。"
    ),
    "settings.google_api_key_env_override": (
        "当前 Google Vision API Key 由 GOOGLE_VISION_API_KEY 环境变量覆盖。在设置中保存新的 Key 不会改变当前实际使用的 Key。"
    ),
    "settings.ocr_provider_env_override": "OCR Provider 由 OCR_PROVIDER 环境变量控制。",
    "settings.validation_model_empty": "Model 不能为空。",
    "settings.validation_timeout": "Request timeout 必须是正数。",
    "settings.validation_shortcuts": "快捷键不能重复。",
    "settings.validation_one_shortcut": "快捷键只能包含一个组合。",
    "settings.wait_ocr_before_connection": "请等待当前 OCR 操作完成后再测试连接。",
    "settings.wait_operation_before_google": "请等待当前操作完成后再测试 Google Vision。",
    "settings.enter_api_key": "请输入 API Key 后再测试连接。",
    "settings.enter_google_api_key": "请先输入 Google Vision API Key。",
    "settings.connection_testing": "正在测试连接…",
    "settings.connection_success": "连接成功。",
    "settings.connection_internal_error": "连接测试过程中发生内部错误。",
    "settings.saved": "设置已保存。",
    "settings.shortcut_registration_failed": "快捷键注册失败，可能已被其他程序占用。",
    "settings.download_local_ocr_unavailable": "此构建未安装/不支持 Local OCR。",
    "settings.download_local_ocr_no_distribution": "此 Mac 支持 Local OCR，但尚未配置组件分发源。",
    "settings.download_wait_test": "请等待当前 OCR 或连接测试完成后再下载 Local OCR。",
    "settings.google_connection_success": "Google Vision 连接成功。",
    "settings.google_connection_failed": "Google Vision 连接测试失败。",
    "controller.settings_tooltip": "设置",
    "controller.text_description": "提取文字",
    "controller.vision_description": "视觉分析",
    "controller.watch_description": "单区域监控",
    "controller.context_watch_description": "上下文 + 题目监控",
    "controller.text_tooltip": "框选题目并进行文字提取",
    "controller.vision_tooltip": "框选题目并进行视觉分析",
    "controller.watch_tooltip": "监控一个屏幕区域中的新题目",
    "controller.context_watch_tooltip": "监控上下文区域和题目区域",
    "controller.status_capturing": "●  框选中…",
    "controller.status_processing": "●  处理中…",
    "controller.status_cancelling": "●  取消中…",
    "controller.status_auto_watch_error": "●  {message}",
    "controller.capture_overlay_error": "无法开始截图：{detail}",
    "controller.screen_permission_title": "需要屏幕录制权限",
    "controller.screen_permission_body": (
        "TellMeSensei 需要屏幕录制权限才能截图。\n\n"
        "请在以下位置启用 TellMeSensei：\n"
        "系统设置 / 系统偏好设置\n"
        "→ 隐私与安全性\n"
        "→ 屏幕录制\n\n"
        "然后重启 TellMeSensei。"
    ),
    "capture.no_screen": "没有可用的显示器。",
    "error.deepseek_empty_ocr": "OCR 未识别到有效文字，无法请求 DeepSeek。",
    "error.deepseek_empty_question_ocr": "Question OCR 未识别到有效文字，无法请求 DeepSeek。",
    "error.deepseek_empty_image": "截图内容为空，无法请求 DeepSeek Vision。",
    "error.deepseek_png_only": "Vision Mode 当前只支持 PNG 截图。",
    "error.deepseek_empty_answer": "DeepSeek 返回了空答案。",
    "error.deepseek_missing_api_key": "未配置 DeepSeek API Key，请在设置中保存 API Key。",
    "error.deepseek_missing_api_key_env": "未配置 DeepSeek API Key，请在设置中保存 API Key，或检查 .env 配置。",
    "error.deepseek_missing_openai": "未安装 openai 依赖，请先执行 python -m pip install -r requirements.txt。",
    "error.deepseek_401": "DeepSeek API Key 无效（401），请前往设置检查 API Key。",
    "error.deepseek_403": "DeepSeek API 访问被拒绝（403），请检查账户权限或 API Key。",
    "error.deepseek_429": "DeepSeek API 请求过于频繁（429），请稍后重试。",
    "error.deepseek_5xx": "DeepSeek 服务暂时不可用（{status_code}），请稍后重试。",
    "error.deepseek_timeout": "DeepSeek API 请求超时，请检查网络后重试。",
    "error.deepseek_connection": "连接 DeepSeek API 失败，请检查网络连接。",
    "error.deepseek_generic": "DeepSeek API 请求失败，请检查网络、API Key 和模型配置。",
    "answer.title_text": "Text / OCR 分析",
    "answer.title_vision": "Vision 分析",
    "answer.status_ready": "●  Ready",
    "answer.status_recognizing": "◌  识别文字中…",
    "answer.status_analyzing": "◌  分析中…",
    "answer.status_analyzing_image": "◌  分析图像中…",
    "answer.status_cancelling": "◌  取消中…",
    "answer.status_cancelled": "■  已取消",
    "answer.status_completed": "✓  分析完成",
    "answer.status_copied": "✓  已复制",
    "answer.status_failed": "!  分析失败",
    "answer.recognized_question": "识别出的题目",
    "answer.recognized_text_placeholder": "识别出的文字会显示在这里。",
    "answer.recognized_context_placeholder": "识别出的上下文会显示在这里。",
    "answer.recognized_question_placeholder": "识别出的题目会显示在这里。",
    "answer.analysis_placeholder": "分析结果会显示在这里。",
    "answer.copy": "复制",
    "answer.retry": "重试",
    "answer.stop": "停止",
    "answer.recapture": "重新截图",
    "answer.close": "关闭",
    "answer.auto_watch_analyzing": "Auto Watch · 分析中…",
    "answer.new_question_analyzing": "检测到新题目 · 分析中…",
    "answer.completed": "完成",
    "answer.analysis_cancelled": "分析已取消",
    "answer.cancelled_body": "已取消，未生成 AI 答案。",
    "answer.failure_body": "AI 解析失败。\n{message}",
    "tray.text_capture": "Text / OCR 截图",
    "tray.vision_capture": "Vision 截图",
    "tray.show_controller": "显示控制器",
    "tray.settings": "设置",
    "tray.quit": "退出",
    "watch.status_arming": "准备中",
    "watch.status_watching": "监控中",
    "watch.status_paused": "已暂停",
    "watch.status_changing": "变化中",
    "watch.status_stopped": "已停止",
    "watch.analysis_ready": "等待变化",
    "watch.analysis_waiting": "等待分析",
    "watch.analysis_analyzing": "分析中…",
    "watch.analysis_context": "识别 Context 中…",
    "watch.analysis_question": "识别 Question 中…",
    "watch.analysis_completed": "上次分析已完成",
    "watch.analysis_cancelled": "分析已取消",
    "watch.analysis_failed": "分析失败",
    "watch.analyze_now": "立即分析",
    "watch.pause": "暂停",
    "watch.resume": "继续",
    "watch.stop": "停止",
    "watch.error_screen_changed": "屏幕不可用或显示器配置已改变。",
    "watch.error_empty_capture": "屏幕截图为空。",
    "watch.error_invalid_context": "Context 选择已不可用。",
    "watch.error_select_context": "请先选择 Context 区域。",
    "watch.error_same_screen": "Context 和 Question 必须位于同一显示器，请重新选择 Question 区域。",
    "watch.error_start": "无法启动 Auto Watch。",
    "watch.error_empty_pair_capture": "Context 和 Question 截图为空。",
    "watch.generation_pair": "组 {generation}",
}


CATALOGS: Mapping[str, Mapping[str, str]] = {"en": _EN, "zh-CN": _ZH_CN}
TRANSLATIONS = CATALOGS


def normalize_language(value: object, default: str = DEFAULT_INTERFACE_LANGUAGE) -> str:
    """Return a supported language code or the supplied supported default."""

    if default not in SUPPORTED_LANGUAGES:
        raise ValueError(f"unsupported language default: {default}")
    if isinstance(value, str) and value.strip() in SUPPORTED_LANGUAGES:
        return value.strip()
    return default


def language_display_name(language: str) -> str:
    """Return the stable display name for one supported language code."""

    return LANGUAGE_DISPLAY_NAMES[normalize_language(language)]


def tr(key: str, language: str = DEFAULT_INTERFACE_LANGUAGE, **values: object) -> str:
    """Look up and format one application-owned string.

    Unknown keys intentionally raise ``KeyError``.  A missing key should be
    fixed in the catalog rather than silently falling back and creating a
    partially bilingual screen.
    """

    normalized = normalize_language(language)
    try:
        template = CATALOGS[normalized][key]
    except KeyError as exc:
        raise KeyError(f"missing translation key: {key!r} ({normalized})") from exc
    try:
        return template.format(**values)
    except (KeyError, IndexError, ValueError) as exc:
        raise ValueError(f"invalid values for translation key: {key!r}") from exc


def answer_language_instruction(language: str) -> str:
    """Return the explicit answer-language contract appended to every prompt."""

    normalized = normalize_language(language, default=DEFAULT_ANSWER_LANGUAGE)
    if normalized == "en":
        return (
            "Output language:\n"
            "- English.\n"
            "- Use English regardless of the language used in the source question.\n"
            "- Use these headings: 【Answer】, 【Explanation】, 【Key Points】."
        )
    return (
        "输出语言：\n"
        "- 简体中文。\n"
        "- 无论题目使用什么语言，都必须使用简体中文回答。\n"
        "- 使用以下标题：【答案】、【解析】、【知识点】。"
    )


def answer_language_headings(language: str) -> tuple[str, str, str]:
    """Return the three headings requested by the configured answer language."""

    normalized = normalize_language(language, default=DEFAULT_ANSWER_LANGUAGE)
    if normalized == "en":
        return ("【Answer】", "【Explanation】", "【Key Points】")
    return ("【答案】", "【解析】", "【知识点】")


def catalog_keys() -> frozenset[str]:
    """Return the canonical translation-key set for parity tests."""

    return frozenset(_EN)


__all__ = [
    "CATALOGS",
    "DEFAULT_ANSWER_LANGUAGE",
    "DEFAULT_INTERFACE_LANGUAGE",
    "LANGUAGE_DISPLAY_NAMES",
    "SUPPORTED_LANGUAGES",
    "SUPPORTED_LANGUAGE_CODES",
    "TRANSLATIONS",
    "answer_language_headings",
    "answer_language_instruction",
    "catalog_keys",
    "language_display_name",
    "normalize_language",
    "tr",
]
