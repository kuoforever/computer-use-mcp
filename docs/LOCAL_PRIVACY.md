# Local privacy boundary

The Agent Host has an opt-in, run-scoped text pseudonymization boundary. It
replaces reviewed sensitive spans before task, memory, or desktop-observation
text can enter provider requests, the replay ledger, traces, or checkpoints.
The model sees typed opaque tokens such as:

```text
[[PRIVATE:EMAIL:7A0D...]]
[[PRIVATE:PHONE:19BC...]]
[[PRIVATE:SECRET:3F42...]]
```

Tokens use a per-run random HMAC key. The same category and plaintext receive
the same token during one run, while different runs are intentionally
unlinkable. The plaintext-to-token vault exists only in Host memory.
Screenshot overlays use compact aliases such as `[EMAIL#1]`; each alias is
bound to the same run-local vault entry as its canonical text token.

## Current scope

The deterministic MVP detects:

- email addresses;
- mainland China mobile numbers, with an optional `+86` prefix;
- valid IPv4 addresses;
- 18-character mainland China identity numbers with a valid birth date and
  standard checksum;
- 13-19 digit bank-card candidates that pass the Luhn checksum;
- explicit operator-configured terms; and
- values in simple `api_key=...`, `access_token=...`, `password=...`, or
  equivalent secret assignments.

Ordinary PII tokens can be restored only for local final display. Secret tokens
are never restored into final text. The only tool-argument restoration sink is
the local read-only `find.query` field. Unknown, malformed, cross-run, secret,
or misplaced tokens fail closed.

All local desensitization lives under the opt-in `computer_use_agent.privacy`
package: text detectors and the run-scoped vault are private internals alongside
the screenshot pipeline and future visual-detector interface. The Runner uses
only this package's public boundary. The current screenshot implementation
adapts the existing local Windows OCR engine over the returned PNG. It checks
individual words and also combines up to eight adjacent words on
the same inferred visual line, with both spaced and compact forms. This catches
values OCR splits around `@`, digit groups, spaces, or assignment punctuation.
Only the word boxes mapped to a detected value are unioned, expanded by two
pixels, painted solid black, and overlaid with a compact typed alias. Rendering
occurs before the result enters the ledger or provider adapter, and preserves
the original PNG width, height, and coordinate system. OCR timeout, malformed
or out-of-bounds boxes, excessive output, and rendering failure stop the
screenshot before provider dispatch. The Runner depends only on the complete
image-redaction port, not on an OCR implementation. Setting
`image_redaction = false`, or omitting that port, removes `screenshot` from the
provider registry and rejects an attempted call.

This release does not claim general NER or semantic anonymity. Image detection
is bounded OCR text detection. Values split across more than eight words,
incorrect OCR reading order, or boxes whose geometry prevents reliable line
grouping may not be recognized. It does not yet detect faces, QR codes, identity
documents as visual objects, signatures, or other non-text secrets. The image
module defines a reviewed, optional `PrivacyVisualDetector` port for those
non-text regions, but no production backend is installed or enabled. Any future
backend must return bounded local pixel boxes; the Host then applies an
irreversible solid overlay without adding the detected content to the vault.
The server's existing title-matched screenshot blackouts still run before this
Host boundary.

[DeepSeek-OCR](https://github.com/deepseek-ai/DeepSeek-OCR) and
[DeepSeek-OCR-2](https://github.com/deepseek-ai/DeepSeek-OCR-2) are evaluation
candidates for a future document-vision or grounded-region backend, not current
runtime dependencies. Their GPU-oriented model stacks and broad
document-understanding scope are kept outside the lightweight Windows Host
until accuracy, hardware, packaging, and privacy tests define an activation
decision. They should not be treated as a drop-in face or QR detector.

## Configuration

Privacy is disabled by default:

```toml
[privacy]
enabled = true
detectors = ["email", "phone", "ipv4", "cn_id", "bank_card", "secret"]
terms = ["Project Phoenix", "Example Customer"]
image_redaction = true
```

Detector names and custom terms are strictly validated. Custom terms are
literal, case-sensitive strings. Privacy cannot currently be enabled together
with `[continuation].enabled = true`: crash recovery would require persisting
the vault, and this MVP deliberately does not write plaintext mappings to disk.

## Data flow and persistence

1. The Host creates a new in-memory vault for the run.
2. It pseudonymizes the task and selected memory content and scope.
3. It pseudonymizes MCP text results before appending them to the ledger.
4. It validates every provider-returned token and tool argument.
5. For screenshots, local OCR identifies word boxes and the Host replaces
   sensitive pixels with solid typed aliases without changing dimensions.
6. It resolves a valid PII token only at an allowlisted local sink.
7. It restores valid, non-secret canonical tokens or image aliases only in the
   returned local final text.

The raw local text can still exist briefly in process memory and in the local
MCP child-to-Host transport before the Host boundary. This mechanism is
pseudonymization, not anonymization: surrounding context may still identify a
person or organization. Operators should combine it with narrow observation
scope and explicit custom terms.

## Deferred image boundary

The privacy package contains the extension point for evaluated local detectors
for faces, QR codes, identity documents, and signatures. Activation
remains deferred: adding a package must not implicitly enable a detector, and a
backend needs fixture-based recall, false-positive, resource, timeout, and
fail-closed tests before configuration can expose it. A future resumable vault
must use an OS-bound encrypted store and bind each entry digest to continuation
evidence before the current continuation incompatibility can be removed.
