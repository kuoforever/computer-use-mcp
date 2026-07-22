# Concurrent checkpoint publish/read evidence

> **Status: offline measurement retained 2026-07-22.** This record documents a
> Windows file-sharing hazard found while building live checkpoint polling
> (progress viewer delivery step 3), the measurements that ruled out two
> plausible fixes, and the change that removed it. It is offline evidence only:
> it is not desktop, provider, campaign, application, or release evidence.

## The hazard

`computer_use_agent.trace._atomic_json` published run checkpoints with
`tempfile.mkstemp` + `os.replace`, and `_read_json` read them with
`Path.read_bytes`. On Windows `os.replace` is `MoveFileExW(MOVEFILE_REPLACE_EXISTING)`,
which **cannot replace a target that has any open handle**.

The failure is asymmetric and severe. `_atomic_json` does not retry, so a
collision raises `CHECKPOINT_WRITE_FAILED` and fails the agent's run. Any live
reader — the operator progress poller above all — would therefore inject a new
failure mode into the write path that carries existing evidence.

## Measurements

One reader polling one checkpoint in a tight loop, on the source commit's
interpreter (CPython 3.13.7, Windows 11):

| Reader | Publisher | Publish failures | Read failures |
| --- | --- | --- | --- |
| `Path.read_bytes` | `os.replace` | **61.9%** (2446/4000) | 0% |
| `FILE_SHARE_DELETE` read | `os.replace` | **73.8%** (1475/2000) | 0% |
| `Path.read_bytes` | `ReplaceFileW` | 100% (sharing violation) | — |
| `FILE_SHARE_DELETE` read | `ReplaceFileW`, 1 read attempt | **0.00%** | 24.3% |
| `FILE_SHARE_DELETE` read | `ReplaceFileW`, 4 read attempts | **0.00%** | 0.05% |

A controlled single-handle probe isolated why the obvious fix fails:

~~~text
share=READ|WRITE          os.replace FAILED(5)   unlink FAILED(32)
share=READ|WRITE|DELETE   os.replace FAILED(5)   unlink OK
share=DELETE              os.replace FAILED(5)   unlink OK
~~~

`FILE_SHARE_DELETE` permits *deletion* but not *replacement by rename*: a
pending-delete file still occupies its directory entry, so the rename onto that
name fails regardless of share mode. Hardening only the reader does not work,
and hardening only the writer with `ReplaceFileW` does not work either — the two
halves are required together.

## The change

`computer_use_agent.atomic_file` now owns both halves of the contract:

- `read_shared_bytes` opens with `FILE_SHARE_READ | FILE_SHARE_WRITE |
  FILE_SHARE_DELETE` so a publish is never blocked, and retries a bounded four
  attempts on the transient states a publish exposes (`ERROR_FILE_NOT_FOUND`,
  `ERROR_PATH_NOT_FOUND`, `ERROR_SHARING_VIOLATION`). Any other error raises on
  the first attempt.
- `publish_atomically` uses `ReplaceFileW`, falling back to `os.replace` for a
  first publish (no target to replace), non-Windows platforms, and any layout
  `ReplaceFileW` declines — so behaviour is never worse than before.

`trace._atomic_json` and `trace._read_json` use them. POSIX `rename` has neither
restriction and keeps the ordinary paths.

`ReplaceFileW` briefly frees the target name, so a racing reader can miss the
record entirely. That trade is deliberate: a failed publish fails a run, while a
failed read only makes one record momentarily unavailable to a viewer that will
look again. Readers never observe a *torn* record either way, because a
share-delete handle keeps referring to the original file object after the
directory entry is swapped.

## Result on the real write path

3,000 real `RunRecorder.record` publishes with a reader continuously calling
`read_run_checkpoint`:

~~~text
REAL WRITER x3000:  checkpoint_write_failures=0  reads_ok=223751 reads_failed=0
~~~

`tests/agent/test_atomic_file.py` holds the regression: a concurrent reader
fails no publish, and every successful concurrent read returns one whole
published payload.

## Supported claim and boundary

This removes a hazard that live checkpoint polling would otherwise have
introduced. It does not change checkpoint schema, contents, or transition rules,
and the full offline gate passes unchanged (1,116 tests). It is not evidence for
any desktop, provider, campaign, or application capability.

Related: [Capability status](CAPABILITY_STATUS.md),
[Operator progress viewer](PROGRESS_VIEWER.md).
