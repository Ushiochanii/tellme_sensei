# Provider Architecture Refactor Design

Status: Draft for design review

## 1. Background

TellMeSensei has reached the point where its analysis workflows are more mature than its backend-selection model.

Today the product can run Text / OCR, Vision, Watch, and Context Watch, but AI access is still structurally centered on DeepSeek:

- `DeepSeekService` owns Text, Context + Question, and Vision analysis;
- prompt construction is mixed into the same class as provider transport and streaming;
- Text uses `AppConfig.model`, while Vision uses a fixed `VISION_MODEL` constant;
- DeepSeek-specific request options and user-facing errors live in the same service;
- Settings exposes one DeepSeek API key and one Text model field.

OCR is further along architecturally. `OCRProvider` is already a shared contract, `create_ocr_provider()` is already the construction seam, and Settings already presents a Local / Online distinction. However, the persisted/runtime model still treats `local` and `google_vision` as concrete values of one `ocr_provider` field, so the structure is not yet ready to retain independent Local engine and Online provider selections.

The next product stage should establish stable backend capability boundaries before building Getting Started / readiness UI on top of them.

## 2. Problem statement

TellMeSensei currently encodes provider names into responsibilities that should belong to product capabilities.

The most visible limitations are:

1. Text AI and Vision AI cannot be configured independently.
2. Adding Qwen or GLM/Z.AI would either require expanding `DeepSeekService` into a multi-vendor switch statement or duplicating the whole service.
3. Prompt semantics are coupled to provider transport, so changing providers risks changing TellMeSensei's analysis behavior.
4. The current model field cannot represent a curated provider-specific model catalog plus a Custom model ID path.
5. The global DeepSeek API-key requirement is incompatible with configurations where Text or Vision uses another provider.
6. Google Cloud Vision is conceptually an Online OCR provider, but runtime configuration still gives it special-case identity beside `local` instead of modelling Local engine vs Online provider explicitly.
7. A future Getting Started screen would currently have to ask DeepSeek- and Google-specific questions rather than stable capability questions such as `Text AI ready?`, `Vision AI ready?`, and `OCR ready?`.

## 3. Goals

1. Make `Text AI`, `Vision AI`, and `OCR` the stable product-level backend capabilities.
2. Allow Text AI and Vision AI to select provider and model independently.
3. Ship first-version AI provider support for:
   - DeepSeek
   - Qwen / Alibaba Cloud Model Studio
   - Z.AI / GLM
4. Separate TellMeSensei prompt construction from provider request transport.
5. Reuse one OpenAI-compatible transport core where the three providers actually share request/stream semantics, while keeping real provider-specific request differences in provider adapters/hooks.
6. Add a small curated model catalog, filtered by Text/Vision capability, plus `Custom model ID...`.
7. Store AI credentials by provider so Text and Vision can share one provider credential without duplicating the stored secret.
8. Preserve existing DeepSeek configuration and credentials for upgrades without introducing a migration framework.
9. Normalize OCR configuration into Local OCR vs Online OCR while retaining the existing `OCRProvider` interface and factory seam.
10. Keep PaddleOCR as the initial Local OCR engine and Google Cloud Vision as the initial Online OCR provider, with clean extension points for later engines/APIs.
11. Leave `main` shippable after every implementation phase.
12. Establish configuration/readiness boundaries that a later Getting Started feature can consume without provider-specific rewrites.

## 4. Non-goals

This refactor does not include:

- OpenAI, Anthropic, Gemini, or other AI providers in the first implementation;
- a generic plugin system or dynamically loaded provider packages;
- a universal normalized model tier such as `Fast / Balanced / Pro` across AI vendors;
- automatic selection between Text and Vision;
- cloud account sync;
- background model-catalog updates;
- automatic provider `/models` discovery as the source of truth;
- a remote TellMeSensei model-catalog service in the first implementation;
- adding a second Online OCR provider before one is explicitly chosen;
- adding a second Local OCR engine before one is explicitly chosen;
- exposing arbitrary raw PaddleOCR parameters;
- changing OCR recognition language semantics;
- building Getting Started in the same refactor;
- changing Auto Watch detection/state-machine behavior;
- changing the answer-language contract introduced by Language Preferences.

Local OCR performance profiles are a follow-on task after this refactor. They should only expose knobs that real measurement shows materially affect TellMeSensei's supported workflow.

## 5. Current architecture relevant to the change

### 5.1 AI

`app/services/deepseek_service.py` currently owns four different responsibilities:

```text
TellMeSensei analysis semantics
  + prompt construction
  + OpenAI-compatible streaming transport
  + DeepSeek-specific request/error behavior
```

It also contains a fixed Vision model and DeepSeek-specific `thinking` request data.

`app/config.py` currently exposes one flat AI configuration:

```text
api_key
model
base_url
request_timeout
```

The same config object is used by all analysis modes, even though Text and Vision now need independent provider/model selection.

### 5.2 Secrets and settings

`SecretStore` already supports generic named accounts through `get_secret`, `set_secret`, and `delete_secret`.

Two legacy account identities matter for real upgrades:

- `tellme-sensei/default` — existing DeepSeek API key;
- `google-vision-api-key` — existing Google Cloud Vision API key.

These identities should be reused rather than copied into new secret slots.

`SettingsRepository` is an allow-listed `settings.json` store. Existing installations may contain `model`, `base_url`, `request_timeout`, and `ocr_provider`, so the refactor must define direct fallback behavior for those real persisted values.

### 5.3 OCR

OCR already has the correct central runtime seam:

```text
OCRProvider
    ↑
create_ocr_provider(...)
    ├ LocalOCRProvider
    └ GoogleVisionOCRProvider
```

Settings already presents:

```text
OCR
├ Local
│  └ PaddleOCR
└ Online
   └ Google Cloud Vision
```

The OCR refactor should therefore extend this structure, not replace it.

## 6. Product capability model

The stable product model becomes:

```text
TellMeSensei
├ Text AI
│  ├ Provider
│  └ Model
├ Vision AI
│  ├ Provider
│  └ Model
└ OCR
   ├ Local
   │  └ Engine
   └ Online
      └ Provider
```

The important distinction is:

- `Text AI` and `Vision AI` are AI reasoning capabilities;
- `OCR` converts an image into recognized text;
- Google Cloud Vision belongs under Online OCR;
- a multimodal GLM/Qwen/DeepSeek model belongs under Vision AI, not OCR.

### 6.1 Analysis-mode routing

Existing product modes map to these capabilities as follows:

| Product path | Backend capability |
|---|---|
| Text / OCR | OCR -> Text AI |
| Context + Question | OCR -> Text AI |
| Vision | Vision AI |
| Watch in Text mode | OCR -> Text AI |
| Watch in Vision mode | Vision AI |
| Context Watch | OCR -> Text AI |

No Auto Watch coordinator/state-machine logic should become provider-aware.

## 7. AI architecture

### 7.1 Separate prompt semantics from provider transport

Introduce a provider-neutral prompt layer, conceptually:

```text
AnalysisPromptBuilder
├ build_text(...)
├ build_context_question(...)
└ build_vision(...)
```

This layer owns:

- TellMeSensei's exam-study behavior;
- Text vs Context + Question vs Vision task instructions;
- answer-language instructions/headings;
- construction of provider-neutral chat message content.

It does not own:

- API keys;
- base URLs;
- HTTP/SDK clients;
- provider-specific `thinking` options;
- status-code wording;
- model catalog persistence.

Switching provider must not silently change the pedagogical prompt contract.

### 7.2 Provider contract

Introduce a small AI provider/transport contract, conceptually:

```python
class AIProvider:
    def complete(request, cancel_event=None) -> str: ...
    def test_connection(model_id, mode, cancel_event=None) -> bool: ...
```

The exact class names may change during implementation, but the responsibility boundary should not.

A request contains provider-neutral information such as:

```text
model ID
analysis capability: text | vision
messages
streaming/cancellation context
```

Provider-specific request options are added inside the provider implementation, not by `AnalysisPromptBuilder` or UI code.

### 7.3 OpenAI-compatible transport

Official provider documentation currently supports an OpenAI-compatible Chat Completions shape for all three first-version providers, including standard `image_url` multimodal content for their supported Vision models.

Therefore the first implementation should reuse a shared OpenAI-compatible streaming core for:

- client creation;
- stream iteration;
- visible/reasoning-content extraction;
- cooperative cancellation;
- stream close;
- common HTTP-class error handling.

Provider adapters remain explicit:

```text
OpenAICompatibleProvider
├ DeepSeekProvider
├ QwenProvider
└ ZAIProvider
```

These adapters own only real differences such as:

- default endpoint;
- provider display identity;
- provider-specific request extras (`thinking`, etc.);
- provider-specific error wording where needed;
- any model-specific request adjustment that is actually required.

Do not create three copies of the current `DeepSeekService`.

Do not claim that every future provider is OpenAI-compatible. A future provider with a genuinely different API gets its own transport implementation behind the same `AIProvider` contract.

### 7.4 Service layer

A provider-neutral analysis service composes:

```text
AnalysisPromptBuilder
        +
selected AIProvider
        +
selected model
```

Text and Context + Question use the resolved Text AI configuration. Vision uses the resolved Vision AI configuration.

The existing public concepts `DeepSeekError` / `DeepSeekCancelled` should become provider-neutral internal errors such as `AIProviderError` / `AIRequestCancelled`. TellMeSensei is an application rather than a public SDK, so implementation callers/tests should be updated directly instead of adding a long-lived compatibility wrapper solely for old internal names.

## 8. AI configuration model

### 8.1 Independent selections

Persist independent non-secret selections:

```text
text_ai_provider
text_ai_model
vision_ai_provider
vision_ai_model
```

First-version provider IDs:

```text
deepseek
qwen
zai
```

Display names remain vendor-native:

```text
DeepSeek
Qwen
Z.AI (GLM)
```

### 8.2 Runtime config

Resolve each capability into an immutable runtime configuration, conceptually:

```python
@dataclass(frozen=True)
class AIBackendConfig:
    provider_id: str
    model_id: str
    api_key: str
    base_url: str
    request_timeout: float

@dataclass(frozen=True)
class AppConfig:
    text_ai: AIBackendConfig
    vision_ai: AIBackendConfig
    ...
```

The same stored provider credential may therefore appear in both immutable runtime configs when Text and Vision use the same provider. The secret is still stored only once.

A single shared AI request timeout is sufficient for this refactor. Separate per-capability timeout controls are not required until real usage demonstrates a need.

### 8.3 Provider credentials and endpoints

Store credentials by provider rather than by Text/Vision capability:

```text
DeepSeek API Key
Qwen API Key
Z.AI API Key
```

DeepSeek must continue using the existing `tellme-sensei/default` secret account so upgrades retain the current key.

Qwen and Z.AI receive their own named SecretStore accounts.

Provider endpoint/base URL is non-secret and stored separately from the API key. Defaults are supplied by the provider descriptor. An editable Endpoint field remains available because Qwen's valid OpenAI-compatible endpoint can vary by region/workspace in normal supported use.

Do not build a generic endpoint-profile/migration subsystem. One provider descriptor plus an optional persisted endpoint override is enough.

### 8.4 Environment variables

Keep provider credentials provider-specific:

```text
DEEPSEEK_API_KEY
QWEN_API_KEY
ZAI_API_KEY
```

Add provider/model selection overrides only where they map cleanly to the new product capabilities:

```text
TEXT_AI_PROVIDER
TEXT_AI_MODEL
VISION_AI_PROVIDER
VISION_AI_MODEL
```

Provider endpoint overrides remain provider-specific:

```text
DEEPSEEK_BASE_URL
QWEN_BASE_URL
ZAI_BASE_URL
```

The exact timeout environment-variable name can be settled in implementation, but existing `DEEPSEEK_TIMEOUT` must remain a fallback for upgraded configurations until the user saves/sets the provider-neutral timeout value.

## 9. Upgrade behavior

This project has real existing installations, so preserving current configuration is required. A migration framework is not.

When new settings are absent:

```text
Text AI provider   = DeepSeek
Vision AI provider = DeepSeek
```

Text model resolution should use this order within the existing configuration-precedence rules:

```text
new Text AI model setting/override
→ existing DeepSeek model setting / DEEPSEEK_MODEL
→ current DeepSeek Text default
```

Vision model resolution should use:

```text
new Vision AI model setting/override
→ current fixed DeepSeek Vision model default
```

DeepSeek API key continues to read the current OS env / existing SecretStore slot / existing `.env` path according to current precedence.

No one-time migration command, schema version, migration directory, or compatibility framework is needed.

Once the user saves the new AI settings, the new provider/model keys become authoritative. Old unused settings may remain harmlessly in `settings.json`; this refactor does not need a cleanup migration.

## 10. Model catalog

### 10.1 Curated catalog, not vendor inventory

TellMeSensei should ship a deliberately small model catalog rather than mirror every model exposed by every vendor.

Each catalog entry needs only product-relevant metadata:

```text
provider_id
model_id
display_name
supported capabilities: text | vision
optional recommendation label
```

The Text selector filters to Text-capable entries. The Vision selector filters to Vision-capable entries.

A model supporting both can appear in both selectors without duplicate catalog records.

### 10.2 First-version size

Target roughly 2–4 useful entries per provider, not dozens.

The exact model IDs should be refreshed from official provider documentation when the implementation phase begins because vendor model catalogs change faster than this architecture.

Current candidate families include:

- DeepSeek: current Flash / Pro Text models and the current Vision model;
- Qwen: current general/multimodal Qwen models exposed through Model Studio's OpenAI-compatible API;
- Z.AI: current GLM Text models and current GLM Vision models.

The Design Doc does not make a specific model ID part of the long-term architecture contract.

### 10.3 Custom model ID

Every provider/model selector includes:

```text
Custom model ID...
```

The stored value is simply the entered model ID. No separate persistent `is_custom` flag is needed.

When loading Settings, a saved model not present in the bundled catalog is displayed as a Custom model ID rather than rejected.

For a custom model selected in the Vision card, the user's explicit placement in Vision is the capability declaration. TellMeSensei does not need a speculative capability database for unknown models.

### 10.4 Dynamic discovery

Provider `/models` endpoints are not the first-version source of truth. A returned model list does not reliably answer every product question TellMeSensei needs, especially modality/capability and recommended-use metadata.

A future manual `Refresh model catalog` mechanism may be considered if bundled-catalog maintenance becomes a real burden. It is not part of this refactor.

## 11. Settings UX

Replace the current `DeepSeek` page with an AI-focused page.

Conceptually:

```text
AI Models

Text AI
Provider  [ DeepSeek ▼ ]
Model     [ deepseek-... ▼ ]
[Test Text AI]

Vision AI
Provider  [ Qwen ▼ ]
Model     [ qwen-... ▼ ]
[Test Vision AI]

Provider Credentials
DeepSeek   API Key [••••••]   Endpoint [...] 
Qwen       API Key [••••••]   Endpoint [...]
Z.AI       API Key [••••••]   Endpoint [...]
```

The final visual composition may use cards or a selected-provider credential editor rather than showing all three keys simultaneously. The invariant is:

- Text and Vision selections are independent;
- provider credentials are shared by provider;
- the user can test the selected Text backend and selected Vision backend separately;
- Endpoint is editable where needed;
- model names remain vendor-native.

### 11.1 Connection tests

`Test Text AI` performs one minimal Text request with the currently selected Text provider/model.

`Test Vision AI` performs a minimal Vision request using a small generated in-memory image so the test verifies not only authentication but also that the selected model actually accepts image input.

Connection tests remain asynchronous/cancellable and retain the current short Settings timeout behavior.

A successful provider credential alone must not be reported as a successful Vision configuration if the selected model rejects images.

## 12. OCR architecture

### 12.1 Keep the existing OCRProvider contract

Do not create a second OCR abstraction alongside `OCRProvider`.

The stable runtime contract remains:

```text
image -> OCRProvider -> recognized text
```

`create_ocr_provider()` remains the single construction point used by callers.

### 12.2 Normalize Local vs Online configuration

Persist the UI concepts explicitly:

```text
ocr_mode = local | online
local_ocr_engine = paddleocr
online_ocr_provider = google_vision
```

This lets TellMeSensei remember both the selected Local engine and Online provider while the user switches between modes.

First-version shipped implementations remain:

```text
Local OCR
└ PaddleOCR

Online OCR
└ Google Cloud Vision
```

The factory resolves the active implementation from `ocr_mode` plus the corresponding selected engine/provider.

### 12.3 Google Cloud Vision

Google Cloud Vision stops being a top-level special OCR mode and becomes the first concrete Online OCR provider.

Its existing SecretStore account and existing `GOOGLE_VISION_API_KEY` environment variable remain valid for upgrades.

The current Google Vision provider implementation should be reused rather than wrapped in another Google-only layer.

### 12.4 Future Online OCR providers

A future Online OCR service should add:

- one concrete `OCRProvider` implementation;
- one provider descriptor/catalog entry;
- one provider credential slot if required;
- Settings fields required by that provider;
- factory registration;
- focused provider tests.

Do not introduce a plugin registry, arbitrary provider JSON schema, or generic parameter bag before a real second provider requires it.

### 12.5 Future Local OCR engines

`local_ocr_engine` establishes the identity boundary, but PaddleOCR remains the only shipped engine in this refactor.

A future engine should own typed settings relevant to that engine. Do not invent one universal `OCRGenericSettings` object for unknown engines.

## 13. Local OCR performance settings follow-on

After the provider architecture is stable, Local OCR tuning should be a separate focused task before Getting Started.

The expected product-level UX remains:

```text
Performance profile
- Fast
- Balanced
- Accurate
```

However those profiles should not be implemented until the current Local OCR worker/runtime is measured and specific controllable knobs are shown to materially change latency/accuracy for TellMeSensei's real Japanese/English/Chinese screenshot workflow.

Only proven knobs should be exposed or mapped into profiles. Do not surface dozens of raw PaddleOCR switches simply because the underlying library has them.

## 14. Failure scenarios that matter

### A. Existing DeepSeek configuration disappears after upgrade

Failure: an upgraded user loses the stored DeepSeek key/model and must reconfigure the application.

Consequence: direct product regression.

Required behavior: retain the legacy DeepSeek secret account and read old model/base-url settings as explicit fallbacks when new AI keys are absent.

### B. Text provider selection changes Vision unexpectedly

Failure: choosing Qwen for Text silently changes Vision from DeepSeek to Qwen.

Consequence: independent capability settings are not real.

Required protection: independent persisted selection tests and UI tests.

### C. Provider transport changes TellMeSensei prompt semantics

Failure: one provider receives a materially different task/answer-language prompt because prompt construction was duplicated in an adapter.

Consequence: provider choice changes product behavior.

Required protection: one shared prompt builder with provider-neutral prompt tests.

### D. A Vision model is accepted by Settings but cannot process images

Failure: credentials test successfully, then real Vision use fails because the selected model is Text-only.

Consequence: misleading Settings state.

Required behavior: bundled catalog filters known models by capability; Vision connection test sends a real minimal image; custom Vision models remain user-explicit and surface the provider error if unsupported.

### E. Qwen endpoint does not match the user's region/workspace

Failure: a valid Qwen API key cannot connect through the default endpoint.

Consequence: Qwen support is unusable for a normal supported configuration.

Required behavior: Endpoint is editable and treated as provider configuration, not hard-coded globally.

### F. Global DeepSeek validation blocks a non-DeepSeek configuration

Failure: Text=Qwen and Vision=Z.AI are fully configured, but startup fails because `DEEPSEEK_API_KEY` is absent.

Consequence: provider abstraction is only cosmetic.

Required behavior: remove the global DeepSeek-key requirement. Validation occurs for the selected capability/provider when needed, and later readiness UI can report missing configuration explicitly.

### G. OCR mode switch forgets the inactive selection

Failure: user selects an Online provider, switches Local, then returning Online loses the prior provider selection.

Consequence: poor settings behavior once multiple providers exist.

Required protection: persist `ocr_mode`, `local_ocr_engine`, and `online_ocr_provider` independently.

### H. Google Cloud Vision upgrade path loses its credential

Failure: the Online OCR refactor starts using a new secret slot and ignores the existing Google key.

Consequence: existing Online OCR stops working.

Required behavior: keep the existing Google Vision secret identity as the canonical Google credential.

## 15. Alternatives considered

### 15.1 One provider/model setting for all AI modes

Rejected. Text and Vision have different model availability, cost, latency, and capability. The user explicitly needs independent choices.

### 15.2 Duplicate one full service per vendor

Rejected. It would duplicate prompt behavior, cancellation, streaming, and error handling and would make future changes drift between providers.

### 15.3 One fully generic universal provider class

Rejected. The first three vendors share enough OpenAI-compatible transport to reuse a core, but provider-specific request extras and endpoint behavior are real. Hiding those differences behind a universal dictionary would make the abstraction less clear, not more.

### 15.4 Generic `Fast / Balanced / Pro` AI tiers

Rejected. Vendor product tiers do not align semantically and change over time. TellMeSensei selects actual model IDs.

### 15.5 Dynamic `/models` discovery first

Rejected. Availability discovery alone does not provide a trustworthy TellMeSensei capability/recommendation catalog. Curated defaults + Custom model ID solve the immediate product problem with much less machinery.

### 15.6 Rebuild OCR around a new registry

Rejected. The current `OCRProvider` and factory are already the correct extension seam. The needed work is configuration normalization, not another abstraction layer.

## 16. Implementation phases

The Design Doc must be accepted before implementation begins. After acceptance, create one umbrella Issue with phase checklists and links to this document.

### Phase 1 — AI core extraction and DeepSeek parity

Goal: establish the new architecture without changing the user's provider choices yet.

Expected work:

- extract shared prompt construction;
- introduce provider-neutral AI errors/request contract;
- introduce shared OpenAI-compatible streaming core;
- move DeepSeek behavior into `DeepSeekProvider`;
- introduce resolved Text AI / Vision AI runtime config with DeepSeek defaults;
- remove the fixed Vision-model constant from analysis routing and resolve it through Vision AI config;
- preserve current DeepSeek behavior and existing Settings UX for this phase where practical.

Exit criteria:

- Text, Context + Question, and Vision produce the same product behavior through the new DeepSeek adapter;
- cancellation and streaming regressions are covered;
- existing user configuration continues to work;
- no Qwen/Z.AI UI is exposed yet.

### Phase 2 — Multi-provider AI + model catalog + Settings

Goal: make the architecture user-visible.

Expected work:

- add Qwen and Z.AI provider adapters;
- add curated AI model catalog + capability filtering;
- add Custom model ID flow;
- add provider-specific credential/endpoint persistence;
- replace DeepSeek Settings page with Text AI / Vision AI selections and provider credentials;
- add separate Text/Vision connection tests;
- update localization strings;
- update README and README.zh-CN.

Exit criteria:

- Text and Vision can independently use any supported first-version provider/model combination;
- known Vision selectors only show Vision-capable bundled models;
- custom model IDs round-trip through Settings;
- one provider credential is reused when both capabilities select the same provider;
- manual smoke verifies at least one real request path for each shipped provider where credentials are available.

### Phase 3 — OCR Local/Online configuration normalization

Goal: finish the OCR backend model without rewriting the working provider contract.

Expected work:

- persist `ocr_mode`, `local_ocr_engine`, and `online_ocr_provider`;
- preserve old `ocr_provider=local|google_vision` as direct upgrade fallback;
- keep PaddleOCR and GoogleVisionOCRProvider implementations intact unless integration requires a small change;
- adapt factory selection to the normalized config;
- ensure Settings retains Local and Online selections independently;
- update user documentation where terminology changes.

Exit criteria:

- Local/Online selection is explicit in config;
- PaddleOCR remains the Local default;
- Google Cloud Vision is represented as the Online provider;
- existing Google Vision credential/config continues to work;
- adding a future Online provider no longer requires changing the product-level OCR mode concept.

### Phase 4 — Local OCR tuning follow-on

This is a separate focused design/implementation task after measurement, not automatically part of the provider-refactor PR series.

Goal: define only evidence-backed `Fast / Balanced / Accurate` behavior and any small Advanced controls that materially affect the supported workflow.

### Phase 5 — Getting Started / readiness dashboard

Begin a separate Design Doc after the provider architecture is stable.

It should consume capability-level readiness such as:

```text
Text AI  -> selected provider/model configured and testable?
Vision AI -> selected provider/model configured and testable?
OCR       -> selected Local engine installed or Online provider configured?
Screen Capture -> permission ready?
Language  -> configured?
```

It must not hard-code DeepSeek or Google Cloud Vision as universal requirements.

## 17. Expected implementation shape

Likely shape after the refactor:

```text
app/
├ ai/
│  ├ catalog.py              # curated provider/model metadata
│  ├ models.py               # provider-neutral request/config types
│  ├ prompts.py              # TellMeSensei Text/Context/Vision prompt construction
│  ├ service.py              # provider-neutral analysis orchestration
│  └ providers/
│     ├ openai_compatible.py # shared streaming/cancellation transport
│     ├ deepseek.py          # DeepSeek endpoint/request differences
│     ├ qwen.py              # Qwen endpoint/request differences
│     └ zai.py               # Z.AI / GLM endpoint/request differences
├ ocr/
│  ├ base.py                 # existing OCRProvider contract
│  ├ factory.py              # Local/Online concrete construction point
│  └ providers/              # existing and future concrete OCR providers
├ config.py                  # resolve capability selections + provider credentials
├ settings/
│  ├ repository.py           # allow-listed non-secret selections/endpoints
│  └ secret_store.py         # named provider credentials
└ ui/
   └ settings_window.py      # Text AI / Vision AI / OCR configuration UX
```

Exact file splits should remain proportional during implementation; do not create empty modules solely to match this tree.

## 18. Test plan

### AI core

1. Shared prompt builder preserves Text, Context + Question, Vision, and answer-language contracts.
2. DeepSeek adapter produces the current request shape, including required provider-specific Vision options.
3. Shared streaming transport preserves visible-content assembly, reasoning metadata handling, cancellation, and stream close.
4. Provider-specific errors are surfaced through provider-neutral application errors without leaking API keys.
5. Text routing always uses Text AI config; Vision routing always uses Vision AI config.

### Configuration and upgrade

6. Missing new AI settings resolve to DeepSeek defaults.
7. Existing saved `model` / `DEEPSEEK_MODEL` still feed Text AI when new Text model keys are absent.
8. Existing DeepSeek SecretStore key remains usable.
9. Text and Vision selections persist independently.
10. Qwen/Z.AI credentials are stored by provider and reused across capabilities.
11. Provider endpoint override persists and resolves correctly.
12. A configuration with no DeepSeek key works when the selected capabilities use other configured providers.

### Model catalog and Settings

13. Text selectors filter Text-capable bundled models.
14. Vision selectors filter Vision-capable bundled models.
15. Unknown saved model IDs load as Custom model IDs.
16. Text/Vision connection tests use the selected provider/model and remain cancellable.
17. Vision connection test includes an actual image input.

### OCR

18. Existing `ocr_provider=local` upgrades to Local + PaddleOCR.
19. Existing `ocr_provider=google_vision` upgrades to Online + Google Cloud Vision.
20. Local and Online selections persist independently.
21. `create_ocr_provider()` constructs the selected concrete implementation through the existing `OCRProvider` contract.
22. Existing Google Vision credential remains usable.
23. Existing Local OCR lifecycle/install/session tests remain green.

### Validation

Each implementation phase runs focused tests first, then the complete Core suite / GitHub Core CI once the phase is ready for review.

User-visible Settings phases require Windows and macOS manual visual/function smoke. Real third-party credentials should be used only for focused manual provider connection tests; CI uses deterministic test doubles and does not depend on external paid APIs.

## 19. Documentation and release

Phase 1 is primarily internal and does not require README churn if user-visible behavior remains unchanged.

Phase 2 is user-visible and must update `README.md` and `README.zh-CN.md` in the same PR with:

- supported AI providers;
- independent Text AI / Vision AI selection;
- model catalog + Custom model ID behavior;
- provider credential/endpoint configuration;
- environment-variable changes and upgrade notes.

Phase 3 updates OCR documentation to make Local OCR vs Online OCR terminology explicit if current docs do not already describe it accurately.

No feature flag is needed. Each phase should merge only when it is independently correct and shippable.

A stable release should happen after the user-visible provider Settings phases have passed Windows/macOS smoke, rather than releasing the internal Phase 1 refactor alone solely to mark progress.

## 20. Definition of Done

The provider architecture refactor is complete when:

- Text AI and Vision AI have independent provider/model selections;
- DeepSeek, Qwen, and Z.AI/GLM are shipped AI providers;
- TellMeSensei prompt semantics are provider-neutral and shared;
- shared OpenAI-compatible transport is reused without hiding real provider differences;
- curated model lists are capability-filtered and Custom model ID is supported;
- credentials are stored once per provider;
- existing DeepSeek key/model configuration survives upgrade;
- startup/runtime no longer globally requires a DeepSeek key when another provider is selected;
- OCR persists Local/Online mode, Local engine, and Online provider independently;
- PaddleOCR remains the Local engine and Google Cloud Vision becomes the first Online OCR provider in the normalized model;
- existing Google Vision configuration survives upgrade;
- focused tests and Core CI pass for every implementation phase;
- user-visible provider/OCR documentation is current;
- Windows and macOS smoke confirms Settings and the selected analysis paths behave correctly.

## 21. Open questions for design review

No architecture blocker remains for starting Phase 1 after review.

Two implementation-time details are intentionally not frozen by this Design Doc:

1. the exact 2–4 bundled model IDs per provider, which should be refreshed from official vendor documentation at Phase 2 start;
2. the exact visual composition of the provider-credential editor, as long as Text/Vision selections remain independent and credentials remain provider-scoped.

The next process step after this Design Doc is accepted is to update the productization roadmap (#62), create one umbrella implementation Issue, and begin Phase 1 from the then-current `main`.
