# Operator localization

> **Status: implemented for four native Windows operator surfaces.** English
> (`en-US`) and Simplified Chinese (`zh-CN`) share the same authority-neutral
> presentation contract. Task Center, Pre-run Review, Approval Inbox CLI,
> other CLI output, arbitrary application text, multi-display behavior,
> personalization, and human screen-reader evidence are outside this slice.

## Configuration and fallback

`[operator].locale` accepts exactly `"en-US"`, `"zh-CN"`, or `"auto"`.
Omitting the key preserves the legacy English presentation. Newly generated
installed product profiles write `locale = "auto"`.

`auto` reads the Windows user locale once while constructing a native operator
surface. `zh-CN`, `zh-SG`, and `zh-Hans` variants select Simplified Chinese.
Traditional Chinese and every unsupported, unavailable, invalid, or failing
system-locale result fall back to English. Locale lookup is presentation-only;
failure cannot stop, approve, retry, replay, or advance a run.

## Localized surfaces

The reviewed resource tables own visible text and matching UI Automation names
for:

- the Decision Card, including its header, choices, details, evidence labels,
  countdown, and safe-close explanation;
- the passive Progress summary, checklist, diagnostic projection, and top-level
  accessible name;
- the passive Presence label, glyph, window title, and top-level accessible
  name; and
- the fixed, noninteractive approval notification.

English choice labels use direct verbs: `Approve once`, `Check screen again`,
`Pause and inspect`, `Stop task`, and `Take control`. Those labels are display
copy only. The stable option IDs remain `option_approve_exact_effect`,
`option_reobserve`, `option_defer`, `option_deny`, and
`option_human_takeover`.

## Boundary and invariants

Locale never changes internal IDs, enums, digests, persisted JSON keys or
values, approval binding, policy decisions, safe defaults, or Runner/MCP
dispatch. Native Decision Card focus and close/timeout behavior continue to
select or return the unique `option_deny` boundary regardless of its displayed
language. Progress and Presence remain non-activating and read-only. The
approval notification remains noninteractive with all approve, deny, and
dispatch capabilities false.

Only exact reviewed Host strings are translated. Unknown Host labels and
application names are preserved verbatim; model text, task text, arbitrary UI
content, credentials, arguments, and tool results never enter the automatic
translation lane.

## Verification and remaining evidence

Deterministic tests cover strict parsing, `auto` resolution and English
fallback, reviewed copy in both locales, unknown-text preservation, stable
option IDs, unchanged authority, UIA-name construction, and removal of English
sentinels from native Progress behavior.

The bounded native probe exercises both locales without opening a provider,
MCP, application, or desktop-action port:

~~~powershell
python scripts/smoke_operator_accessibility.py
~~~

The probe inspects native UI Automation Text/Edit/Button names, traverses the
complete Decision Card keyboard path to `option_deny`, and confirms that
Progress and Presence do not change the foreground window. It is not Narrator
or NVDA auditory evidence, translation certification, application acceptance,
or E4/release evidence.
