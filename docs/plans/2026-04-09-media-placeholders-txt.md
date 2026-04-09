# Add media placeholders flag for TXT output

## Overview
Add `--media-placeholders` CLI flag that inserts media type indicators in TXT output (e.g. `[photo]`, `[file=report.pdf]`). Default: off. This helps readers see where media was attached without downloading it.

## Context
- TXT rendering: `src/telegram_download_chat/core/messages.py:131-185` (`save_messages_as_txt`)
- CLI args: `src/telegram_download_chat/cli/arguments.py` (`CLIOptions` dataclass + `parse_args`)
- Options flow: `cli/commands.py` → `save_messages_with_status` → `save_messages` → `save_messages_as_txt`
- Media detection: serialized message dicts have `media` field (dict with `_` key for type, e.g. `MessageMediaPhoto`)
- Also need to support `convert` command path (JSON→TXT)

## Development Approach
- **Testing approach**: Regular (code first, then tests)
- Complete each task fully before moving to the next
- **CRITICAL: every task MUST include new/updated tests**
- **CRITICAL: all tests must pass before starting next task**

## Implementation Steps

### Task 1: Add CLI flag and plumb through options
- [ ] Add `media_placeholders: bool = False` to `CLIOptions` in `cli/arguments.py`
- [ ] Add `--media-placeholders` argument to `parse_args()` in `cli/arguments.py`
- [ ] Add `media_placeholders` param to `save_messages_with_status()` in `cli/commands.py`
- [ ] Pass `args.media_placeholders` at all 4 call sites in `commands.py` (lines ~389, ~406, ~424, and convert path)
- [ ] Add `media_placeholders` param to `save_messages()` in `core/messages.py`
- [ ] Pass it through to `save_messages_as_txt()` call
- [ ] Write tests for CLI flag parsing (on/off)
- [ ] Run tests - must pass before next task

### Task 2: Implement media placeholder generation
- [ ] Add `_get_media_placeholder(media_dict: dict) -> Optional[str]` method to `MessagesMixin` in `core/messages.py`
  - `MessageMediaPhoto` → `[photo]`
  - `MessageMediaDocument` → `[file=filename]` (extract from `document.attributes` where `_=DocumentAttributeFilename`), fall back to `[file]`
  - Check `DocumentAttributeVideo` → `[video]`, `DocumentAttributeAudio` → `[audio]`, `DocumentAttributeSticker` → `[sticker]`
  - `MessageMediaContact` → `[contact]`
  - `MessageMediaGeo` / `MessageMediaGeoLive` → `[location]`
  - `MessageMediaVenue` → `[location]`
  - `MessageMediaPoll` → `[poll]`
  - `MessageMediaDice` → `[dice]`
  - `MessageMediaGame` → `[game]`
  - `MessageMediaWebPage` → `None` (web previews are not attachments)
  - Unknown media → `[media]`
- [ ] In `save_messages_as_txt()`, when `media_placeholders=True`, call `_get_media_placeholder(msg.get("media"))` and append on a new line after the text
- [ ] Write unit tests for `_get_media_placeholder` with all media types
- [ ] Write tests for `save_messages_as_txt` with media_placeholders enabled
- [ ] Run tests - must pass before next task

### Task 3: Verify acceptance criteria
- [ ] Verify: flag off by default (no change to existing output)
- [ ] Verify: `[photo]`, `[file=filename.ext]`, `[video]`, `[audio]`, `[sticker]` etc. all work
- [ ] Verify: placeholder appears on separate line after text
- [ ] Verify: media-only messages show just the placeholder
- [ ] Run full test suite
- [ ] Run linter (`black`, `isort`)

### Task 4: [Final] Update documentation
- [ ] Update README.md CLI flags section if it lists all flags
- [ ] Update CLAUDE.md if needed

## Technical Details

### Placeholder format
```
[photo]
[video]
[audio]
[sticker]  
[file=document.pdf]
[file]              (no filename available)
[contact]
[location]
[poll]
[dice]
[game]
[media]             (unknown media type)
```

### Serialized media dict structure (from Telethon `to_dict()`)
```python
# Photo
{"_": "MessageMediaPhoto", "photo": {"_": "Photo", "id": 123, ...}}

# Document with filename
{"_": "MessageMediaDocument", "document": {"_": "Document", "attributes": [{"_": "DocumentAttributeFilename", "file_name": "report.pdf"}], ...}}

# Document with video attribute  
{"_": "MessageMediaDocument", "document": {"_": "Document", "attributes": [{"_": "DocumentAttributeVideo", ...}], ...}}
```

### TXT output example (with flag on)
```
2024-01-15 12:30:00 Alice:
Check this out
[photo]

2024-01-15 12:31:00 Bob:
[file=report.pdf]

```

## Post-Completion
- Test manually with a real chat export containing media messages
