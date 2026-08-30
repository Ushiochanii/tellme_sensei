# Language Preferences Design

Status: Draft for design review

## 1. Background

TellMeSensei currently has two different language behaviors mixed together:

- most product UI labels are English, with some user-facing status/error strings still hard-coded in Chinese;
- DeepSeek Text, Vision, and Context + Question prompts are hard-coded in Chinese and strongly bias every answer toward Chinese, regardless of the question language or the user's preference.

This is acceptable for the original single-user workflow, but it is not suitable for a general release. A user should be able to choose both the language of the application interface and the language used for AI explanations.

The existing `ocr_language` setting is an OCR recognition hint and is not a UI/answer language preference. It remains a separate concept.

## 2. Problem statement

A non-Chinese user can run the application with an English-looking interface and still receive a Chinese answer because the DeepSeek prompts are fixed in Chinese. At the same time, some status/error messages can unexpectedly appear in Chinese inside otherwise English UI.

A single global `Language` option would not fully solve this because interface language and answer language are independent user choices.

Examples of valid combinations:

- English interface + English answers
- English interface + Simplified Chinese answers
- Simplified Chinese interface + English answers
- Simplified Chinese interface + Simplified Chinese answers

The language of the source question must not silently override the configured answer language.

## 3. Goals

1. Add persistent `Interface language` and `Answer language` preferences to Settings.
2. Support English (`en`) and Simplified Chinese (`zh-CN`) in the first implementation.
3. Make Text, Vision, and Context + Question analysis obey `Answer language` consistently.
4. Localize ordinary user-facing UI/status/error copy according to `Interface language`.
5. Keep established product/technical vocabulary in English where translation would reduce clarity or change the product identity.
6. Preserve existing behavior for current installations unless the user changes the new preferences.
7. Keep the implementation small and native to the current Python/PySide6 architecture; do not introduce a heavy localization framework for two languages.

## 4. Non-goals

This feature does not include:

- automatic system-locale detection;
- automatic answer-language detection from question content;
- Japanese UI or Japanese answer-language support in the first version;
- Qt `.ts` / `.qm` translation infrastructure;
- downloadable language packs;
- changing OCR provider selection or `ocr_language` behavior;
- translating third-party product names, model names, API names, or technical identifiers;
- changing the actual reasoning/answer quality beyond language control.

Additional languages may be added later by extending the same small language catalog if real demand appears.

## 5. Current architecture relevant to this change

- `app/settings/repository.py` persists allow-listed non-sensitive settings in `settings.json`.
- `app/config.py` assembles one immutable `AppConfig` for runtime jobs.
- `app/services/deepseek_service.py` owns Text, Vision, and Context + Question prompt construction and user-facing DeepSeek errors.
- `app/ui/settings_window.py` owns Settings UI copy and persistence actions.
- `app/ui/main_window.py`, `app/ui/answer_window.py`, tray/watch UI classes, and related UI modules contain product-owned labels/status strings.

The feature should extend those existing responsibilities rather than creating a parallel settings or prompt subsystem.

## 6. Proposed user model

### 6.1 Settings

Add a `Language` section/page with two independent selectors:

```text
Language

Interface language
[ English ▼ ]

Answer language
[ 简体中文 ▼ ]
```

First-version values:

| Setting | Stored value | Display label |
|---|---|---|
| Interface language | `en` | English |
| Interface language | `zh-CN` | 简体中文 |
| Answer language | `en` | English |
| Answer language | `zh-CN` | 简体中文 |

### 6.2 Defaults and upgrade behavior

To preserve the application's current effective behavior:

```text
interface_language = en
answer_language = zh-CN
```

Existing installations with no language keys therefore continue to see the mostly-English interface and Chinese AI explanations after upgrading.

New installations initially use the same defaults. Changing the product's new-user default can be a later product decision; it should not be hidden inside this implementation.

### 6.3 Apply behavior

- `Answer language` applies to the next analysis request after Settings is saved.
- `Interface language` is persisted immediately and takes effect after TellMeSensei is restarted.
- Settings must state clearly that an application restart is required for interface-language changes.

This avoids introducing a runtime retranslation lifecycle across already-constructed Qt widgets solely for the first two-language implementation.

## 7. Language-invariant product vocabulary

The following established product/technical terms remain English in both interface languages unless a later design explicitly changes them:

- TellMeSensei
- Text / OCR
- Vision
- Watch
- Context Watch
- Ready
- Context
- Question
- Answer
- Local OCR
- PaddleOCR
- Google Cloud Vision
- DeepSeek
- API Key
- model names and environment-variable names

The main floating controller therefore keeps its current core vocabulary and visual identity in both interface languages. The AnswerWindow structural labels `Context`, `Question`, and `Answer` also remain English so the application's main information structure stays consistent across interface languages.

Supporting descriptions around those terms may be localized where they are ordinary prose. For example, a Chinese interface may keep `Context Watch` as the card title while translating explanatory tooltips or Settings help text.

## 8. Localized UI scope

Ordinary product-owned copy should follow `Interface language`, including where applicable:

- Settings page titles, descriptions, field labels, buttons, warnings, validation messages, connection-test messages, update messages, and restart notice;
- AnswerWindow placeholders, action buttons, and processing/status messages, while the structural labels `Context`, `Question`, and `Answer` remain English;
- tray/menu text and tooltips;
- capture/watch selection guidance and user-facing workflow errors;
- product-owned DeepSeek configuration/request errors shown to the user.

Logs, internal exception text that is never surfaced directly, code identifiers, third-party error payloads, and developer diagnostics do not need translation solely for this feature.

## 9. Localization mechanism

Add one small module, tentatively:

```text
app/localization.py
```

Responsibilities:

- define supported language codes and display names;
- provide the English and Simplified Chinese string catalogs;
- expose a small lookup function such as `tr(key, language, **values)`;
- expose answer-language metadata/instructions used by prompt construction;
- define the default interface and answer language values.

Example conceptual usage:

```python
tr("settings.title", "zh-CN")
tr("answer.copy", "en")
```

The implementation should fail fast in tests if one supported interface language is missing a required translation key. It should not silently build a large fallback/compatibility framework.

Translation keys should describe meaning rather than literal English text, for example:

```text
settings.title
settings.restart_required
answer.action.copy
status.recognizing_question
error.deepseek_timeout
```

Invariant labels such as `Context`, `Question`, and `Answer` do not need duplicate translation-catalog entries merely to return the same English text.

## 10. Persistence and runtime config

Add two allow-listed non-sensitive settings:

```json
{
  "interface_language": "en",
  "answer_language": "zh-CN"
}
```

`SettingsRepository` validates only supported values and falls back to the defined defaults when keys are absent or invalid.

Add the corresponding immutable fields to `AppConfig` so a processing job receives the answer/interface language along with the rest of its runtime configuration.

No environment-variable override is needed for these UI preferences in the first version. They are ordinary user settings, not deployment configuration.

## 11. DeepSeek prompt design

Do not create separate full copies of every Text/Vision/Context prompt for every language.

Prompt construction should separate:

1. task behavior;
2. mode-specific context (Text, Vision, Context + Question);
3. configured answer language and output headings.

The language instruction must explicitly state that the configured answer language controls the response regardless of the language used in the source question.

Conceptually:

```text
Task:
- understand the exam question;
- identify the answer;
- explain the reasoning;
- summarize key concepts;
- do not fabricate missing information.

Output language:
- Simplified Chinese
- use headings: 答案 / 解析 / 知识点
```

or:

```text
Output language:
- English
- use headings: Answer / Explanation / Key Points
```

The same answer-language setting applies to:

- normal OCR/Text analysis;
- Vision analysis;
- Context + Question analysis;
- Watch and Context Watch indirectly through their existing shared analysis paths.

## 12. Interaction with OCR language

`ocr_language` remains independent.

For example, all of the following must remain valid:

```text
OCR hint: Japanese
Interface: English
Answer: Simplified Chinese
```

Changing `Answer language` must not change OCR recognition configuration, and changing OCR recognition language must not change the interface or DeepSeek response language.

## 13. Failure scenarios that matter

### A. Answer language is ignored in one analysis path

Failure: Text answers are English but Vision or Context + Question still answers in Chinese.

Consequence: the setting is not trustworthy.

Required protection: focused tests must inspect/drive all three prompt paths and confirm they carry the configured language/output contract.

### B. Interface becomes partially bilingual unintentionally

Failure: a supported translated screen shows English and Chinese product-owned prose because a translation key is missing.

Consequence: visibly broken localization.

Required protection: translation-catalog key parity test plus focused UI assertions for the main translated surfaces.

Language-invariant vocabulary listed in Section 7 is intentional and must not be treated as a missing translation.

### C. Existing users unexpectedly switch answer language

Failure: upgrading changes the default answer from Chinese to English without user action.

Consequence: regression in established behavior.

Required protection: settings/config tests for missing language keys must resolve to `en` interface + `zh-CN` answer.

### D. Language preference changes OCR behavior

Failure: selecting English answers changes the OCR language/provider.

Consequence: unrelated behavior regression.

Required protection: settings/config tests keep `ocr_language`, provider, interface language, and answer language independent.

### E. Interface setting appears to apply immediately but existing widgets stay stale

Failure: Settings says the language changed while already-open windows retain mixed old/new copy.

Consequence: inconsistent UI.

Required behavior: first version explicitly treats interface-language changes as restart-required; do not partially retranslate live widgets.

## 14. Expected implementation shape

Likely implementation files:

```text
app/localization.py                  # language catalog + answer language metadata
app/settings/repository.py           # persist/validate two language preferences
app/config.py                        # expose language preferences in AppConfig
app/services/deepseek_service.py     # language-aware prompts and user-facing errors
app/ui/settings_window.py            # language controls + translated Settings copy
app/ui/main_window.py                # localized ordinary controller copy/tooltips; invariant card terms stay English
app/ui/answer_window.py              # invariant structure labels + translated action/status copy
app/ui/tray.py and relevant watch UI # translate user-facing prose where present

tests/...                            # settings, prompt, catalog parity, focused UI regression coverage
README.md
README.zh-CN.md                      # document the two preferences and restart behavior
```

The actual implementation PR should only touch additional UI modules when they contain reachable product-owned strings that must participate in the selected interface language.

## 15. Test plan

Minimum meaningful coverage:

1. `SettingsRepository` loads/saves supported language values and uses the upgrade defaults when absent.
2. Invalid persisted language values fall back to the defined defaults.
3. `AppConfig` carries the persisted interface and answer language independently from OCR language/provider.
4. English and Simplified Chinese interface catalogs have the same required keys.
5. Text prompt contains the configured answer-language instruction/headings.
6. Vision prompt contains the configured answer-language instruction/headings.
7. Context + Question prompt contains the configured answer-language instruction/headings.
8. Main controller and AnswerWindow still display invariant terms such as `Text / OCR`, `Vision`, `Watch`, `Context Watch`, `Ready`, `Context`, `Question`, and `Answer` under both interface languages.
9. Focused Settings/AnswerWindow tests verify translated ordinary UI copy for both languages.
10. Existing OCR/provider/analysis-mode behavior remains unchanged.

Because this changes shared Settings/config/prompt/UI behavior, the implementation phase should finish with the complete Core test suite and GitHub Core CI after focused tests pass.

## 16. Documentation

The implementation PR is user-visible and must update both `README.md` and `README.zh-CN.md` in the same PR.

Documentation should explain:

- Interface language and Answer language are independent;
- first-version supported languages;
- `Text / OCR`, `Vision`, `Watch`, `Context Watch`, `Ready`, `Context`, `Question`, `Answer`, and technical product names intentionally remain English;
- interface-language changes require application restart;
- answer-language changes apply to subsequent analyses;
- OCR recognition language is a separate setting/concept.

## 17. Rollout

No feature flag, migration framework, compatibility wrapper, or settings-file migration step is required.

Existing settings files simply lack the two new allow-listed keys and therefore use the defined defaults until the user saves a preference.

## 18. Definition of Done

The feature is complete when:

- Settings exposes independent Interface language and Answer language selectors;
- both preferences persist across restart;
- English and Simplified Chinese are supported;
- Text, Vision, and Context + Question all obey Answer language;
- ordinary reachable UI copy follows Interface language while the defined product vocabulary stays invariant;
- interface-language restart behavior is clear and consistent;
- OCR language/provider remains independent;
- focused regression tests and Core CI pass;
- English and Chinese README documentation is updated;
- Windows and macOS manual smoke confirms the selected language is visually coherent in the main controller, Settings, and AnswerWindow.

## 19. Open questions for design review

There are no remaining architecture or product-wording blockers for the first implementation.
